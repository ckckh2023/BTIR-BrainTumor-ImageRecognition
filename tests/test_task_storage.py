'''任务元数据与清理流程的基础回归测试'''

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from contextlib import redirect_stderr, redirect_stdout
from dataclasses import replace
from io import StringIO
import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
import sqlite3
from threading import Barrier
from unittest.mock import patch

from Main import _build_parser, main
from core.settings import SETTINGS
from core.task_definitions import TaskStatus
from core.task_records import StoredTaskInput, TaskRecord
from repositories.task_repository_contracts import (
    TaskNotFoundError,
    TaskQuotaExceededError,
    TaskRepositoryUnavailableError,
)
from repositories.sqlite_task_repository import CURRENT_SCHEMA_VERSION, SqliteTaskRepository
from repositories.user_repository import SqliteUserRepository
from services.cleanup_service import clear_generated_files
from services.task_queue import TaskReconciliationReport


class TaskStorageTests(unittest.TestCase):
    '''使用临时目录验证 SQLite 任务存储与清理流程'''

    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.project_root = Path(self.temporary_directory.name)
        self.output_dir = self.project_root / "output"
        self.archive_dir = self.project_root / "archive"
        self.repository = SqliteTaskRepository(self.project_root / "tasks.db")
        self.cli_settings = replace(SETTINGS, task_archive_dir=self.archive_dir)

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    @staticmethod
    def _record(task_id: str, status: TaskStatus = TaskStatus.CREATED) -> TaskRecord:
        now = datetime.fromisoformat("2026-01-01T00:00:00+00:00")
        return TaskRecord(
            task_id=task_id,
            name=f"测试任务 {task_id}",
            status=status,
            created_at=now,
            updated_at=now,
            input=StoredTaskInput(
                size_bytes=1,
                sha256="a" * 64,
            ),
        )

    def test_save_load_and_update_task(self) -> None:
        task_dir = self.output_dir / "task-001"
        task_dir.mkdir(parents=True)
        self.repository.save(task_dir, self._record(task_dir.name))

        self.assertTrue(self.repository.exists(task_dir))
        self.assertEqual(self.repository.count(), 1)
        self.assertEqual(self.repository.load(task_dir).status, TaskStatus.CREATED)

        record = self.repository.load(task_dir)
        record.status = TaskStatus.QUEUED
        self.repository.save(task_dir, record)

        self.assertEqual(self.repository.load(task_dir).status, TaskStatus.QUEUED)

    def test_missing_task_raises_not_found_error(self) -> None:
        with self.assertRaises(TaskNotFoundError):
            self.repository.load(self.output_dir / "missing-task")

    def test_task_owner_is_preserved_across_regular_updates(self) -> None:
        task_dir = self.output_dir / "owned-task"
        task_dir.mkdir(parents=True)
        record = self._record(task_dir.name)
        self.repository.save(task_dir, record, user_id="owner-a")

        record.status = TaskStatus.QUEUED
        self.repository.save(task_dir, record, user_id="owner-b")

        self.assertEqual(self.repository.get_task_user_id(task_dir.name), "owner-a")

    def test_missing_task_owner_lookup_raises_not_found(self) -> None:
        with self.assertRaises(TaskNotFoundError):
            self.repository.get_task_user_id("missing-task")

    def test_unowned_tasks_require_explicit_operator_assignment(self) -> None:
        task_dir = self.output_dir / "legacy-task"
        task_dir.mkdir(parents=True)
        self.repository.save(task_dir, self._record(task_dir.name))

        self.assertEqual(self.repository.count_unowned_tasks(), 1)
        self.assertIsNone(self.repository.get_task_user_id(task_dir.name))

        changed = self.repository.assign_unowned_tasks("owner-a")

        self.assertEqual(changed, 1)
        self.assertEqual(self.repository.count_unowned_tasks(), 0)
        self.assertEqual(self.repository.get_task_user_id(task_dir.name), "owner-a")

    def test_claim_legacy_tasks_command_previews_then_assigns(self) -> None:
        task_dir = self.output_dir / "legacy-cli-task"
        task_dir.mkdir(parents=True)
        self.repository.save(task_dir, self._record(task_dir.name))
        SqliteUserRepository(self.repository).create_user(
            username="legacy_owner",
            hashed_password="not-used-by-command",
        )

        with (
            patch("Main.task_repository", self.repository),
            redirect_stdout(StringIO()) as preview_output,
        ):
            self.assertEqual(main(["claim-legacy-tasks", "legacy_owner"]), 0)
        self.assertIn("1 条", preview_output.getvalue())
        self.assertEqual(self.repository.count_unowned_tasks(), 1)

        with (
            patch("Main.task_repository", self.repository),
            redirect_stdout(StringIO()) as apply_output,
        ):
            self.assertEqual(
                main(["claim-legacy-tasks", "legacy_owner", "--apply"]),
                0,
            )
        self.assertIn("已把 1 条", apply_output.getvalue())
        self.assertEqual(self.repository.count_unowned_tasks(), 0)

    def test_user_management_commands_update_account_state(self) -> None:
        with (
            patch("Main.task_repository", self.repository),
            patch("Main.SETTINGS", self.cli_settings),
            patch("Main.getpass.getpass", side_effect=["safe-password", "safe-password"]),
            patch("Main.hash_password", side_effect=lambda value: f"hash:{value}"),
            redirect_stdout(StringIO()),
        ):
            self.assertEqual(main(["user", "create", "alice"]), 0)

        user_repository = SqliteUserRepository(self.repository)
        created = user_repository.get_by_username("alice")
        self.assertIsNotNone(created)
        self.assertEqual(created.hashed_password, "hash:safe-password")
        self.assertEqual(created.role.value, "user")

        with (
            patch("Main.task_repository", self.repository),
            patch("Main.SETTINGS", self.cli_settings),
            redirect_stdout(StringIO()),
        ):
            self.assertEqual(main(["user", "set-role", "alice", "admin"]), 0)
        promoted = user_repository.get_by_username("alice")
        self.assertEqual(promoted.role.value, "admin")
        self.assertEqual(promoted.token_version, 1)

        with (
            patch("Main.task_repository", self.repository),
            patch("Main.SETTINGS", self.cli_settings),
            redirect_stdout(StringIO()),
        ):
            self.assertEqual(main(["user", "disable", "alice"]), 0)
        disabled = user_repository.get_by_username("alice")
        self.assertFalse(disabled.is_active)
        self.assertEqual(disabled.token_version, 2)

        with (
            patch("Main.task_repository", self.repository),
            patch("Main.SETTINGS", self.cli_settings),
            redirect_stdout(StringIO()),
        ):
            self.assertEqual(main(["user", "enable", "alice"]), 0)
        enabled = user_repository.get_by_username("alice")
        self.assertTrue(enabled.is_active)
        self.assertEqual(enabled.token_version, 2)

        with (
            patch("Main.task_repository", self.repository),
            patch("Main.SETTINGS", self.cli_settings),
            patch("Main.getpass.getpass", side_effect=["new-password", "new-password"]),
            patch("Main.hash_password", side_effect=lambda value: f"hash:{value}"),
            redirect_stdout(StringIO()),
        ):
            self.assertEqual(main(["user", "reset-password", "alice"]), 0)
        reset = user_repository.get_by_username("alice")
        self.assertEqual(reset.hashed_password, "hash:new-password")
        self.assertEqual(reset.token_version, 3)
        self.assertTrue(reset.must_change_password)
        audit_text = (self.archive_dir / "audit.jsonl").read_text(encoding="utf-8")
        self.assertIn('"operation": "user_created_cli"', audit_text)
        self.assertIn('"operation": "user_role_changed_cli"', audit_text)
        self.assertIn('"operation": "user_status_changed_cli"', audit_text)
        self.assertIn('"operation": "password_reset_cli"', audit_text)

    def test_task_quota_check_is_atomic_across_concurrent_writes(self) -> None:
        user = SqliteUserRepository(self.repository).create_user(
            "quota-user",
            "password-hash",
        )
        task_dirs = [self.output_dir / f"quota-task-{index}" for index in range(2)]
        for task_dir in task_dirs:
            task_dir.mkdir(parents=True)
        barrier = Barrier(2)

        def save_task(task_dir: Path) -> str:
            barrier.wait()
            try:
                self.repository.save(
                    task_dir,
                    self._record(task_dir.name),
                    user_id=user.user_id,
                    max_tasks_per_user=1,
                )
            except TaskQuotaExceededError:
                return "limited"
            return "saved"

        with ThreadPoolExecutor(max_workers=2) as executor:
            outcomes = list(executor.map(save_task, task_dirs))

        self.assertCountEqual(outcomes, ["saved", "limited"])
        self.assertEqual(self.repository.count(user_id=user.user_id), 1)

    def test_list_tasks_supports_status_filter_and_pagination(self) -> None:
        task_ids = ["task-001", "task-002", "task-003"]
        statuses = [TaskStatus.CREATED, TaskStatus.FAILED, TaskStatus.FAILED]
        for index, (task_id, status) in enumerate(zip(task_ids, statuses, strict=True)):
            task_dir = self.output_dir / task_id
            task_dir.mkdir(parents=True)
            record = self._record(task_id, status)
            record.created_at = datetime.fromisoformat(
                f"2026-01-0{index + 1}T00:00:00+00:00"
            )
            self.repository.save(task_dir, record)

        failed_records, failed_total = self.repository.list_tasks(
            limit=1,
            offset=0,
            status=TaskStatus.FAILED,
        )

        self.assertEqual(failed_total, 2)
        self.assertEqual([record.task_id for record in failed_records], ["task-003"])

    def test_list_tasks_supports_search_time_range_and_excludes_archived(self) -> None:
        records = [
            ("task-alpha", "Patient Alpha", "2026-01-01T00:00:00+00:00", None),
            ("task-beta", "Patient Beta", "2026-01-02T00:00:00+00:00", None),
            (
                "task-archived",
                "Patient Alpha archived",
                "2026-01-03T00:00:00+00:00",
                "2026-01-04T00:00:00+00:00",
            ),
        ]
        for task_id, name, created_at, archived_at in records:
            task_dir = self.output_dir / task_id
            task_dir.mkdir(parents=True)
            record = self._record(task_id)
            record.name = name
            record.created_at = datetime.fromisoformat(created_at)
            record.archived_at = (
                datetime.fromisoformat(archived_at) if archived_at is not None else None
            )
            self.repository.save(task_dir, record)

        matched_records, matched_total = self.repository.list_tasks(
            limit=20,
            offset=0,
            query="PATIENT ALPHA",
            created_from=datetime.fromisoformat("2025-12-31T16:00:00-08:00"),
            created_to=datetime.fromisoformat("2026-01-02T00:00:00+00:00"),
        )

        self.assertEqual(matched_total, 1)
        self.assertEqual([record.task_id for record in matched_records], ["task-alpha"])

        active_records, active_total = self.repository.list_tasks(limit=20, offset=0)
        self.assertEqual(active_total, 2)
        self.assertNotIn(
            "task-archived",
            {record.task_id for record in active_records},
        )

    def test_list_archived_tasks_supports_filters_and_pagination(self) -> None:
        records = [
            (
                "task-active",
                "Patient Alpha active",
                TaskStatus.SUCCEEDED,
                None,
            ),
            (
                "task-archived-old",
                "Patient Alpha archived",
                TaskStatus.FAILED,
                "2026-01-03T00:00:00+00:00",
            ),
            (
                "task-archived-new",
                "Patient Beta archived",
                TaskStatus.SUCCEEDED,
                "2026-01-04T00:00:00+00:00",
            ),
        ]
        for task_id, name, task_status, archived_at in records:
            task_dir = self.output_dir / task_id
            task_dir.mkdir(parents=True)
            record = self._record(task_id, task_status)
            record.name = name
            record.archived_at = (
                datetime.fromisoformat(archived_at) if archived_at is not None else None
            )
            self.repository.save(task_dir, record)

        archived_records, archived_total = self.repository.list_archived_tasks(
            limit=1,
            offset=0,
        )
        self.assertEqual(archived_total, 2)
        self.assertEqual(
            [record.task_id for record in archived_records],
            ["task-archived-new"],
        )

        matched_records, matched_total = self.repository.list_archived_tasks(
            limit=20,
            offset=0,
            status=TaskStatus.FAILED,
            query="PATIENT ALPHA",
        )
        self.assertEqual(matched_total, 1)
        self.assertEqual(
            [record.task_id for record in matched_records],
            ["task-archived-old"],
        )

    def test_list_active_tasks_excludes_terminal_records(self) -> None:
        task_statuses = {
            "task-created": TaskStatus.CREATED,
            "task-queued": TaskStatus.QUEUED,
            "task-running": TaskStatus.RUNNING,
            "task-cancel-requested": TaskStatus.CANCEL_REQUESTED,
            "task-succeeded": TaskStatus.SUCCEEDED,
            "task-failed": TaskStatus.FAILED,
            "task-canceled": TaskStatus.CANCELED,
        }
        for task_id, task_status in task_statuses.items():
            task_dir = self.output_dir / task_id
            task_dir.mkdir(parents=True)
            self.repository.save(task_dir, self._record(task_id, task_status))

        active_records = self.repository.list_active_tasks(limit=100)

        self.assertEqual(
            {record.task_id for record in active_records},
            {"task-queued", "task-running", "task-cancel-requested"},
        )

    def test_reconcile_command_runs_the_active_task_sweep(self) -> None:
        report = TaskReconciliationReport(
            scanned_task_count=1,
            changed_task_ids=["task-queued"],
            skipped_task_ids=[],
        )
        stdout = StringIO()

        with (
            patch("Main.reconcile_active_tasks", return_value=report) as reconcile,
            redirect_stdout(stdout),
        ):
            exit_code = main(["reconcile-tasks", "--limit", "2"])

        self.assertEqual(exit_code, 0)
        reconcile.assert_called_once_with(limit=2)
        self.assertIn("状态已修复：1 条", stdout.getvalue())

    def test_game_command_bypasses_the_regular_command_parser(self) -> None:
        with patch("Main.run_game", return_value=0) as game:
            exit_code = main(["game"])

        self.assertEqual(exit_code, 0)
        game.assert_called_once_with()

    def test_model_commands_require_an_existing_task_id(self) -> None:
        parser = _build_parser()
        with redirect_stderr(StringIO()), self.assertRaises(SystemExit) as raised:
            parser.parse_args(["run"])

        self.assertEqual(raised.exception.code, 2)
        parsed = parser.parse_args(["run", "--task-id", "task-001"])
        self.assertEqual(parsed.task_id, "task-001")

    def test_unavailable_database_raises_storage_error(self) -> None:
        blocked_parent = self.project_root / "not-a-directory"
        blocked_parent.write_text("blocked", encoding="utf-8")

        with self.assertRaises(TaskRepositoryUnavailableError):
            SqliteTaskRepository(blocked_parent / "tasks.db")

    def test_query_indexes_are_created_for_task_listing_and_archiving(self) -> None:
        connection = sqlite3.connect(self.repository.database_path)
        try:
            index_names = {
                row[1]
                for row in connection.execute("PRAGMA index_list(tasks)").fetchall()
            }
        finally:
            connection.close()

        self.assertTrue(
            {
                "idx_tasks_created_at_task_id",
                "idx_tasks_status_created_at_task_id",
                "idx_tasks_status_updated_at_task_id",
                "idx_tasks_archived_at_task_id",
            }.issubset(index_names)
        )

    def test_schema_migrations_are_recorded_for_a_fresh_database(self) -> None:
        connection = sqlite3.connect(self.repository.database_path)
        try:
            versions = [
                row[0]
                for row in connection.execute(
                    "SELECT version FROM schema_migrations ORDER BY version"
                ).fetchall()
            ]
        finally:
            connection.close()

        self.assertEqual(versions, list(range(1, CURRENT_SCHEMA_VERSION + 1)))

    def test_existing_users_default_to_user_role_during_migration(self) -> None:
        database_path = self.project_root / "user-role-migration.db"
        repository = SqliteTaskRepository(database_path)
        user_repository = SqliteUserRepository(repository)
        user_repository.create_user("legacy_user", "password-hash")

        connection = sqlite3.connect(database_path)
        try:
            connection.execute("ALTER TABLE users RENAME TO users_with_role")
            connection.execute(
                """
                CREATE TABLE users (
                    user_id TEXT PRIMARY KEY,
                    username TEXT NOT NULL UNIQUE,
                    hashed_password TEXT NOT NULL,
                    is_active INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    token_version INTEGER NOT NULL DEFAULT 0
                )
                """
            )
            connection.execute(
                """
                INSERT INTO users (
                    user_id, username, hashed_password, is_active,
                    created_at, updated_at, token_version
                )
                SELECT user_id, username, hashed_password, is_active,
                       created_at, updated_at, token_version
                FROM users_with_role
                """
            )
            connection.execute("DROP TABLE users_with_role")
            connection.execute("DELETE FROM schema_migrations WHERE version >= 10")
            connection.commit()
        finally:
            connection.close()

        migrated_repository = SqliteTaskRepository(database_path)
        migrated_user = SqliteUserRepository(migrated_repository).get_by_username(
            "legacy_user"
        )

        self.assertIsNotNone(migrated_user)
        self.assertEqual(migrated_user.role.value, "user")

    def test_username_normalization_migration_rejects_case_only_duplicates(self) -> None:
        database_path = self.project_root / "username-normalization-conflict.db"
        SqliteTaskRepository(database_path)
        connection = sqlite3.connect(database_path)
        try:
            connection.execute("ALTER TABLE users RENAME TO users_with_normalized_name")
            connection.execute(
                """
                CREATE TABLE users (
                    user_id TEXT PRIMARY KEY,
                    username TEXT NOT NULL UNIQUE,
                    hashed_password TEXT NOT NULL,
                    is_active INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    token_version INTEGER NOT NULL DEFAULT 0,
                    role TEXT NOT NULL DEFAULT 'user',
                    must_change_password INTEGER NOT NULL DEFAULT 0
                )
                """
            )
            connection.executemany(
                """
                INSERT INTO users (
                    user_id, username, hashed_password, is_active,
                    created_at, updated_at, token_version, role,
                    must_change_password
                )
                VALUES (?, ?, 'hash', 1, '2026-01-01', '2026-01-01', 0, 'user', 0)
                """,
                (("user-a", "Alice"), ("user-b", "alice")),
            )
            connection.execute("DROP TABLE users_with_normalized_name")
            connection.execute("DELETE FROM schema_migrations WHERE version = 12")
            connection.commit()
        finally:
            connection.close()

        with self.assertRaisesRegex(
            TaskRepositoryUnavailableError,
            "仅大小写不同的重复用户名",
        ):
            SqliteTaskRepository(database_path)

    def test_legacy_database_is_upgraded_without_losing_task_rows(self) -> None:
        legacy_database_path = self.project_root / "legacy-tasks.db"
        connection = sqlite3.connect(legacy_database_path)
        try:
            connection.execute(
                """
                CREATE TABLE tasks (
                    task_id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    record_json TEXT NOT NULL
                )
                """
            )
            connection.execute(
                """
                INSERT INTO tasks (task_id, name, status, created_at, updated_at, record_json)
                VALUES ('legacy-task', '旧任务', 'succeeded', '2026-01-01', '2026-01-01', '{}')
                """
            )
            connection.commit()
        finally:
            connection.close()

        SqliteTaskRepository(legacy_database_path)

        connection = sqlite3.connect(legacy_database_path)
        try:
            columns = {
                row[1] for row in connection.execute("PRAGMA table_info(tasks)").fetchall()
            }
            task_id = connection.execute(
                "SELECT task_id FROM tasks WHERE task_id = 'legacy-task'"
            ).fetchone()[0]
            migrated_version = connection.execute(
                "SELECT MAX(version) FROM schema_migrations"
            ).fetchone()[0]
        finally:
            connection.close()

        self.assertIn("archived_at", columns)
        self.assertEqual(task_id, "legacy-task")
        self.assertEqual(migrated_version, CURRENT_SCHEMA_VERSION)

    def test_completed_status_is_normalized_by_schema_migration(self) -> None:
        legacy_database_path = self.project_root / "completed-status.db"
        connection = sqlite3.connect(legacy_database_path)
        try:
            connection.execute(
                """
                CREATE TABLE tasks (
                    task_id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    archived_at TEXT,
                    record_json TEXT NOT NULL
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE schema_migrations (
                    version INTEGER PRIMARY KEY,
                    name TEXT NOT NULL,
                    applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            connection.executemany(
                "INSERT INTO schema_migrations (version, name) VALUES (?, ?)",
                [(1, "create_tasks_table"), (2, "add_archived_at"), (3, "create_task_indexes")],
            )
            connection.execute(
                """
                INSERT INTO tasks (task_id, name, status, created_at, updated_at, record_json)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    "completed-task",
                    "旧完成任务",
                    "completed",
                    "2026-01-01",
                    "2026-01-01",
                    json.dumps({"task_id": "completed-task", "status": "completed"}),
                ),
            )
            connection.commit()
        finally:
            connection.close()

        SqliteTaskRepository(legacy_database_path)

        connection = sqlite3.connect(legacy_database_path)
        try:
            status, record_json = connection.execute(
                "SELECT status, record_json FROM tasks WHERE task_id = 'completed-task'"
            ).fetchone()
        finally:
            connection.close()

        self.assertEqual(status, TaskStatus.SUCCEEDED.value)
        self.assertEqual(json.loads(record_json)["status"], TaskStatus.SUCCEEDED.value)

    def test_source_file_is_normalized_by_schema_migration(self) -> None:
        legacy_database_path = self.project_root / "source-file.db"
        connection = sqlite3.connect(legacy_database_path)
        try:
            connection.execute(
                """
                CREATE TABLE tasks (
                    task_id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    archived_at TEXT,
                    record_json TEXT NOT NULL
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE schema_migrations (
                    version INTEGER PRIMARY KEY,
                    name TEXT NOT NULL,
                    applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            connection.executemany(
                "INSERT INTO schema_migrations (version, name) VALUES (?, ?)",
                [
                    (1, "create_tasks_table"),
                    (2, "add_archived_at"),
                    (3, "create_task_indexes"),
                    (4, "normalize_completed_status"),
                ],
            )
            record = self._record("source-file-task")
            record_data = record.model_dump(mode="json")
            record_data["input"]["source_file"] = "legacy-scan.png"
            connection.execute(
                """
                INSERT INTO tasks (
                    task_id, name, status, created_at, updated_at, archived_at, record_json
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record.task_id,
                    record.name,
                    record.status.value,
                    record.created_at.isoformat(),
                    record.updated_at.isoformat(),
                    None,
                    json.dumps(record_data),
                ),
            )
            connection.commit()
        finally:
            connection.close()

        repository = SqliteTaskRepository(legacy_database_path)
        migrated = repository.load(self.output_dir / "source-file-task")

        self.assertEqual(migrated.input.original_filename, "legacy-scan.png")
        self.assertNotIn("source_file", migrated.input.model_dump())

    def test_dry_run_keeps_output_and_database_records(self) -> None:
        task_dir = self.output_dir / "task-002"
        task_dir.mkdir(parents=True)
        (task_dir / "result.json").write_text("{}", encoding="utf-8")
        self.repository.save(task_dir, self._record(task_dir.name))
        archived_task_dir = self.archive_dir / "tasks" / "task-archived-dry-run"
        archived_task_dir.mkdir(parents=True)
        archived_record = self._record(archived_task_dir.name)
        archived_record.archived_at = archived_record.updated_at
        self.repository.save(archived_task_dir, archived_record)
        user_repository = SqliteUserRepository(self.repository)
        user_repository.create_user("dry_run_user", "password-hash")

        clear_generated_files(
            self.project_root,
            self.output_dir,
            self.archive_dir,
            dry_run=True,
            task_repository=self.repository,
            user_repository=user_repository,
        )

        self.assertTrue(task_dir.exists())
        self.assertTrue(archived_task_dir.exists())
        self.assertEqual(self.repository.count(), 2)
        self.assertIsNotNone(user_repository.get_by_username("dry_run_user"))

    def test_clear_deletes_all_business_data_and_generated_files(self) -> None:
        task_dir = self.output_dir / "task-003"
        task_dir.mkdir(parents=True)
        (task_dir / "result.json").write_text("{}", encoding="utf-8")
        self.repository.save(task_dir, self._record(task_dir.name))

        archived_task_dir = self.archive_dir / "tasks" / "task-archived"
        archived_task_dir.mkdir(parents=True)
        (archived_task_dir / "result.json").write_text("{}", encoding="utf-8")
        archived_record = self._record(archived_task_dir.name)
        archived_record.archived_at = archived_record.updated_at
        self.repository.save(archived_task_dir, archived_record)
        (self.archive_dir / "audit.jsonl").write_text(
            '{"operation":"archive"}\n',
            encoding="utf-8",
        )
        user_repository = SqliteUserRepository(self.repository)
        user_repository.create_user("clear_user", "password-hash")

        clear_generated_files(
            self.project_root,
            self.output_dir,
            self.archive_dir,
            dry_run=False,
            task_repository=self.repository,
            user_repository=user_repository,
        )

        self.assertFalse(self.output_dir.exists())
        self.assertFalse(self.archive_dir.exists())
        self.assertEqual(self.repository.count(), 0)
        self.assertIsNone(user_repository.get_by_username("clear_user"))

    def test_clear_command_does_not_accept_an_arbitrary_output_directory(self) -> None:
        parser = _build_parser()
        with (
            redirect_stderr(StringIO()),
            self.assertRaises(SystemExit) as raised,
        ):
            parser.parse_args(["clear", "--output-dir", "outside"])

        self.assertEqual(raised.exception.code, 2)


if __name__ == "__main__":
    unittest.main()

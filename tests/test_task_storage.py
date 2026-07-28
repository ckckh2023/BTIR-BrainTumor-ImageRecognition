'''任务元数据与清理流程的基础回归测试'''

from __future__ import annotations

from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
import sqlite3
from unittest.mock import patch

from Main import _build_parser, main
from core.task_definitions import TaskStatus
from core.task_records import StoredTaskInput, TaskRecord
from repositories.task_repository_contracts import (
    TaskNotFoundError,
    TaskRepositoryUnavailableError,
)
from repositories.sqlite_task_repository import CURRENT_SCHEMA_VERSION, SqliteTaskRepository
from services.cleanup_service import clear_generated_files
from services.task_queue import TaskReconciliationReport


class TaskStorageTests(unittest.TestCase):
    '''使用临时目录验证 SQLite 任务存储与清理流程'''

    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.project_root = Path(self.temporary_directory.name)
        self.output_dir = self.project_root / "output"
        self.repository = SqliteTaskRepository(self.project_root / "tasks.db")

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
                path="input/image.png",
                storage_mode="uploaded",
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
        for command in ("classify", "segment", "all"):
            with (
                self.subTest(command=command),
                redirect_stderr(StringIO()),
                self.assertRaises(SystemExit) as raised,
            ):
                parser.parse_args([command, "legacy-image.png"])

            self.assertEqual(raised.exception.code, 2)
            parsed = parser.parse_args([command, "--task-id", "task-001"])
            self.assertEqual(parsed.task_id, "task-001")
            self.assertFalse(hasattr(parsed, "image_path"))
            self.assertFalse(hasattr(parsed, "input_mode"))

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

        clear_generated_files(
            self.project_root,
            self.output_dir,
            self.project_root / "segmenter",
            dry_run=True,
            task_repository=self.repository,
            clear_task_metadata=True,
        )

        self.assertTrue(task_dir.exists())
        self.assertEqual(self.repository.count(), 1)

    def test_clear_default_output_deletes_files_and_database_records(self) -> None:
        task_dir = self.output_dir / "task-003"
        task_dir.mkdir(parents=True)
        (task_dir / "result.json").write_text("{}", encoding="utf-8")
        self.repository.save(task_dir, self._record(task_dir.name))

        clear_generated_files(
            self.project_root,
            self.output_dir,
            self.project_root / "segmenter",
            dry_run=False,
            task_repository=self.repository,
            clear_task_metadata=True,
        )

        self.assertFalse(self.output_dir.exists())
        self.assertEqual(self.repository.count(), 0)

    def test_clear_custom_output_keeps_database_records(self) -> None:
        default_task_dir = self.output_dir / "task-004"
        default_task_dir.mkdir(parents=True)
        self.repository.save(default_task_dir, self._record(default_task_dir.name))

        custom_output_dir = self.project_root / "custom-output"
        (custom_output_dir / "temporary.txt").parent.mkdir(parents=True)
        (custom_output_dir / "temporary.txt").write_text("temporary", encoding="utf-8")

        clear_generated_files(
            self.project_root,
            custom_output_dir,
            self.project_root / "segmenter",
            dry_run=False,
            task_repository=self.repository,
            clear_task_metadata=False,
        )

        self.assertFalse(custom_output_dir.exists())
        self.assertEqual(self.repository.count(), 1)


if __name__ == "__main__":
    unittest.main()

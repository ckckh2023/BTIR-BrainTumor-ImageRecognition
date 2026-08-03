'''任务归档与永久删除安全边界的回归测试'''

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from contextlib import nullcontext
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from core.settings import SETTINGS
from core.task_definitions import TaskStatus
from core.task_records import StoredTaskInput, TaskRecord
from repositories.sqlite_task_repository import SqliteTaskRepository
from repositories.task_repository_contracts import TaskNotFoundError
from services.audit_service import append_audit_event, list_audit_events
from services.archive_service import (
    archive_expired_tasks,
    archive_task,
    purge_expired_archives,
    restore_task,
)


class TaskArchiveTests(unittest.TestCase):
    '''验证归档只移动符合策略的任务，永久删除仅作用于归档区。'''

    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary_directory.name)
        self.output_dir = self.root / "output"
        self.archive_dir = self.root / "archive"
        self.repository = SqliteTaskRepository(self.root / "tasks.db")
        self.now = datetime(2026, 7, 21, tzinfo=timezone.utc)
        self.settings = replace(
            SETTINGS,
            task_cleanup_enabled=True,
            succeeded_task_retention_days=30,
            failed_task_retention_days=7,
            task_archive_grace_days=7,
        )

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    @staticmethod
    def _no_lock(_: str):
        return nullcontext()

    def _create_task(self, task_id: str, status: TaskStatus, updated_at: datetime) -> Path:
        task_dir = self.output_dir / task_id
        task_dir.mkdir(parents=True)
        (task_dir / "result.json").write_text("{}", encoding="utf-8")
        self.repository.save(
            task_dir,
            TaskRecord(
                task_id=task_id,
                name=task_id,
                status=status,
                created_at=updated_at,
                updated_at=updated_at,
                input=StoredTaskInput(
                    size_bytes=1,
                    sha256="a" * 64,
                ),
            ),
        )
        return task_dir

    def test_archive_dry_run_never_moves_task_data(self) -> None:
        task_dir = self._create_task(
            "task-archive-preview",
            TaskStatus.SUCCEEDED,
            self.now - timedelta(days=31),
        )

        with patch("services.archive_service.SETTINGS", self.settings):
            report = archive_expired_tasks(
                dry_run=True,
                now=self.now,
                repository=self.repository,
                output_dir=self.output_dir,
                archive_dir=self.archive_dir,
            )

        self.assertEqual(report.processed_task_ids, [task_dir.name])
        self.assertTrue(task_dir.is_dir())
        self.assertFalse((self.archive_dir / "tasks" / task_dir.name).exists())

    def test_archive_moves_eligible_task_and_preserves_metadata(self) -> None:
        task_dir = self._create_task(
            "task-archive-apply",
            TaskStatus.FAILED,
            self.now - timedelta(days=8),
        )

        with (
            patch("services.archive_service.SETTINGS", self.settings),
            patch("services.archive_service.task_write_lock", self._no_lock),
        ):
            report = archive_expired_tasks(
                dry_run=False,
                now=self.now,
                repository=self.repository,
                output_dir=self.output_dir,
                archive_dir=self.archive_dir,
                cleanup_enabled=True,
            )

        archived_dir = self.archive_dir / "tasks" / task_dir.name
        self.assertEqual(report.processed_task_ids, [task_dir.name])
        self.assertFalse(task_dir.exists())
        self.assertTrue((archived_dir / "result.json").is_file())
        self.assertEqual(self.repository.load(archived_dir).archived_at, self.now)
        self.assertTrue((self.archive_dir / "audit.jsonl").is_file())

    def test_archive_moves_expired_canceled_task(self) -> None:
        task_dir = self._create_task(
            "task-canceled-archive",
            TaskStatus.CANCELED,
            self.now - timedelta(days=8),
        )

        with (
            patch("services.archive_service.SETTINGS", self.settings),
            patch("services.archive_service.task_write_lock", self._no_lock),
        ):
            report = archive_expired_tasks(
                dry_run=False,
                now=self.now,
                repository=self.repository,
                output_dir=self.output_dir,
                archive_dir=self.archive_dir,
                cleanup_enabled=True,
            )

        self.assertEqual(report.processed_task_ids, [task_dir.name])
        self.assertTrue((self.archive_dir / "tasks" / task_dir.name).is_dir())

    def test_manual_archive_moves_nonactive_task_and_is_idempotent(self) -> None:
        task_dir = self._create_task(
            "task-manual-archive",
            TaskStatus.CREATED,
            self.now,
        )

        with patch("services.archive_service.task_write_lock", self._no_lock):
            archived = archive_task(
                task_dir.name,
                actor_user_id="user-a",
                target_user_id="user-b",
                now=self.now,
                repository=self.repository,
                output_dir=self.output_dir,
                archive_dir=self.archive_dir,
            )
            repeated = archive_task(
                task_dir.name,
                now=self.now + timedelta(minutes=1),
                repository=self.repository,
                output_dir=self.output_dir,
                archive_dir=self.archive_dir,
            )

        archived_dir = self.archive_dir / "tasks" / task_dir.name
        self.assertFalse(task_dir.exists())
        self.assertTrue((archived_dir / "result.json").is_file())
        self.assertEqual(archived.archived_at, self.now)
        self.assertEqual(repeated.archived_at, self.now)
        self.assertIn(
            '"operation": "archive_api"',
            (self.archive_dir / "audit.jsonl").read_text(encoding="utf-8"),
        )
        self.assertIn(
            '"actor_user_id": "user-a"',
            (self.archive_dir / "audit.jsonl").read_text(encoding="utf-8"),
        )
        self.assertIn(
            '"target_user_id": "user-b"',
            (self.archive_dir / "audit.jsonl").read_text(encoding="utf-8"),
        )

    def test_manual_archive_rejects_active_tasks(self) -> None:
        for task_status in (
            TaskStatus.QUEUED,
            TaskStatus.RUNNING,
            TaskStatus.CANCEL_REQUESTED,
        ):
            with self.subTest(status=task_status):
                task_dir = self._create_task(
                    f"task-active-{task_status.value}",
                    task_status,
                    self.now,
                )
                with (
                    patch("services.archive_service.task_write_lock", self._no_lock),
                    self.assertRaisesRegex(ValueError, "不能删除"),
                ):
                    archive_task(
                        task_dir.name,
                        now=self.now,
                        repository=self.repository,
                        output_dir=self.output_dir,
                        archive_dir=self.archive_dir,
                    )

                self.assertTrue(task_dir.is_dir())
                self.assertIsNone(self.repository.load(task_dir).archived_at)

    def test_restore_moves_archived_task_back_to_output(self) -> None:
        task_dir = self._create_task(
            "task-restore",
            TaskStatus.SUCCEEDED,
            self.now,
        )
        restored_at = self.now + timedelta(hours=1)

        with patch("services.archive_service.task_write_lock", self._no_lock):
            archive_task(
                task_dir.name,
                now=self.now,
                repository=self.repository,
                output_dir=self.output_dir,
                archive_dir=self.archive_dir,
            )
            restored = restore_task(
                task_dir.name,
                actor_user_id="user-a",
                now=restored_at,
                repository=self.repository,
                output_dir=self.output_dir,
                archive_dir=self.archive_dir,
            )

        self.assertTrue((task_dir / "result.json").is_file())
        self.assertFalse((self.archive_dir / "tasks" / task_dir.name).exists())
        self.assertIsNone(restored.archived_at)
        self.assertEqual(restored.updated_at, restored_at)
        visible_tasks, total = self.repository.list_tasks(limit=20, offset=0)
        self.assertEqual(total, 1)
        self.assertEqual([record.task_id for record in visible_tasks], [task_dir.name])
        self.assertIn(
            '"operation": "restore_api"',
            (self.archive_dir / "audit.jsonl").read_text(encoding="utf-8"),
        )
        self.assertIn(
            '"actor_user_id": "user-a"',
            (self.archive_dir / "audit.jsonl").read_text(encoding="utf-8"),
        )

    def test_restore_rejects_task_that_is_not_archived(self) -> None:
        task_dir = self._create_task(
            "task-not-archived",
            TaskStatus.SUCCEEDED,
            self.now,
        )

        with self.assertRaisesRegex(ValueError, "未归档"):
            restore_task(
                task_dir.name,
                now=self.now,
                repository=self.repository,
                output_dir=self.output_dir,
                archive_dir=self.archive_dir,
            )

        self.assertTrue(task_dir.is_dir())

    def test_concurrent_audit_events_remain_valid_json_lines(self) -> None:
        def write_event(index: int) -> None:
            append_audit_event(
                operation="concurrent_test",
                timestamp=self.now + timedelta(microseconds=index),
                actor_user_id=f"user-{index}",
                outcome="success",
                source_ip="127.0.0.1",
                audit_dir=self.archive_dir,
            )

        with ThreadPoolExecutor(max_workers=8) as executor:
            list(executor.map(write_event, range(50)))

        events, total, invalid_lines = list_audit_events(
            audit_dir=self.archive_dir,
            limit=100,
            offset=0,
            operation="concurrent_test",
        )
        self.assertEqual(total, 50)
        self.assertEqual(len(events), 50)
        self.assertEqual(invalid_lines, 0)
        self.assertTrue(all(event["outcome"] == "success" for event in events))
        self.assertTrue(all(event["source_ip"] == "127.0.0.1" for event in events))

    def test_purge_removes_only_expired_archived_task(self) -> None:
        task_id = "task-purge-apply"
        archived_dir = self.archive_dir / "tasks" / task_id
        archived_dir.mkdir(parents=True)
        (archived_dir / "result.json").write_text("{}", encoding="utf-8")
        archived_at = self.now - timedelta(days=8)
        self.repository.save(
            archived_dir,
            TaskRecord(
                task_id=task_id,
                name=task_id,
                status=TaskStatus.SUCCEEDED,
                created_at=self.now - timedelta(days=40),
                updated_at=self.now - timedelta(days=40),
                archived_at=archived_at,
                input=StoredTaskInput(
                    size_bytes=1,
                    sha256="a" * 64,
                ),
            ),
        )

        with (
            patch("services.archive_service.SETTINGS", self.settings),
            patch("services.archive_service.task_write_lock", self._no_lock),
        ):
            report = purge_expired_archives(
                dry_run=False,
                now=self.now,
                repository=self.repository,
                archive_dir=self.archive_dir,
                cleanup_enabled=True,
            )

        self.assertEqual(report.processed_task_ids, [task_id])
        self.assertFalse(archived_dir.exists())
        with self.assertRaises(TaskNotFoundError):
            self.repository.load(archived_dir)

    def test_apply_requires_explicit_cleanup_enablement(self) -> None:
        self._create_task(
            "task-disabled",
            TaskStatus.SUCCEEDED,
            self.now - timedelta(days=31),
        )

        with self.assertRaisesRegex(ValueError, "自动清理未启用"):
            archive_expired_tasks(
                dry_run=False,
                now=self.now,
                repository=self.repository,
                output_dir=self.output_dir,
                archive_dir=self.archive_dir,
                cleanup_enabled=False,
            )


if __name__ == "__main__":
    unittest.main()

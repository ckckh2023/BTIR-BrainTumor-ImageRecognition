'''任务元数据与清理流程的基础回归测试'''

from __future__ import annotations

from contextlib import redirect_stdout
from io import StringIO
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
import sqlite3
from unittest.mock import patch

from Main import main
from core.task_definitions import TaskStatus
from core.task_records import StoredTaskInput, TaskRecord
from repositories.task_repository import (
    SqliteTaskRepository,
    TaskNotFoundError,
    TaskRepositoryUnavailableError,
)
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
            scanned_task_ids=["task-queued"],
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

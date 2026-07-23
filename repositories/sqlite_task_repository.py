'''SQLite 任务元数据仓储实现'''

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Iterator

from pydantic import ValidationError

from core.task_definitions import ACTIVE_ASYNC_TASK_STATUSES, TaskStatus
from core.task_records import TaskRecord
from repositories.task_repository import (
    TaskNotFoundError,
    TaskRepository,
    TaskRepositoryUnavailableError,
)


class SqliteTaskRepository:
    '''以 SQLite 保存任务元数据'''

    def __init__(self, database_path: Path) -> None:
        self.database_path = database_path
        self._initialize_database()

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        try:
            connection = sqlite3.connect(self.database_path, timeout=5)
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA busy_timeout = 5000")
        except sqlite3.Error as exc:
            raise TaskRepositoryUnavailableError("SQLite 任务数据库不可用") from exc

        try:
            yield connection
            connection.commit()
        except sqlite3.Error as exc:
            connection.rollback()
            raise TaskRepositoryUnavailableError("SQLite 任务数据库不可用") from exc
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def _initialize_database(self) -> None:
        try:
            self.database_path.parent.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise TaskRepositoryUnavailableError("SQLite 任务数据库不可用") from exc

        with self._connect() as connection:
            connection.execute("PRAGMA journal_mode = WAL")
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS tasks (
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
            columns = {
                row["name"]
                for row in connection.execute("PRAGMA table_info(tasks)").fetchall()
            }
            if "archived_at" not in columns:
                connection.execute("ALTER TABLE tasks ADD COLUMN archived_at TEXT")
            connection.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_tasks_created_at_task_id
                ON tasks (created_at DESC, task_id DESC)
                """
            )
            connection.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_tasks_status_created_at_task_id
                ON tasks (status, created_at DESC, task_id DESC)
                """
            )
            connection.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_tasks_status_updated_at_task_id
                ON tasks (status, updated_at ASC, task_id ASC)
                """
            )
            connection.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_tasks_archived_at_task_id
                ON tasks (archived_at ASC, task_id ASC)
                """
            )

    def exists(self, task_dir: Path) -> bool:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT 1 FROM tasks WHERE task_id = ?",
                (task_dir.name,),
            ).fetchone()
        return row is not None

    def load(self, task_dir: Path) -> TaskRecord:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT record_json FROM tasks WHERE task_id = ?",
                (task_dir.name,),
            ).fetchone()

        if row is None:
            raise TaskNotFoundError("任务元数据不存在")

        try:
            return TaskRecord.model_validate_json(row["record_json"])
        except (ValidationError, ValueError) as exc:
            raise ValueError("任务元数据格式无效") from exc

    def save(self, task_dir: Path, record: TaskRecord) -> Path:
        if record.task_id != task_dir.name:
            raise ValueError("任务 ID 与任务目录不一致")

        record_json = record.model_dump_json(exclude_none=True)
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO tasks (
                    task_id, name, status, created_at, updated_at, archived_at, record_json
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(task_id) DO UPDATE SET
                    name = excluded.name,
                    status = excluded.status,
                    updated_at = excluded.updated_at,
                    archived_at = excluded.archived_at,
                    record_json = excluded.record_json
                """,
                (
                    record.task_id,
                    record.name,
                    record.status.value,
                    record.created_at.isoformat(),
                    record.updated_at.isoformat(),
                    record.archived_at.isoformat() if record.archived_at else None,
                    record_json,
                ),
            )
        return self.database_path.resolve()

    def count(self) -> int:
        with self._connect() as connection:
            row = connection.execute("SELECT COUNT(*) AS total FROM tasks").fetchone()
        return int(row["total"])

    def list_tasks(
        self,
        *,
        limit: int,
        offset: int,
        status: TaskStatus | None = None,
    ) -> tuple[list[TaskRecord], int]:
        where_clause = ""
        parameters: tuple[object, ...] = ()
        if status is not None:
            where_clause = "WHERE status = ?"
            parameters = (status.value,)

        with self._connect() as connection:
            total_row = connection.execute(
                f"SELECT COUNT(*) AS total FROM tasks {where_clause}",
                parameters,
            ).fetchone()
            rows = connection.execute(
                f"""
                SELECT record_json FROM tasks
                {where_clause}
                ORDER BY created_at DESC, task_id DESC
                LIMIT ? OFFSET ?
                """,
                (*parameters, limit, offset),
            ).fetchall()

        return self._records_from_rows(rows), int(total_row["total"])

    def list_active_tasks(self, *, limit: int) -> list[TaskRecord]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT record_json FROM tasks
                WHERE archived_at IS NULL AND status IN (?, ?, ?)
                ORDER BY updated_at ASC, task_id ASC
                LIMIT ?
                """,
                (
                    *(task_status.value for task_status in ACTIVE_ASYNC_TASK_STATUSES),
                    limit,
                ),
            ).fetchall()
        return self._records_from_rows(rows)

    def list_archive_candidates(
        self,
        *,
        succeeded_before: datetime,
        failed_before: datetime,
        limit: int,
    ) -> list[TaskRecord]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT record_json FROM tasks
                WHERE archived_at IS NULL AND (
                    (status IN (?, ?) AND updated_at < ?) OR
                    (status IN (?, ?) AND updated_at < ?)
                )
                ORDER BY updated_at ASC, task_id ASC
                LIMIT ?
                """,
                (
                    TaskStatus.SUCCEEDED.value,
                    TaskStatus.COMPLETED.value,
                    succeeded_before.isoformat(),
                    TaskStatus.FAILED.value,
                    TaskStatus.CANCELED.value,
                    failed_before.isoformat(),
                    limit,
                ),
            ).fetchall()
        return self._records_from_rows(rows)

    def list_purge_candidates(
        self,
        *,
        archived_before: datetime,
        limit: int,
    ) -> list[TaskRecord]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT record_json FROM tasks
                WHERE archived_at IS NOT NULL AND archived_at < ?
                ORDER BY archived_at ASC, task_id ASC
                LIMIT ?
                """,
                (archived_before.isoformat(), limit),
            ).fetchall()
        return self._records_from_rows(rows)

    @staticmethod
    def _records_from_rows(rows: list[sqlite3.Row]) -> list[TaskRecord]:
        try:
            return [TaskRecord.model_validate_json(row["record_json"]) for row in rows]
        except (ValidationError, ValueError) as exc:
            raise ValueError("任务元数据格式无效") from exc

    def delete_all(self) -> int:
        with self._connect() as connection:
            cursor = connection.execute("DELETE FROM tasks")
        return cursor.rowcount

    def delete(self, task_id: str) -> None:
        with self._connect() as connection:
            connection.execute("DELETE FROM tasks WHERE task_id = ?", (task_id,))

    def health_check(self) -> None:
        with self._connect() as connection:
            connection.execute("SELECT 1").fetchone()

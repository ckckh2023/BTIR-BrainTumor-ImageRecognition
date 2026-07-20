'''SQLite 任务元数据仓储'''

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator, Protocol

from pydantic import ValidationError

from core.settings import SETTINGS
from core.task_records import TaskRecord


class TaskNotFoundError(LookupError):
    '''任务元数据不存在。'''


class TaskRepositoryUnavailableError(RuntimeError):
    '''任务元数据存储不可用。'''


class TaskRepository(Protocol):
    '''任务元数据存储的最小接口。'''

    def exists(self, task_dir: Path) -> bool:
        '''返回任务元数据是否存在。'''

    def load(self, task_dir: Path) -> TaskRecord:
        '''读取一条任务元数据。'''

    def save(self, task_dir: Path, record: TaskRecord) -> Path:
        '''保存一条任务元数据。'''

    def count(self) -> int:
        '''返回当前存储中的任务数量。'''

    def delete_all(self) -> int:
        '''删除全部任务元数据，并返回删除数量。'''

    def health_check(self) -> None:
        '''检查任务元数据存储是否可用。'''


class SqliteTaskRepository:
    '''以 SQLite 保存任务元数据。'''

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
                    record_json TEXT NOT NULL
                )
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
                    task_id, name, status, created_at, updated_at, record_json
                )
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(task_id) DO UPDATE SET
                    name = excluded.name,
                    status = excluded.status,
                    updated_at = excluded.updated_at,
                    record_json = excluded.record_json
                """,
                (
                    record.task_id,
                    record.name,
                    record.status.value,
                    record.created_at.isoformat(),
                    record.updated_at.isoformat(),
                    record_json,
                ),
            )
        return self.database_path.resolve()

    def count(self) -> int:
        with self._connect() as connection:
            row = connection.execute("SELECT COUNT(*) AS total FROM tasks").fetchone()
        return int(row["total"])

    def delete_all(self) -> int:
        with self._connect() as connection:
            cursor = connection.execute("DELETE FROM tasks")
        return cursor.rowcount

    def health_check(self) -> None:
        with self._connect() as connection:
            connection.execute("SELECT 1").fetchone()


task_repository: TaskRepository = SqliteTaskRepository(SETTINGS.task_database_path)

'''任务元数据的数据访问接口及 JSON 实现'''

from __future__ import annotations

import json
import os
import tempfile
import sqlite3
from contextlib import contextmanager
from core.settings import SETTINGS
from pathlib import Path
from typing import Any, Iterator, Protocol


class TaskNotFoundError(LookupError):
    '''任务元数据不存在'''


class TaskRepositoryUnavailableError(RuntimeError):
    '''任务元数据存储不可用'''


class TaskRepository(Protocol):
    '''任务元数据存储需要提供的最小接口'''

    def exists(self, task_dir: Path) -> bool:
        '''返回任务元数据是否存在'''

    def load(self, task_dir: Path) -> dict[str, Any]:
        '''读取一条任务元数据'''

    def save(self, task_dir: Path, record: dict[str, Any]) -> Path:
        '''保存一条任务元数据'''


    def count(self) -> int:
        '''返回当前存储中的任务数量'''

    def delete_all(self) -> int:
        '''删除当前存储中的全部任务元数据，并返回删除数量'''


    def health_check(self) -> None:
        '''检查任务元数据存储是否可用'''


class JsonTaskRepository:
    '''以任务目录中的 task.json 保存任务元数据'''

    filename = "task.json"

    def _path(self, task_dir: Path) -> Path:
        return task_dir / self.filename

    def exists(self, task_dir: Path) -> bool:
        return self._path(task_dir).is_file()

    def load(self, task_dir: Path) -> dict[str, Any]:
        path = self._path(task_dir)
        if not path.is_file():
            raise TaskNotFoundError("任务元数据不存在")

        try:
            record = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise ValueError("任务元数据格式无效") from exc

        if not isinstance(record, dict):
            raise ValueError("任务元数据格式无效")
        return record

    def save(self, task_dir: Path, record: dict[str, Any]) -> Path:
        path = self._path(task_dir)
        path.parent.mkdir(parents=True, exist_ok=True)
        file_descriptor, temporary_name = tempfile.mkstemp(
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            text=True,
        )
        temporary_path = Path(temporary_name)

        try:
            with os.fdopen(file_descriptor, "w", encoding="utf-8") as temporary_file:
                json.dump(record, temporary_file, ensure_ascii=False, indent=2)
                temporary_file.write("\n")
                temporary_file.flush()
                os.fsync(temporary_file.fileno())
            os.replace(temporary_path, path)
        except Exception:
            temporary_path.unlink(missing_ok=True)
            raise
        return path.resolve()


    def count(self) -> int:
        return 0

    def delete_all(self) -> int:
        return 0


    def health_check(self) -> None:
        return None


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
                    record_json TEXT NOT NULL
                )"""
            )


    def exists(self, task_dir: Path) -> bool:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT 1 FROM tasks WHERE task_id = ?",
                (task_dir.name,),
            ).fetchone()
        return row is not None
    

    def load(self, task_dir: Path) -> dict[str, Any]:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT record_json FROM tasks WHERE task_id = ?",
                (task_dir.name,),
            ).fetchone()

        if row is None:
            raise TaskNotFoundError("任务元数据不存在")

        try:
            record = json.loads(row["record_json"])
        except json.JSONDecodeError as exc:
            raise ValueError("任务元数据格式无效") from exc

        if not isinstance(record, dict):
            raise ValueError("任务元数据格式无效")
        return record


    def save(self, task_dir: Path, record: dict[str, Any]) -> Path:
        if record.get("task_id") != task_dir.name:
            raise ValueError("任务 ID 与任务目录不一致")

        record_json = json.dumps(record, ensure_ascii=False)

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
                    record["task_id"],
                    record["name"],
                    record["status"],
                    record["created_at"],
                    record["updated_at"],
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


task_repository: TaskRepository = SqliteTaskRepository(
    SETTINGS.task_database_path
)

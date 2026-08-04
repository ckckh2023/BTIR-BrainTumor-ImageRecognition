'''SQLite 任务元数据仓储实现'''

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Callable, Iterator

from pydantic import ValidationError

from core.task_definitions import ACTIVE_ASYNC_TASK_STATUSES, TaskStatus
from core.task_records import TaskRecord
from repositories.task_repository_contracts import (
    TaskNotFoundError,
    TaskQuotaExceededError,
    TaskRepositoryUnavailableError,
)


'''迁移函数类型'''
Migration = Callable[[sqlite3.Connection], None]


def _migration_001_create_tasks_table(connection: sqlite3.Connection) -> None:
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


def _migration_002_add_archived_at(connection: sqlite3.Connection) -> None:
    columns = {
        row["name"]
        for row in connection.execute("PRAGMA table_info(tasks)").fetchall()
    }
    if "archived_at" not in columns:
        connection.execute("ALTER TABLE tasks ADD COLUMN archived_at TEXT")


def _migration_003_create_task_indexes(connection: sqlite3.Connection) -> None:
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


def _migration_004_normalize_completed_status(connection: sqlite3.Connection) -> None:
    rows = connection.execute(
        "SELECT task_id, record_json FROM tasks WHERE status = ?",
        ("completed",),
    ).fetchall()
    for row in rows:
        try:
            record_data = json.loads(row["record_json"])
        except json.JSONDecodeError:
            record_data = None
        if isinstance(record_data, dict):
            record_data["status"] = "succeeded"
            record_json = json.dumps(record_data, ensure_ascii=False, separators=(",", ":"))
        else:
            record_json = row["record_json"]
        connection.execute(
            "UPDATE tasks SET status = ?, record_json = ? WHERE task_id = ?",
            ("succeeded", record_json, row["task_id"]),
        )


def _migration_005_normalize_input_filename(connection: sqlite3.Connection) -> None:
    rows = connection.execute("SELECT task_id, record_json FROM tasks").fetchall()
    for row in rows:
        try:
            record_data = json.loads(row["record_json"])
        except json.JSONDecodeError:
            continue
        if not isinstance(record_data, dict):
            continue

        input_data = record_data.get("input")
        if not isinstance(input_data, dict) or "source_file" not in input_data:
            continue
        source_file = input_data.pop("source_file")
        if not input_data.get("original_filename") and isinstance(source_file, str):
            input_data["original_filename"] = source_file
        connection.execute(
            "UPDATE tasks SET record_json = ? WHERE task_id = ?",
            (
                json.dumps(record_data, ensure_ascii=False, separators=(",", ":")),
                row["task_id"],
            ),
        )


def _migration_006_create_users_table(connection: sqlite3.Connection) -> None:
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS users (
            user_id TEXT PRIMARY KEY,
            username TEXT NOT NULL UNIQUE,
            hashed_password TEXT NOT NULL,
            is_active INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )
    connection.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS idx_users_username
        ON users (username)
        """
    )


def _migration_007_add_user_id_to_tasks(connection: sqlite3.Connection) -> None:
    columns = {
        row["name"]
        for row in connection.execute("PRAGMA table_info(tasks)").fetchall()
    }
    if "user_id" not in columns:
        connection.execute("ALTER TABLE tasks ADD COLUMN user_id TEXT")
    connection.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_tasks_user_id
        ON tasks (user_id)
        """
    )


def _migration_008_add_user_task_indexes(connection: sqlite3.Connection) -> None:
    connection.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_tasks_user_active_created
        ON tasks (user_id, created_at DESC)
        WHERE archived_at IS NULL
        """
    )
    connection.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_tasks_user_archived
        ON tasks (user_id, archived_at DESC)
        WHERE archived_at IS NOT NULL
        """
    )


def _migration_009_add_user_token_version(connection: sqlite3.Connection) -> None:
    columns = {
        row["name"]
        for row in connection.execute("PRAGMA table_info(users)").fetchall()
    }
    if "token_version" not in columns:
        connection.execute(
            "ALTER TABLE users ADD COLUMN token_version INTEGER NOT NULL DEFAULT 0"
        )


def _migration_010_add_user_role(connection: sqlite3.Connection) -> None:
    columns = {
        row["name"]
        for row in connection.execute("PRAGMA table_info(users)").fetchall()
    }
    if "role" not in columns:
        connection.execute(
            "ALTER TABLE users ADD COLUMN role TEXT NOT NULL DEFAULT 'user'"
        )


def _migration_011_add_user_password_change_flag(connection: sqlite3.Connection) -> None:
    columns = {
        row["name"]
        for row in connection.execute("PRAGMA table_info(users)").fetchall()
    }
    if "must_change_password" not in columns:
        connection.execute(
            "ALTER TABLE users ADD COLUMN must_change_password "
            "INTEGER NOT NULL DEFAULT 0"
        )


def _migration_012_add_normalized_username(connection: sqlite3.Connection) -> None:
    columns = {
        row["name"]
        for row in connection.execute("PRAGMA table_info(users)").fetchall()
    }
    if "normalized_username" not in columns:
        connection.execute("ALTER TABLE users ADD COLUMN normalized_username TEXT")
    connection.execute(
        "UPDATE users SET normalized_username = LOWER(username) "
        "WHERE normalized_username IS NULL"
    )
    duplicate = connection.execute(
        """
        SELECT normalized_username, GROUP_CONCAT(username, ', ') AS usernames
        FROM users
        GROUP BY normalized_username
        HAVING COUNT(*) > 1
        LIMIT 1
        """
    ).fetchone()
    if duplicate is not None:
        raise TaskRepositoryUnavailableError(
            "SQLite 用户数据库存在仅大小写不同的重复用户名："
            f"{duplicate['usernames']}；请先人工合并账号"
        )
    connection.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS idx_users_normalized_username
        ON users (normalized_username)
        """
    )


'''迁移清单'''
SCHEMA_MIGRATIONS: tuple[tuple[int, str, Migration], ...] = (
    (1, "create_tasks_table", _migration_001_create_tasks_table),
    (2, "add_archived_at", _migration_002_add_archived_at),
    (3, "create_task_indexes", _migration_003_create_task_indexes),
    (4, "normalize_completed_status", _migration_004_normalize_completed_status),
    (5, "normalize_input_filename", _migration_005_normalize_input_filename),
    (6, "create_users_table", _migration_006_create_users_table),
    (7, "add_user_id_to_tasks", _migration_007_add_user_id_to_tasks),
    (8, "add_user_task_indexes", _migration_008_add_user_task_indexes),
    (9, "add_user_token_version", _migration_009_add_user_token_version),
    (10, "add_user_role", _migration_010_add_user_role),
    (11, "add_user_password_change_flag", _migration_011_add_user_password_change_flag),
    (12, "add_normalized_username", _migration_012_add_normalized_username),
)
CURRENT_SCHEMA_VERSION = SCHEMA_MIGRATIONS[-1][0]


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
            self._apply_schema_migrations(connection)

    @staticmethod
    def _apply_schema_migrations(connection: sqlite3.Connection) -> None:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS schema_migrations (
                version INTEGER PRIMARY KEY,
                name TEXT NOT NULL,
                applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        applied_versions = {
            row["version"]
            for row in connection.execute("SELECT version FROM schema_migrations")
        }
        if applied_versions and max(applied_versions) > CURRENT_SCHEMA_VERSION:
            raise TaskRepositoryUnavailableError("SQLite 任务数据库版本高于当前程序")

        for version, name, migration in SCHEMA_MIGRATIONS:
            if version in applied_versions:
                continue
            migration(connection)
            connection.execute(
                "INSERT INTO schema_migrations (version, name) VALUES (?, ?)",
                (version, name),
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

    def save(
        self,
        task_dir: Path,
        record: TaskRecord,
        user_id: str | None = None,
        *,
        max_tasks_per_user: int | None = None,
    ) -> Path:
        if record.task_id != task_dir.name:
            raise ValueError("任务 ID 与任务目录不一致")
        if max_tasks_per_user is not None and user_id is None:
            raise ValueError("按用户保存任务时缺少用户标识")

        record_json = record.model_dump_json(exclude_none=True)
        with self._connect() as connection:
            if max_tasks_per_user is not None:
                '''保留写锁避免并发绕过配额检查'''
                connection.execute("BEGIN IMMEDIATE")
            existing = connection.execute(
                "SELECT user_id FROM tasks WHERE task_id = ?",
                (record.task_id,),
            ).fetchone()
            effective_user_id = user_id
            if existing is not None and existing["user_id"] is not None:
                effective_user_id = existing["user_id"]
            if existing is None and max_tasks_per_user is not None:
                total = connection.execute(
                    "SELECT COUNT(*) AS total FROM tasks WHERE user_id = ?",
                    (user_id,),
                ).fetchone()["total"]
                if int(total) >= max_tasks_per_user:
                    raise TaskQuotaExceededError(
                        "当前账号保存的任务数已达到上限，请先归档并等待管理员清理"
                    )
            connection.execute(
                """
                INSERT INTO tasks (
                    task_id, name, status, created_at, updated_at, archived_at, user_id, record_json
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
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
                    effective_user_id,
                    record_json,
                ),
            )
        return self.database_path.resolve()

    def count(self, user_id: str | None = None) -> int:
        with self._connect() as connection:
            if user_id is not None:
                row = connection.execute(
                    "SELECT COUNT(*) AS total FROM tasks WHERE user_id = ?",
                    (user_id,),
                ).fetchone()
            else:
                row = connection.execute("SELECT COUNT(*) AS total FROM tasks").fetchone()
        return int(row["total"])

    def list_tasks(
        self,
        *,
        limit: int,
        offset: int,
        status: TaskStatus | None = None,
        query: str | None = None,
        created_from: datetime | None = None,
        created_to: datetime | None = None,
        user_id: str | None = None,
    ) -> tuple[list[TaskRecord], int]:
        conditions = ["archived_at IS NULL"]
        parameters: list[object] = []
        if user_id is not None:
            conditions.append("user_id = ?")
            parameters.append(user_id)
        if status is not None:
            conditions.append("status = ?")
            parameters.append(status.value)
        if query is not None:
            escaped_query = (
                query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            )
            search_pattern = f"%{escaped_query}%"
            conditions.append(
                "("
                "name COLLATE NOCASE LIKE ? ESCAPE '\\' OR "
                "task_id COLLATE NOCASE LIKE ? ESCAPE '\\'"
                ")"
            )
            parameters.extend((search_pattern, search_pattern))
        if created_from is not None:
            conditions.append("julianday(created_at) >= julianday(?)")
            parameters.append(created_from.isoformat())
        if created_to is not None:
            conditions.append("julianday(created_at) <= julianday(?)")
            parameters.append(created_to.isoformat())

        where_clause = f"WHERE {' AND '.join(conditions)}"

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

    def list_archived_tasks(
        self,
        *,
        limit: int,
        offset: int,
        status: TaskStatus | None = None,
        query: str | None = None,
        user_id: str | None = None,
    ) -> tuple[list[TaskRecord], int]:
        conditions = ["archived_at IS NOT NULL"]
        parameters: list[object] = []
        if user_id is not None:
            conditions.append("user_id = ?")
            parameters.append(user_id)
        if status is not None:
            conditions.append("status = ?")
            parameters.append(status.value)
        if query is not None:
            escaped_query = (
                query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            )
            search_pattern = f"%{escaped_query}%"
            conditions.append(
                "("
                "name COLLATE NOCASE LIKE ? ESCAPE '\\' OR "
                "task_id COLLATE NOCASE LIKE ? ESCAPE '\\'"
                ")"
            )
            parameters.extend((search_pattern, search_pattern))

        where_clause = f"WHERE {' AND '.join(conditions)}"
        with self._connect() as connection:
            total_row = connection.execute(
                f"SELECT COUNT(*) AS total FROM tasks {where_clause}",
                parameters,
            ).fetchone()
            rows = connection.execute(
                f"""
                SELECT record_json FROM tasks
                {where_clause}
                ORDER BY archived_at DESC, task_id DESC
                LIMIT ? OFFSET ?
                """,
                (*parameters, limit, offset),
            ).fetchall()

        return self._records_from_rows(rows), int(total_row["total"])

    def list_active_tasks(self, *, limit: int, user_id: str | None = None) -> list[TaskRecord]:
        conditions = ["archived_at IS NULL", f"status IN ({', '.join('?' for _ in ACTIVE_ASYNC_TASK_STATUSES)})"]
        params: list[object] = [*(s.value for s in ACTIVE_ASYNC_TASK_STATUSES)]
        if user_id is not None:
            conditions.append("user_id = ?")
            params.append(user_id)
        where = f"WHERE {' AND '.join(conditions)}"
        with self._connect() as connection:
            rows = connection.execute(
                f"""
                SELECT record_json FROM tasks
                {where}
                ORDER BY updated_at ASC, task_id ASC
                LIMIT ?
                """,
                (*params, limit),
            ).fetchall()
        return self._records_from_rows(rows)

    def list_archive_candidates(
        self,
        *,
        succeeded_before: datetime,
        failed_before: datetime,
        limit: int,
        user_id: str | None = None,
    ) -> list[TaskRecord]:
        extra_cond = "AND user_id = ?" if user_id is not None else ""
        params: list[object] = [
            TaskStatus.SUCCEEDED.value,
            succeeded_before.isoformat(),
            TaskStatus.FAILED.value,
            TaskStatus.CANCELED.value,
            failed_before.isoformat(),
        ]
        if user_id is not None:
            params.append(user_id)
        with self._connect() as connection:
            rows = connection.execute(
                f"""
                SELECT record_json FROM tasks
                WHERE archived_at IS NULL AND (
                    (status = ? AND updated_at < ?) OR
                    (status IN (?, ?) AND updated_at < ?)
                ) {extra_cond}
                ORDER BY updated_at ASC, task_id ASC
                LIMIT ?
                """,
                (*params, limit),
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

    def get_task_user_id(self, task_id: str) -> str | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT user_id FROM tasks WHERE task_id = ?",
                (task_id,),
            ).fetchone()
        if row is None:
            raise TaskNotFoundError("任务元数据不存在")
        return row["user_id"]

    def get_task_user_ids(self, task_ids: list[str]) -> dict[str, str | None]:
        if not task_ids:
            return {}
        placeholders = ", ".join("?" for _ in task_ids)
        with self._connect() as connection:
            rows = connection.execute(
                f"SELECT task_id, user_id FROM tasks WHERE task_id IN ({placeholders})",
                task_ids,
            ).fetchall()
        return {row["task_id"]: row["user_id"] for row in rows}

    def count_unowned_tasks(self) -> int:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT COUNT(*) AS total FROM tasks WHERE user_id IS NULL"
            ).fetchone()
        return int(row["total"])

    def assign_unowned_tasks(self, user_id: str) -> int:
        '''由运维命令把历史无归属任务一次性分配给明确用户'''
        with self._connect() as connection:
            cursor = connection.execute(
                "UPDATE tasks SET user_id = ? WHERE user_id IS NULL",
                (user_id,),
            )
        return cursor.rowcount

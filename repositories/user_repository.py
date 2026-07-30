'''用户仓储实现，复用 SQLite 任务数据库'''

from __future__ import annotations

import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

from core.user_records import UserRecord
from repositories.sqlite_task_repository import SqliteTaskRepository
from repositories.task_repository_contracts import TaskRepositoryUnavailableError


class UsernameAlreadyExistsError(ValueError):
    pass


class SqliteUserRepository:

    def __init__(self, repository: SqliteTaskRepository) -> None:
        self._repo = repository

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        try:
            connection = sqlite3.connect(self._repo.database_path, timeout=5)
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA busy_timeout = 5000")
        except sqlite3.Error as exc:
            raise TaskRepositoryUnavailableError("SQLite 用户数据库不可用") from exc

        try:
            yield connection
            connection.commit()
        except sqlite3.IntegrityError:
            connection.rollback()
            raise
        except sqlite3.Error as exc:
            connection.rollback()
            raise TaskRepositoryUnavailableError("SQLite 用户数据库不可用") from exc
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def create_user(
        self,
        username: str,
        hashed_password: str,
    ) -> UserRecord:
        now = datetime.now(timezone.utc)
        user_id = uuid.uuid4().hex[:16]
        record = UserRecord(
            user_id=user_id,
            username=username,
            hashed_password=hashed_password,
            is_active=True,
            created_at=now,
            updated_at=now,
        )
        try:
            with self._connect() as connection:
                connection.execute(
                    """
                    INSERT INTO users (
                        user_id, username, hashed_password, is_active, created_at, updated_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        record.user_id,
                        record.username,
                        record.hashed_password,
                        1 if record.is_active else 0,
                        record.created_at.isoformat(),
                        record.updated_at.isoformat(),
                    ),
                )
        except sqlite3.IntegrityError as exc:
            if "users.username" in str(exc):
                raise UsernameAlreadyExistsError(
                    f"用户名 '{username}' 已被注册"
                ) from exc
            raise
        return record

    def get_by_username(self, username: str) -> UserRecord | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM users WHERE username = ?",
                (username,),
            ).fetchone()
        if row is None:
            return None
        return self._row_to_record(row)

    def get_by_user_id(self, user_id: str) -> UserRecord | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM users WHERE user_id = ?",
                (user_id,),
            ).fetchone()
        if row is None:
            return None
        return self._row_to_record(row)

    @staticmethod
    def _row_to_record(row: sqlite3.Row) -> UserRecord:
        return UserRecord(
            user_id=row["user_id"],
            username=row["username"],
            hashed_password=row["hashed_password"],
            is_active=bool(row["is_active"]),
            created_at=datetime.fromisoformat(row["created_at"]),
            updated_at=datetime.fromisoformat(row["updated_at"]),
        )

'''认证、用户隔离与安全配置的回归测试'''

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

os.environ.setdefault(
    "BTIR_JWT_SECRET_KEY",
    "test-only-jwt-secret-key-at-least-32-bytes",
)

from fastapi import HTTPException, status
from fastapi.testclient import TestClient

from api.app import app
from api.routes.tasks import enforce_active_task_limit, enforce_task_storage_limit
from core.settings import SETTINGS
from core.task_definitions import TaskStatus
from core.task_records import StoredTaskInput, TaskRecord
from repositories.sqlite_task_repository import SqliteTaskRepository
from repositories.user_repository import SqliteUserRepository
from services.auth_service import hash_password, validate_auth_configuration
from services.auth_rate_limit import AuthRateLimitExceededError


class AuthenticationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = TemporaryDirectory()
        self.root = Path(self.temporary_directory.name)
        self.repository = SqliteTaskRepository(self.root / "tasks.db")
        self.registration_settings = replace(SETTINGS, registration_enabled=True)
        self.patches = [
            patch("api.auth.task_repository", self.repository),
            patch("api.routes.tasks.task_repository", self.repository),
            patch("api.routes.auth.SETTINGS", self.registration_settings),
            patch("api.routes.auth.consume_auth_rate_limit"),
            patch("api.routes.auth.clear_auth_rate_limit"),
        ]
        for patcher in self.patches:
            patcher.start()
            self.addCleanup(patcher.stop)

    def tearDown(self) -> None:
        app.dependency_overrides.clear()
        self.temporary_directory.cleanup()

    def _register(self, client: TestClient, username: str) -> dict:
        response = client.post(
            "/auth/register",
            json={"username": username, "password": "safe-password"},
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        return response.json()

    @staticmethod
    def _headers(auth: dict) -> dict[str, str]:
        return {"Authorization": f"Bearer {auth['access_token']}"}

    def _record(self, task_id: str) -> TaskRecord:
        now = datetime.now(timezone.utc)
        return TaskRecord(
            task_id=task_id,
            name=task_id,
            status=TaskStatus.SUCCEEDED,
            created_at=now,
            updated_at=now,
            input=StoredTaskInput(
                size_bytes=1,
                sha256="a" * 64,
            ),
        )

    def test_register_login_and_me(self) -> None:
        with TestClient(app) as client:
            registered = self._register(client, "alice")
            login = client.post(
                "/auth/login",
                json={"username": "alice", "password": "safe-password"},
            )
            profile = client.get("/auth/me", headers=self._headers(registered))

        self.assertEqual(login.status_code, status.HTTP_200_OK)
        self.assertEqual(profile.status_code, status.HTTP_200_OK)
        self.assertEqual(profile.json()["username"], "alice")

    def test_registration_can_be_disabled(self) -> None:
        with (
            patch("api.routes.auth.SETTINGS", replace(SETTINGS, registration_enabled=False)),
            TestClient(app) as client,
        ):
            response = client.post(
                "/auth/register",
                json={"username": "alice", "password": "safe-password"},
            )

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_protected_endpoint_without_token_returns_unauthorized(self) -> None:
        with TestClient(app) as client:
            response = client.get("/auth/me")

        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_duplicate_username_returns_conflict(self) -> None:
        with TestClient(app) as client:
            self._register(client, "alice")
            duplicate = client.post(
                "/auth/register",
                json={"username": "alice", "password": "safe-password"},
            )

        self.assertEqual(duplicate.status_code, status.HTTP_409_CONFLICT)

    def test_other_user_cannot_access_any_task_action(self) -> None:
        task_dir = self.root / "task-owned-by-alice"
        task_dir.mkdir()

        with TestClient(app) as client:
            alice = self._register(client, "alice")
            bob = self._register(client, "bob")
            self.repository.save(
                task_dir,
                self._record(task_dir.name),
                user_id=alice["user_id"],
            )
            headers = self._headers(bob)
            requests = (
                ("GET", f"/tasks/{task_dir.name}", None),
                ("DELETE", f"/tasks/{task_dir.name}", None),
                ("POST", f"/tasks/{task_dir.name}/restore", None),
                ("GET", f"/tasks/{task_dir.name}/runs", None),
                ("GET", f"/tasks/{task_dir.name}/files/frontend_result.json", None),
                ("POST", f"/tasks/{task_dir.name}/run-async", {}),
                ("POST", f"/tasks/{task_dir.name}/cancel", None),
                ("POST", f"/tasks/{task_dir.name}/retry", {}),
            )
            for method, url, json_body in requests:
                with self.subTest(method=method, url=url):
                    response = client.request(
                        method,
                        url,
                        headers=headers,
                        json=json_body,
                    )
                    self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

            task_list = client.get("/tasks", headers=headers)

        self.assertEqual(task_list.status_code, status.HTTP_200_OK)
        self.assertEqual(task_list.json()["total"], 0)

    def test_unowned_legacy_task_is_not_accessible(self) -> None:
        task_dir = self.root / "legacy-task"
        task_dir.mkdir()
        self.repository.save(task_dir, self._record(task_dir.name))

        with TestClient(app) as client:
            user = self._register(client, "alice")
            response = client.get(
                f"/tasks/{task_dir.name}",
                headers=self._headers(user),
            )

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_per_user_task_limits_are_enforced(self) -> None:
        user_repository = SqliteUserRepository(self.repository)
        user = user_repository.create_user(
            username="alice",
            hashed_password="not-used",
        )
        active_dir = self.root / "active-task"
        active_dir.mkdir()
        active_record = self._record(active_dir.name)
        active_record.status = TaskStatus.QUEUED
        self.repository.save(active_dir, active_record, user_id=user.user_id)

        limited_settings = replace(
            SETTINGS,
            max_tasks_per_user=1,
            max_active_tasks_per_user=1,
        )
        with patch("api.routes.tasks.SETTINGS", limited_settings):
            with self.assertRaises(HTTPException) as storage_error:
                enforce_task_storage_limit(user)
            with self.assertRaises(HTTPException) as active_error:
                enforce_active_task_limit("another-task", user)
            enforce_active_task_limit(active_dir.name, user)

        self.assertEqual(
            storage_error.exception.status_code,
            status.HTTP_429_TOO_MANY_REQUESTS,
        )
        self.assertEqual(
            active_error.exception.status_code,
            status.HTTP_429_TOO_MANY_REQUESTS,
        )

    def test_unsafe_jwt_configuration_is_rejected(self) -> None:
        with patch(
            "services.auth_service.SETTINGS",
            replace(SETTINGS, jwt_secret_key="short"),
        ):
            with self.assertRaises(RuntimeError):
                validate_auth_configuration()

    def test_rate_limited_login_returns_retry_after(self) -> None:
        with (
            patch(
                "api.routes.auth.consume_auth_rate_limit",
                side_effect=AuthRateLimitExceededError(37),
            ),
            TestClient(app) as client,
        ):
            response = client.post(
                "/auth/login",
                json={"username": "alice", "password": "safe-password"},
            )

        self.assertEqual(response.status_code, status.HTTP_429_TOO_MANY_REQUESTS)
        self.assertEqual(response.headers["Retry-After"], "37")

    def test_password_reset_revokes_existing_token(self) -> None:
        with TestClient(app) as client:
            registered = self._register(client, "alice")
            user_repository = SqliteUserRepository(self.repository)
            updated = user_repository.update_password(
                "alice",
                hash_password("new-safe-password"),
            )
            self.assertIsNotNone(updated)

            old_profile = client.get(
                "/auth/me",
                headers=self._headers(registered),
            )
            new_login = client.post(
                "/auth/login",
                json={"username": "alice", "password": "new-safe-password"},
            )

        self.assertEqual(old_profile.status_code, status.HTTP_401_UNAUTHORIZED)
        self.assertEqual(new_login.status_code, status.HTTP_200_OK)

    def test_disable_then_enable_keeps_old_token_revoked(self) -> None:
        with TestClient(app) as client:
            registered = self._register(client, "alice")
            user_repository = SqliteUserRepository(self.repository)
            user_repository.set_active("alice", False)
            disabled_profile = client.get(
                "/auth/me",
                headers=self._headers(registered),
            )
            user_repository.set_active("alice", True)
            reenabled_profile = client.get(
                "/auth/me",
                headers=self._headers(registered),
            )

        self.assertEqual(disabled_profile.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(reenabled_profile.status_code, status.HTTP_401_UNAUTHORIZED)


if __name__ == "__main__":
    unittest.main()

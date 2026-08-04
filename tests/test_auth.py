'''认证、用户隔离与安全配置的回归测试'''

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
from contextlib import nullcontext
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
from core.user_records import UserRole
from repositories.sqlite_task_repository import SqliteTaskRepository
from repositories.user_repository import SqliteUserRepository
from services.auth_service import hash_password, validate_auth_configuration
from services.auth_rate_limit import AuthRateLimitExceededError


class AuthenticationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = TemporaryDirectory()
        self.root = Path(self.temporary_directory.name)
        self.repository = SqliteTaskRepository(self.root / "tasks.db")
        self.registration_settings = replace(
            SETTINGS,
            registration_enabled=True,
            task_archive_dir=self.root / "archive",
        )
        self.admin_settings = replace(
            SETTINGS,
            output_dir=self.root / "output",
            task_archive_dir=self.root / "archive",
        )
        self.patches = [
            patch("api.auth.task_repository", self.repository),
            patch("api.routes.tasks.task_repository", self.repository),
            patch("api.routes.admin.task_repository", self.repository),
            patch("api.routes.admin.SETTINGS", self.admin_settings),
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

    @staticmethod
    def _confirmed_headers(auth: dict, action: str) -> dict[str, str]:
        return {
            **AuthenticationTests._headers(auth),
            "X-BTIR-Confirm-Action": action,
        }

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
        self.assertEqual(registered["role"], "user")
        self.assertEqual(login.json()["role"], "user")
        self.assertEqual(profile.json()["role"], "user")

    def test_admin_can_query_users_and_cross_user_tasks_read_only(self) -> None:
        with TestClient(app) as client:
            alice = self._register(client, "alice")
            bob = self._register(client, "bob")
            regular_admin_response = client.get(
                "/admin/users",
                headers=self._headers(alice),
            )

            user_repository = SqliteUserRepository(self.repository)
            promoted = user_repository.set_role("alice", UserRole.ADMIN)
            self.assertIsNotNone(promoted)
            old_token_response = client.get(
                "/admin/users",
                headers=self._headers(alice),
            )
            login = client.post(
                "/auth/login",
                json={"username": "alice", "password": "safe-password"},
            )
            admin_headers = self._headers(login.json())

            task_dir = self.root / "task-owned-by-bob"
            task_dir.mkdir()
            self.repository.save(
                task_dir,
                self._record(task_dir.name),
                user_id=bob["user_id"],
            )
            users_response = client.get(
                "/admin/users?role=user&q=bo",
                headers=admin_headers,
            )
            tasks_response = client.get(
                "/admin/tasks?owner_username=bob",
                headers=admin_headers,
            )

        self.assertEqual(regular_admin_response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(old_token_response.status_code, status.HTTP_401_UNAUTHORIZED)
        self.assertEqual(login.status_code, status.HTTP_200_OK)
        self.assertEqual(login.json()["role"], "admin")
        self.assertEqual(users_response.status_code, status.HTTP_200_OK)
        self.assertEqual(users_response.json()["total"], 1)
        user_item = users_response.json()["items"][0]
        self.assertEqual(user_item["username"], "bob")
        self.assertNotIn("hashed_password", user_item)
        self.assertNotIn("token_version", user_item)
        self.assertEqual(tasks_response.status_code, status.HTTP_200_OK)
        self.assertEqual(tasks_response.json()["total"], 1)
        task_item = tasks_response.json()["items"][0]
        self.assertEqual(task_item["task_id"], task_dir.name)
        self.assertEqual(task_item["owner_user_id"], bob["user_id"])
        self.assertEqual(task_item["owner_username"], "bob")

    def test_users_can_only_list_and_read_their_own_tasks(self) -> None:
        output_dir = self.admin_settings.output_dir
        output_dir.mkdir()
        with TestClient(app) as client:
            alice = self._register(client, "alice")
            bob = self._register(client, "bob")
            alice_task_dir = output_dir / "task-owned-by-alice"
            bob_task_dir = output_dir / "task-owned-by-bob"
            alice_task_dir.mkdir()
            bob_task_dir.mkdir()
            self.repository.save(
                alice_task_dir,
                self._record(alice_task_dir.name),
                user_id=alice["user_id"],
            )
            self.repository.save(
                bob_task_dir,
                self._record(bob_task_dir.name),
                user_id=bob["user_id"],
            )

            alice_tasks = client.get("/tasks", headers=self._headers(alice))
            bob_tasks = client.get("/tasks", headers=self._headers(bob))
            alice_reads_bob = client.get(
                f"/tasks/{bob_task_dir.name}",
                headers=self._headers(alice),
            )

        self.assertEqual(alice_tasks.status_code, status.HTTP_200_OK)
        self.assertEqual(bob_tasks.status_code, status.HTTP_200_OK)
        self.assertEqual(
            [item["task_id"] for item in alice_tasks.json()["items"]],
            [alice_task_dir.name],
        )
        self.assertEqual(
            [item["task_id"] for item in bob_tasks.json()["items"]],
            [bob_task_dir.name],
        )
        self.assertEqual(alice_reads_bob.status_code, status.HTTP_404_NOT_FOUND)

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

    def test_admin_can_reset_password_and_archive_a_specific_users_task(self) -> None:
        output_dir = self.admin_settings.output_dir
        output_dir.mkdir()
        with TestClient(app) as client:
            admin = self._register(client, "admin")
            bob = self._register(client, "bob")
            user_repository = SqliteUserRepository(self.repository)
            user_repository.set_role("admin", UserRole.ADMIN)
            login = client.post(
                "/auth/login",
                json={"username": "admin", "password": "safe-password"},
            )
            admin_headers = self._headers(login.json())

            forbidden_reset = client.post(
                f"/admin/users/{admin['user_id']}/reset-password",
                headers=self._headers(bob),
                json={"new_password": "temporary-password"},
            )
            reset = client.post(
                f"/admin/users/{bob['user_id']}/reset-password",
                headers=admin_headers,
                json={"new_password": "temporary-password"},
            )
            confirmed_reset = client.post(
                f"/admin/users/{bob['user_id']}/reset-password",
                headers=self._confirmed_headers(
                    login.json(),
                    f"reset-password:{bob['user_id']}",
                ),
                json={"new_password": "temporary-password"},
            )
            old_bob_token = client.get("/auth/me", headers=self._headers(bob))
            new_bob_login = client.post(
                "/auth/login",
                json={"username": "bob", "password": "temporary-password"},
            )
            temporary_headers = self._headers(new_bob_login.json())
            password_change_required = client.get(
                "/tasks",
                headers=temporary_headers,
            )
            temporary_profile = client.get(
                "/auth/me",
                headers=temporary_headers,
            )
            changed_password = client.post(
                "/auth/change-password",
                headers=temporary_headers,
                json={
                    "current_password": "temporary-password",
                    "new_password": "bob-private-password",
                },
            )
            changed_headers = self._headers(changed_password.json())
            expired_temporary_token = client.get(
                "/auth/me",
                headers=temporary_headers,
            )
            usable_task_list = client.get("/tasks", headers=changed_headers)

            task_dir = output_dir / "task-owned-by-bob"
            task_dir.mkdir()
            self.repository.save(
                task_dir,
                self._record(task_dir.name),
                user_id=bob["user_id"],
            )
            wrong_owner = client.delete(
                f"/admin/users/{admin['user_id']}/tasks/{task_dir.name}",
                headers=admin_headers,
            )
            with patch(
                "services.archive_service.task_write_lock",
                side_effect=lambda _: nullcontext(),
            ):
                confirmation_required_for_archive = client.delete(
                    f"/admin/users/{bob['user_id']}/tasks/{task_dir.name}",
                    headers=admin_headers,
                )
                archived = client.delete(
                    f"/admin/users/{bob['user_id']}/tasks/{task_dir.name}",
                    headers=self._confirmed_headers(
                        login.json(),
                        f"archive-task:{task_dir.name}",
                    ),
                )
                confirmation_required_for_restore = client.post(
                    f"/admin/users/{bob['user_id']}/tasks/{task_dir.name}/restore",
                    headers=admin_headers,
                )
                restored = client.post(
                    f"/admin/users/{bob['user_id']}/tasks/{task_dir.name}/restore",
                    headers=self._confirmed_headers(
                        login.json(),
                        f"restore-task:{task_dir.name}",
                    ),
                )
            audit_response = client.get(
                f"/admin/audit?target_user_id={bob['user_id']}",
                headers=admin_headers,
            )

        self.assertEqual(forbidden_reset.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(reset.status_code, status.HTTP_428_PRECONDITION_REQUIRED)
        self.assertEqual(
            reset.json()["detail"]["confirmation_action"],
            f"reset-password:{bob['user_id']}",
        )
        self.assertEqual(confirmed_reset.status_code, status.HTTP_200_OK)
        self.assertTrue(confirmed_reset.json()["token_revoked"])
        self.assertEqual(old_bob_token.status_code, status.HTTP_401_UNAUTHORIZED)
        self.assertEqual(new_bob_login.status_code, status.HTTP_200_OK)
        self.assertTrue(new_bob_login.json()["must_change_password"])
        self.assertEqual(password_change_required.status_code, status.HTTP_403_FORBIDDEN)
        self.assertTrue(temporary_profile.json()["must_change_password"])
        self.assertEqual(changed_password.status_code, status.HTTP_200_OK)
        self.assertFalse(changed_password.json()["must_change_password"])
        self.assertEqual(expired_temporary_token.status_code, status.HTTP_401_UNAUTHORIZED)
        self.assertEqual(usable_task_list.status_code, status.HTTP_200_OK)
        self.assertEqual(wrong_owner.status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(
            confirmation_required_for_archive.status_code,
            status.HTTP_428_PRECONDITION_REQUIRED,
        )
        self.assertEqual(archived.status_code, status.HTTP_200_OK)
        self.assertEqual(
            confirmation_required_for_restore.status_code,
            status.HTTP_428_PRECONDITION_REQUIRED,
        )
        self.assertEqual(restored.status_code, status.HTTP_200_OK)
        self.assertTrue(task_dir.is_dir())
        self.assertEqual(audit_response.status_code, status.HTTP_200_OK)
        self.assertEqual(audit_response.json()["total"], 6)
        self.assertEqual(
            [item["operation"] for item in audit_response.json()["items"]],
            [
                "restore_api",
                "archive_api",
                "password_changed",
                "auth_login_succeeded",
                "admin_password_reset",
                "user_registered",
            ],
        )
        audit_text = (
            self.admin_settings.task_archive_dir / "audit.jsonl"
        ).read_text(encoding="utf-8")
        self.assertIn('"operation": "admin_password_reset"', audit_text)
        self.assertIn('"operation": "archive_api"', audit_text)
        self.assertIn('"operation": "restore_api"', audit_text)
        self.assertIn(f'"actor_user_id": "{admin["user_id"]}"', audit_text)
        self.assertIn(f'"target_user_id": "{bob["user_id"]}"', audit_text)
        self.assertIn('"source_ip": "testclient"', audit_text)
        self.assertIn('"outcome": "success"', audit_text)
        self.assertNotIn("temporary-password", audit_text)

    def test_protected_endpoint_without_token_returns_unauthorized(self) -> None:
        with TestClient(app) as client:
            response = client.get("/auth/me")

        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_duplicate_username_returns_conflict(self) -> None:
        with TestClient(app) as client:
            registered = self._register(client, "Alice")
            duplicate = client.post(
                "/auth/register",
                json={"username": "alice", "password": "safe-password"},
            )
            login = client.post(
                "/auth/login",
                json={"username": "ALICE", "password": "safe-password"},
            )

        self.assertEqual(duplicate.status_code, status.HTTP_409_CONFLICT)
        self.assertEqual(login.status_code, status.HTTP_200_OK)
        self.assertEqual(login.json()["user_id"], registered["user_id"])
        self.assertEqual(login.json()["username"], "Alice")

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

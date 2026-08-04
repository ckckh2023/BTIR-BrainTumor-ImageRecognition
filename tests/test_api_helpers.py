'''任务路由内部辅助函数的回归测试'''

from __future__ import annotations

import asyncio
from contextlib import nullcontext
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
import zipfile
from io import BytesIO

from fastapi import HTTPException, status
from fastapi.testclient import TestClient
from redis.exceptions import RedisError

os.environ.setdefault("BTIR_JWT_SECRET_KEY", "test-only-jwt-secret-key-at-least-32-bytes")

from api.app import app
from api.auth import get_current_user
from api.routes.tasks import (
    bad_request_http_error,
    sanitize_public_payload,
    task_input_data,
    task_summary_data,
)
from api.routes.runtime import get_liveness, get_queue_status, get_readiness
from core.task_definitions import JobStatus, ModelName, TaskStatus
from core.task_records import (
    StoredTaskInput,
    StoredTaskModality,
    TaskErrorRecord,
    TaskJobRecord,
    TaskRecord,
    TaskRunRecord,
)
from core.settings import SETTINGS
from core.user_records import UserRecord
from services.task_lock import TaskLockBusyError, TaskLockUnavailableError
from services.task_queue import TaskQueueUnavailableError
from services.task_queue import get_inference_queue_status
from unittest.mock import Mock, patch


TEST_USER = UserRecord(
    user_id="test-user",
    username="test_user",
    hashed_password="not-used",
    created_at=datetime.now(timezone.utc),
    updated_at=datetime.now(timezone.utc),
)


class TaskRouteHelperTests(unittest.TestCase):
    '''验证任务响应组装和预期异常的 HTTP 转换规则'''

    def test_service_exceptions_are_registered_globally(self) -> None:
        cases = [
            (TaskLockBusyError("busy"), status.HTTP_409_CONFLICT),
            (TaskLockUnavailableError("lock unavailable"), status.HTTP_503_SERVICE_UNAVAILABLE),
            (TaskQueueUnavailableError("queue unavailable"), status.HTTP_503_SERVICE_UNAVAILABLE),
        ]
        for exc, expected_status in cases:
            with self.subTest(exc=type(exc).__name__):
                handler = app.exception_handlers[type(exc)]
                response = asyncio.run(handler(None, exc))
                self.assertEqual(response.status_code, expected_status)
                self.assertEqual(json.loads(response.body), {"detail": str(exc)})

    def test_value_error_remains_a_route_level_bad_request(self) -> None:
        response = bad_request_http_error(ValueError("invalid request"))
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.detail, "invalid request")

    def test_task_summary_exposes_safe_error_without_internal_detail(self) -> None:
        now = datetime.fromisoformat("2026-01-01T00:00:00+00:00")
        record = TaskRecord(
            task_id="task-error-001",
            name="错误任务",
            status=TaskStatus.FAILED,
            created_at=now,
            updated_at=now,
            input=StoredTaskInput(
                size_bytes=1,
                sha256="a" * 64,
            ),
            error=TaskErrorRecord(
                code="inference_failed",
                message="模型推理失败，请稍后重试或联系管理员",
                detail="RuntimeError: internal model path",
                updated_at=now,
            ),
        )

        summary = task_summary_data(record).model_dump(mode="json")

        self.assertEqual(summary["error"]["code"], "inference_failed")
        self.assertNotIn("detail", summary["error"])

    def test_public_json_sanitizer_removes_paths_and_diagnostics(self) -> None:
        sanitized = sanitize_public_payload(
            {
                "result": {"class": "yes", "path": "C:/private/result.json"},
                "error": {
                    "message": "任务失败",
                    "detail": "模型位于 C:/private/model",
                },
                "traceback": "File C:/private/service.py, line 1",
            }
        )

        self.assertEqual(
            sanitized,
            {"result": {"class": "yes"}, "error": {"message": "任务失败"}},
        )

    def test_3d_task_input_exposes_named_files_without_fake_filename(self) -> None:
        now = datetime.fromisoformat("2026-01-01T00:00:00+00:00")
        modalities = {
            name: StoredTaskModality(
                path=f"input/{name}.nii.gz",
                size_bytes=10,
                sha256=name * 16,
            )
            for name in ("flair", "t1ce", "t1", "t2")
        }
        record = TaskRecord(
            task_id="task-3d-input-001",
            name="3D 输入",
            status=TaskStatus.CREATED,
            created_at=now,
            updated_at=now,
            analysis_mode="3d",
            input=StoredTaskInput(
                size_bytes=40,
                sha256="a" * 64,
                modalities=modalities,
            ),
        )

        public_input = task_input_data(record).model_dump(mode="json")

        self.assertNotIn("filename", public_input)
        self.assertEqual(
            set(public_input["files"]),
            {"flair", "t1ce", "t1", "t2"},
        )

    def test_liveness_never_checks_external_dependencies(self) -> None:
        self.assertEqual(get_liveness(), {"status": "ok"})

    def test_readiness_reports_all_critical_dependencies(self) -> None:
        redis_client = Mock()
        redis_client.ping.return_value = True
        with (
            patch("api.routes.runtime.task_repository.health_check"),
            patch("api.routes.runtime.get_redis_client", return_value=redis_client),
            patch("api.routes.runtime.has_active_inference_worker", return_value=True),
        ):
            readiness = get_readiness()

        self.assertEqual(readiness["status"], "ready")
        self.assertEqual(
            readiness["components"],
            {
                "task_database": "ok",
                "redis": "ok",
                "inference_worker": "ok",
                "models": "ok",
            },
        )

    def test_readiness_returns_503_when_no_inference_worker_is_active(self) -> None:
        redis_client = Mock()
        redis_client.ping.return_value = True
        with (
            patch("api.routes.runtime.task_repository.health_check"),
            patch("api.routes.runtime.get_redis_client", return_value=redis_client),
            patch("api.routes.runtime.has_active_inference_worker", return_value=False),
            self.assertRaises(HTTPException) as caught,
        ):
            get_readiness()

        self.assertEqual(caught.exception.status_code, status.HTTP_503_SERVICE_UNAVAILABLE)
        self.assertEqual(
            caught.exception.detail["components"]["inference_worker"],
            "unavailable",
        )

    def test_readiness_returns_503_when_redis_is_unavailable(self) -> None:
        with (
            patch("api.routes.runtime.task_repository.health_check"),
            patch(
                "api.routes.runtime.get_redis_client",
                side_effect=RedisError("redis unavailable"),
            ),
            self.assertRaises(HTTPException) as caught,
        ):
            get_readiness()

        self.assertEqual(caught.exception.status_code, status.HTTP_503_SERVICE_UNAVAILABLE)
        self.assertEqual(caught.exception.detail["components"]["redis"], "unavailable")

    def test_queue_status_summarizes_the_inference_queue(self) -> None:
        queue_3d = Mock(name="queue-3d")
        queue_3d.name = "inference-3d"
        queue_3d.count = 4
        queue_3d.started_job_registry.count = 1
        queue_3d.failed_job_registry.count = 0
        queue_3d.get_job_ids.return_value = []
        oldest_job = Mock(enqueued_at=datetime.now().astimezone() - timedelta(seconds=4))
        worker_3d = Mock()
        worker_3d.queue_names.return_value = ["inference-3d"]

        with (
            patch(
                "services.task_queue.get_task_queue",
                return_value=queue_3d,
            ),
            patch(
                "services.task_queue.get_active_inference_workers",
                return_value=[worker_3d],
            ),
            patch("services.task_queue.Job.fetch", return_value=oldest_job),
        ):
            queue_status = get_inference_queue_status()

        self.assertEqual(queue_status["active_workers"], 1)
        self.assertEqual(queue_status["queued_jobs"], 4)
        self.assertEqual(queue_status["running_jobs"], 1)
        self.assertEqual(queue_status["failed_jobs"], 0)
        self.assertIsNone(queue_status["oldest_wait_seconds"])
        self.assertEqual(queue_status["queues"]["3d"]["queued_jobs"], 4)

    def test_queue_status_returns_503_when_redis_is_unavailable(self) -> None:
        with (
            patch(
                "api.routes.runtime.get_inference_queue_status",
                side_effect=RedisError("redis unavailable"),
            ),
            self.assertRaises(HTTPException) as caught,
        ):
            get_queue_status()

        self.assertEqual(caught.exception.status_code, status.HTTP_503_SERVICE_UNAVAILABLE)


class TaskHttpEndpointTests(unittest.TestCase):
    '''通过 FastAPI TestClient 验证浏览器实际会经历的任务 HTTP 流程'''

    def setUp(self) -> None:
        app.dependency_overrides[get_current_user] = lambda: TEST_USER
        self.owner_patcher = patch(
            "api.routes.tasks.task_repository.get_task_user_id",
            return_value=TEST_USER.user_id,
        )
        self.owner_patcher.start()

    def tearDown(self) -> None:
        self.owner_patcher.stop()
        app.dependency_overrides.pop(get_current_user, None)

    def test_legacy_and_single_model_endpoints_are_not_registered(self) -> None:
        paths = app.openapi()["paths"]

        self.assertNotIn("/tasks/from-path", paths)
        self.assertNotIn("/tasks/{task_id}/run", paths)
        self.assertNotIn("/tasks/{task_id}/classify", paths)
        self.assertNotIn("/tasks/{task_id}/segment", paths)
        self.assertEqual(set(paths["/tasks"]), {"get"})
        self.assertIn("/tasks/3d", paths)
        self.assertEqual(set(paths["/tasks/3d"]), {"post"})
        self.assertIn("/tasks/3d/archive", paths)
        self.assertEqual(set(paths["/tasks/3d/archive"]), {"post"})
        self.assertIn("/tasks/{task_id}/run-async", paths)
        self.assertNotIn(
            "requestBody",
            paths["/tasks/{task_id}/run-async"]["post"],
        )
        self.assertIn("/tasks/{task_id}/runs", paths)
        self.assertIn("/tasks/archived", paths)
        self.assertIn("delete", paths["/tasks/{task_id}"])
        self.assertIn("/tasks/{task_id}/restore", paths)

    def test_create_3d_task_accepts_four_named_modalities(self) -> None:
        with TemporaryDirectory() as directory:
            task_dir = Path(directory) / "task-http-3d-001"
            task_dir.mkdir()
            stored = {
                modality: task_dir / "input" / f"{modality}.nii.gz"
                for modality in ("flair", "t1ce", "t1", "t2")
            }
            with (
                patch("api.routes.tasks.task_repository.count", return_value=0),
                patch("api.routes.tasks.create_task_dir", return_value=task_dir),
                patch(
                    "api.routes.tasks.initialize_uploaded_volume_task",
                    return_value=stored,
                ) as initialize_volume,
                TestClient(app) as client,
            ):
                response = client.post(
                    "/tasks/3d",
                    files={
                        modality: (
                            f"patient_{modality}.nii.gz",
                            b"nifti-data",
                            "application/gzip",
                        )
                        for modality in stored
                    },
                    data={"name": "3D patient"},
                )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        payload = response.json()
        self.assertEqual(payload["analysis_mode"], "3d")
        self.assertEqual(payload["task_id"], task_dir.name)
        self.assertEqual(
            set(payload["input_files"]),
            {"flair", "t1ce", "t1", "t2"},
        )
        self.assertEqual(
            set(initialize_volume.call_args.kwargs["uploads"]),
            {"flair", "t1ce", "t1", "t2"},
        )

    def test_create_3d_task_accepts_a_case_zip(self) -> None:
        archive_bytes = BytesIO()
        with zipfile.ZipFile(archive_bytes, "w") as archive:
            for modality in ("flair", "t1ce", "t1", "t2"):
                archive.writestr(f"BraTS19_case/BraTS19_case_{modality}.nii", b"nifti-data")
            archive.writestr("BraTS19_case/BraTS19_case_seg.nii", b"ground-truth")
        archive_bytes.seek(0)

        with TemporaryDirectory() as directory:
            task_dir = Path(directory) / "task-http-3d-archive-001"
            task_dir.mkdir()
            stored = {
                modality: task_dir / "input" / f"{modality}.nii.gz"
                for modality in ("flair", "t1ce", "t1", "t2")
            }
            with (
                patch("api.routes.tasks.task_repository.count", return_value=0),
                patch("api.routes.tasks.create_task_dir", return_value=task_dir),
                patch(
                    "api.routes.tasks.initialize_uploaded_volume_task",
                    return_value=stored,
                ) as initialize_volume,
                TestClient(app) as client,
            ):
                response = client.post(
                    "/tasks/3d/archive",
                    files={"archive": ("BraTS19_case.zip", archive_bytes.getvalue(), "application/zip")},
                    data={"name": "ZIP patient"},
                )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(set(response.json()["input_files"]), {"flair", "t1ce", "t1", "t2"})
        self.assertEqual(
            set(initialize_volume.call_args.kwargs["uploads"]),
            {"flair", "t1ce", "t1", "t2"},
        )

    def test_case_zip_returns_selectable_candidates_when_a_modality_is_duplicated(self) -> None:
        archive_bytes = BytesIO()
        with zipfile.ZipFile(archive_bytes, "w") as archive:
            for modality in ("flair", "t1ce", "t1", "t2"):
                archive.writestr(f"case_a_{modality}.nii", b"nifti-data")
            archive.writestr("case_b_flair.nii", b"nifti-data")
        archive_bytes.seek(0)

        with (
            patch("api.routes.tasks.task_repository.count", return_value=0),
            TestClient(app) as client,
        ):
            response = client.post(
                "/tasks/3d/archive",
                files={"archive": ("two-cases.zip", archive_bytes.getvalue(), "application/zip")},
            )

        self.assertEqual(response.status_code, status.HTTP_422_UNPROCESSABLE_CONTENT)
        detail = response.json()["detail"]
        self.assertEqual(detail["code"], "archive_modality_selection_required")
        self.assertEqual(detail["modalities"]["flair"]["reason"], "duplicate")
        self.assertEqual(len(detail["modalities"]["flair"]["candidates"]), 2)

    def test_case_zip_accepts_manual_replacements_for_every_modality(self) -> None:
        archive_bytes = BytesIO()
        with zipfile.ZipFile(archive_bytes, "w") as archive:
            archive.writestr("case_notes.txt", b"notes")
        archive_bytes.seek(0)

        with TemporaryDirectory() as directory:
            task_dir = Path(directory) / "task-http-3d-archive-manual-001"
            task_dir.mkdir()
            stored = {
                modality: task_dir / "input" / f"{modality}.nii.gz"
                for modality in ("flair", "t1ce", "t1", "t2")
            }
            with (
                patch("api.routes.tasks.task_repository.count", return_value=0),
                patch("api.routes.tasks.create_task_dir", return_value=task_dir),
                patch(
                    "api.routes.tasks.initialize_uploaded_volume_task",
                    return_value=stored,
                ) as initialize_volume,
                TestClient(app) as client,
            ):
                response = client.post(
                    "/tasks/3d/archive",
                    files={
                        "archive": ("case.zip", archive_bytes.getvalue(), "application/zip"),
                        **{
                            modality: (f"manual_{modality}.nii", b"nifti-data", "application/octet-stream")
                            for modality in stored
                        },
                    },
                )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(
            set(initialize_volume.call_args.kwargs["uploads"]),
            {"flair", "t1ce", "t1", "t2"},
        )

    def test_case_zip_returns_a_client_error_when_an_entry_cannot_be_read(self) -> None:
        archive_bytes = BytesIO()
        with zipfile.ZipFile(archive_bytes, "w") as archive:
            for modality in ("flair", "t1ce", "t1", "t2"):
                archive.writestr(f"case_{modality}.nii", b"nifti-data")
        archive_bytes.seek(0)

        with (
            patch("api.routes.tasks.task_repository.count", return_value=0),
            patch(
                "api.routes.tasks.initialize_uploaded_volume_task",
                side_effect=RuntimeError("File is encrypted, password required"),
            ),
            TestClient(app) as client,
        ):
            response = client.post(
                "/tasks/3d/archive",
                files={"archive": ("encrypted.zip", archive_bytes.getvalue(), "application/zip")},
            )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("无法读取", response.json()["detail"])

    def test_task_list_forwards_search_and_time_filters(self) -> None:
        with (
            patch(
                "api.routes.tasks.task_repository.list_tasks",
                return_value=([], 0),
            ) as list_tasks,
            TestClient(app) as client,
        ):
            response = client.get(
                "/tasks",
                params={
                    "q": "  Patient Alpha  ",
                    "status": "succeeded",
                    "created_from": "2026-01-01T08:00:00+08:00",
                    "created_to": "2026-01-02T08:00:00+08:00",
                },
            )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        list_tasks.assert_called_once_with(
            limit=20,
            offset=0,
            status=TaskStatus.SUCCEEDED,
            query="Patient Alpha",
            created_from=datetime.fromisoformat("2026-01-01T00:00:00+00:00"),
            created_to=datetime.fromisoformat("2026-01-02T00:00:00+00:00"),
            user_id=TEST_USER.user_id,
        )

    def test_task_list_rejects_reversed_time_range(self) -> None:
        with (
            patch("api.routes.tasks.task_repository.list_tasks") as list_tasks,
            TestClient(app) as client,
        ):
            response = client.get(
                "/tasks",
                params={
                    "created_from": "2026-01-02T00:00:00Z",
                    "created_to": "2026-01-01T00:00:00Z",
                },
            )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        list_tasks.assert_not_called()

    def test_archived_task_list_forwards_filters_and_exposes_archive_times(self) -> None:
        archived_at = datetime.fromisoformat("2026-07-28T12:00:00+00:00")
        task_record = TaskRecord(
            task_id="task-archived-001",
            name="Archived test",
            status=TaskStatus.FAILED,
            created_at=archived_at - timedelta(days=1),
            updated_at=archived_at,
            archived_at=archived_at,
            input=StoredTaskInput(
                size_bytes=1,
                sha256="a" * 64,
            ),
        )

        with (
            patch(
                "api.routes.tasks.task_repository.list_archived_tasks",
                return_value=([task_record], 1),
            ) as list_archived_tasks,
            TestClient(app) as client,
        ):
            response = client.get(
                "/tasks/archived",
                params={
                    "q": "  Archived test  ",
                    "status": "failed",
                    "limit": 10,
                    "offset": 0,
                },
            )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        list_archived_tasks.assert_called_once_with(
            limit=10,
            offset=0,
            status=TaskStatus.FAILED,
            query="Archived test",
            user_id=TEST_USER.user_id,
        )
        payload = response.json()
        self.assertEqual(payload["total"], 1)
        self.assertEqual(payload["items"][0]["task_id"], task_record.task_id)
        self.assertEqual(
            datetime.fromisoformat(
                payload["items"][0]["archived_at"].replace("Z", "+00:00")
            ),
            archived_at,
        )
        self.assertEqual(
            datetime.fromisoformat(
                payload["items"][0]["purge_eligible_at"].replace("Z", "+00:00")
            ),
            archived_at + timedelta(days=SETTINGS.task_archive_grace_days),
        )

    def test_task_run_history_supports_model_filter_and_pagination(self) -> None:
        task_dir = Path("output") / "task-run-history-001"
        first_created_at = datetime.fromisoformat("2026-01-01T00:00:00+00:00")
        second_created_at = datetime.fromisoformat("2026-01-02T00:00:00+00:00")
        record = TaskRecord(
            task_id=task_dir.name,
            name="Run history",
            status=TaskStatus.SUCCEEDED,
            created_at=first_created_at,
            updated_at=second_created_at,
            input=StoredTaskInput(
                size_bytes=1,
                sha256="a" * 64,
            ),
            runs=[
                TaskRunRecord(
                    run_id="classification-old",
                    model=ModelName.CLASSIFICATION,
                    result_file="runs/classification/old/result.json",
                    created_at=first_created_at,
                    inference_ms=10.0,
                ),
                TaskRunRecord(
                    run_id="classification-new",
                    model=ModelName.CLASSIFICATION,
                    result_file="runs/classification/new/result.json",
                    created_at=second_created_at,
                    inference_ms=8.0,
                ),
                TaskRunRecord(
                    run_id="segmentation-new",
                    model=ModelName.SEGMENTATION,
                    result_file="runs/segmentation/new/result.json",
                    created_at=second_created_at,
                    inference_ms=20.0,
                ),
            ],
        )

        with (
            patch("api.routes.tasks.require_task_dir", return_value=task_dir),
            patch("api.routes.tasks.task_repository.load", return_value=record),
            TestClient(app) as client,
        ):
            response = client.get(
                f"/tasks/{task_dir.name}/runs",
                params={"model": "classification", "limit": 1, "offset": 0},
            )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        payload = response.json()
        self.assertEqual(payload["total"], 2)
        self.assertEqual(payload["items"][0]["run_id"], "classification-new")
        self.assertEqual(payload["items"][0]["model"], "classification")
        self.assertNotIn("result_file", payload["items"][0])

    def test_delete_task_archives_data_and_returns_purge_eligibility(self) -> None:
        archived_at = datetime.fromisoformat("2026-07-28T12:00:00+00:00")
        task_record = TaskRecord(
            task_id="task-delete-001",
            name="Delete test",
            status=TaskStatus.SUCCEEDED,
            created_at=archived_at - timedelta(minutes=1),
            updated_at=archived_at,
            archived_at=archived_at,
            input=StoredTaskInput(
                size_bytes=1,
                sha256="a" * 64,
            ),
        )

        with (
            patch("api.routes.tasks.archive_task", return_value=task_record),
            TestClient(app) as client,
        ):
            response = client.delete(f"/tasks/{task_record.task_id}")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        payload = response.json()
        self.assertEqual(payload["schema_version"], "0.1")
        self.assertEqual(payload["task_id"], task_record.task_id)
        self.assertEqual(payload["status"], "archived")
        self.assertEqual(
            datetime.fromisoformat(payload["archived_at"].replace("Z", "+00:00")),
            archived_at,
        )
        self.assertEqual(
            datetime.fromisoformat(
                payload["purge_eligible_at"].replace("Z", "+00:00")
            ),
            archived_at + timedelta(days=SETTINGS.task_archive_grace_days),
        )

    def test_delete_task_rejects_active_task(self) -> None:
        with (
            patch(
                "api.routes.tasks.archive_task",
                side_effect=ValueError("排队、运行或等待取消的任务不能删除"),
            ),
            TestClient(app) as client,
        ):
            response = client.delete("/tasks/task-running-001")

        self.assertEqual(response.status_code, status.HTTP_409_CONFLICT)
        self.assertEqual(
            response.json()["detail"],
            "排队、运行或等待取消的任务不能删除",
        )

    def test_restore_task_returns_original_task_status(self) -> None:
        restored_at = datetime.fromisoformat("2026-07-28T13:00:00+00:00")
        task_record = TaskRecord(
            task_id="task-restore-001",
            name="Restore test",
            status=TaskStatus.FAILED,
            created_at=restored_at - timedelta(days=1),
            updated_at=restored_at,
            archived_at=None,
            input=StoredTaskInput(
                size_bytes=1,
                sha256="a" * 64,
            ),
        )

        with (
            patch("api.routes.tasks.restore_task", return_value=task_record),
            TestClient(app) as client,
        ):
            response = client.post(f"/tasks/{task_record.task_id}/restore")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        payload = response.json()
        self.assertEqual(payload["status"], "restored")
        self.assertEqual(payload["task_status"], "failed")
        self.assertEqual(
            datetime.fromisoformat(payload["restored_at"].replace("Z", "+00:00")),
            restored_at,
        )

    def test_restore_task_rejects_nonarchived_task(self) -> None:
        with (
            patch(
                "api.routes.tasks.restore_task",
                side_effect=ValueError("任务未归档，无需恢复"),
            ),
            TestClient(app) as client,
        ):
            response = client.post("/tasks/task-not-archived/restore")

        self.assertEqual(response.status_code, status.HTTP_409_CONFLICT)
        self.assertEqual(response.json()["detail"], "任务未归档，无需恢复")

    def test_upload_enqueue_query_and_fetch_result(self) -> None:
        now = datetime.fromisoformat("2026-01-01T00:00:00+00:00")
        with TemporaryDirectory() as directory:
            task_dir = Path(directory) / "task-http-001"
            task_dir.mkdir()
            input_dir = task_dir / "input"
            input_dir.mkdir()
            input_paths = {
                modality: input_dir / f"{modality}.nii.gz"
                for modality in ("flair", "t1ce", "t1", "t2")
            }
            for input_path in input_paths.values():
                input_path.write_bytes(b"not-used-by-mock")
            frontend_result = task_dir / "frontend_result.json"
            frontend_result.write_text(
                json.dumps(
                    {
                        "task_id": task_dir.name,
                        "analysis_mode": "3d",
                        "input_files": {
                            modality: path.name
                            for modality, path in input_paths.items()
                        },
                        "classification": {"class": "yes"},
                        "timing": {"classification_inference_ms": 12.5},
                        "image_path": "private/path.png",
                    }
                ),
                encoding="utf-8",
            )
            record = TaskRecord(
                task_id=task_dir.name,
                name="HTTP workflow test",
                status=TaskStatus.SUCCEEDED,
                created_at=now,
                updated_at=now,
                completed_models=[],
                input=StoredTaskInput(
                    size_bytes=4,
                    sha256="a" * 64,
                    modalities={
                        modality: StoredTaskModality(
                            path=f"input/{path.name}",
                            size_bytes=1,
                            sha256=modality * 16,
                        )
                        for modality, path in input_paths.items()
                    },
                ),
                job=TaskJobRecord(
                    id="job-http-001",
                    queue="inference",
                    status=JobStatus.SUCCEEDED,
                    queued_at=now,
                    started_at=now,
                    finished_at=now,
                ),
            )
            queued_job = {
                "id": "job-http-001",
                "queue": "inference",
                "status": "queued",
                "attempt": 0,
                "max_retries": 1,
                "queued_at": now.isoformat(),
            }

            with (
                patch("api.routes.tasks.create_task_dir", return_value=task_dir),
                patch(
                    "api.routes.tasks.initialize_uploaded_volume_task",
                    return_value=input_paths,
                ),
                patch("api.routes.tasks.require_task_dir", return_value=task_dir),
                patch(
                    "api.routes.tasks.enqueue_task_run",
                    return_value=(queued_job, False),
                ),
                patch(
                    "api.routes.tasks.user_quota_lock",
                    return_value=nullcontext(),
                ) as quota_lock,
                patch("api.routes.tasks.reconcile_task_job", return_value=record),
                TestClient(app) as client,
            ):
                created = client.post(
                    "/tasks/3d",
                    files={
                        modality: (path.name, b"nifti-data", "application/octet-stream")
                        for modality, path in input_paths.items()
                    },
                    data={"name": "HTTP workflow test"},
                )
                enqueued = client.post(
                    f"/tasks/{task_dir.name}/run-async",
                )
                task_status = client.get(f"/tasks/{task_dir.name}")
                result_file = client.get(
                    f"/tasks/{task_dir.name}/files/frontend_result.json"
                )

        self.assertEqual(created.status_code, status.HTTP_201_CREATED)
        self.assertEqual(created.json()["task_id"], task_dir.name)
        self.assertEqual(enqueued.status_code, status.HTTP_202_ACCEPTED)
        quota_lock.assert_called_once_with(TEST_USER.user_id)
        self.assertEqual(enqueued.json()["job"]["id"], "job-http-001")
        self.assertEqual(task_status.status_code, status.HTTP_200_OK)
        self.assertEqual(task_status.json()["status"], "succeeded")
        self.assertEqual(
            task_status.json()["frontend_result"]["timing"]["classification_inference_ms"],
            12.5,
        )
        self.assertNotIn("image_path", task_status.json()["frontend_result"])
        self.assertEqual(result_file.status_code, status.HTTP_200_OK)
        self.assertNotIn("image_path", result_file.json())

    def test_active_task_status_skips_intermediate_frontend_result(self) -> None:
        now = datetime.fromisoformat("2026-01-01T00:00:00+00:00")
        record = TaskRecord(
            task_id="task-active-result-001",
            name="Active result",
            status=TaskStatus.RUNNING,
            created_at=now,
            updated_at=now,
            input=StoredTaskInput(size_bytes=1, sha256="a" * 64),
        )
        with TemporaryDirectory() as directory:
            task_dir = Path(directory) / record.task_id
            task_dir.mkdir()
            (task_dir / "frontend_result.json").write_text(
                json.dumps({"classification": {"class": "yes"}}),
                encoding="utf-8",
            )
            with (
                patch("api.routes.tasks.require_task_dir", return_value=task_dir),
                patch("api.routes.tasks.reconcile_task_job", return_value=record),
                TestClient(app) as client,
            ):
                response = client.get(f"/tasks/{record.task_id}")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIsNone(response.json()["frontend_result"])

    def test_terminal_task_status_skips_job_progress_lookup(self) -> None:
        now = datetime.fromisoformat("2026-01-01T00:00:00+00:00")
        record = TaskRecord(
            task_id="task-terminal-result-001",
            name="Terminal result",
            status=TaskStatus.SUCCEEDED,
            created_at=now,
            updated_at=now,
            input=StoredTaskInput(size_bytes=1, sha256="a" * 64),
        )
        with TemporaryDirectory() as directory:
            task_dir = Path(directory) / record.task_id
            task_dir.mkdir()
            with (
                patch("api.routes.tasks.require_task_dir", return_value=task_dir),
                patch("api.routes.tasks.reconcile_task_job", return_value=record),
                patch("api.routes.tasks.get_task_job_progress") as get_progress,
                TestClient(app) as client,
            ):
                response = client.get(f"/tasks/{record.task_id}")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIsNone(response.json()["progress"])
        get_progress.assert_not_called()

    def test_cancel_endpoint_returns_the_cancellation_state(self) -> None:
        task_dir = Path("output") / "task-http-cancel-001"
        canceled_record = Mock(status=TaskStatus.CANCELED)

        with (
            patch("api.routes.tasks.require_task_dir", return_value=task_dir),
            patch("api.routes.tasks.cancel_task_run", return_value=canceled_record),
            TestClient(app) as client,
        ):
            response = client.post(f"/tasks/{task_dir.name}/cancel")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(
            response.json(),
            {
                "schema_version": "0.1",
                "task_id": task_dir.name,
                "status": "canceled",
            },
        )

    def test_cancel_endpoint_rejects_non_active_tasks(self) -> None:
        task_dir = Path("output") / "task-http-cancel-conflict"

        with (
            patch("api.routes.tasks.require_task_dir", return_value=task_dir),
            patch(
                "api.routes.tasks.cancel_task_run",
                side_effect=ValueError("仅排队或运行中的任务可以取消"),
            ),
            TestClient(app) as client,
        ):
            response = client.post(f"/tasks/{task_dir.name}/cancel")

        self.assertEqual(response.status_code, status.HTTP_409_CONFLICT)
        self.assertEqual(response.json()["detail"], "仅排队或运行中的任务可以取消")

    def test_internal_error_file_is_not_downloadable(self) -> None:
        with TemporaryDirectory() as directory:
            task_dir = Path(directory) / "task-with-private-error"
            task_dir.mkdir()
            (task_dir / "error.json").write_text(
                json.dumps({"traceback": "File C:/private/service.py"}),
                encoding="utf-8",
            )
            with (
                patch("api.routes.tasks.require_task_dir", return_value=task_dir),
                TestClient(app) as client,
            ):
                response = client.get(f"/tasks/{task_dir.name}/files/error.json")

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)


if __name__ == "__main__":
    unittest.main()

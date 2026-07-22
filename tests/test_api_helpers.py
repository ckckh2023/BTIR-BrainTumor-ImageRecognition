'''任务路由内部辅助函数的回归测试'''

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from fastapi import HTTPException, status
from fastapi.testclient import TestClient
from redis.exceptions import RedisError

from api.app import app
from api.routes import tasks
from api.routes.tasks import (
    bad_request_http_error,
    resolve_run_threshold,
    task_summary_data,
)
from api.routes.runtime import get_liveness, get_queue_status, get_readiness
from contracts.task import RunTaskRequest
from core.task_definitions import JobStatus, TaskStatus
from core.task_records import StoredTaskInput, TaskErrorRecord, TaskJobRecord, TaskRecord
from core.settings import SETTINGS
from services.task_lock import TaskLockBusyError, TaskLockUnavailableError
from services.task_queue import TaskQueueUnavailableError
from services.task_queue import get_inference_queue_status
from unittest.mock import Mock, patch


class TaskRouteHelperTests(unittest.TestCase):
    '''验证默认阈值和预期异常的 HTTP 转换规则'''

    def test_resolve_run_threshold_prefers_request_value(self) -> None:
        self.assertEqual(resolve_run_threshold(RunTaskRequest(threshold=0.7)), 0.7)
        self.assertEqual(resolve_run_threshold(None), SETTINGS.default_segment_threshold)

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
                path="input/image.png",
                storage_mode="uploaded",
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

    def test_get_task_falls_back_to_recorded_input_filename(self) -> None:
        task_dir = Path("output") / "task-result-image-001"
        now = datetime.fromisoformat("2026-01-01T00:00:00+00:00")
        record = TaskRecord(
            task_id=task_dir.name,
            name="结果图片回退测试",
            status=TaskStatus.SUCCEEDED,
            created_at=now,
            updated_at=now,
            input=StoredTaskInput(
                path="input/uploaded-image.png",
                storage_mode="uploaded",
                size_bytes=1,
                sha256="a" * 64,
            ),
        )

        with (
            patch("api.routes.tasks.require_task_dir", return_value=task_dir),
            patch("api.routes.tasks.reconcile_task_job", return_value=record),
            patch("api.routes.tasks.Path.is_file", return_value=True),
            patch(
                "api.routes.tasks.Path.read_text",
                return_value='{"task_id": "task-result-image-001"}',
            ),
        ):
            response = tasks.get_task(task_dir.name)

        self.assertEqual(response.frontend_result["image_file"], "uploaded-image.png")

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
        self.assertEqual(caught.exception.detail["components"]["inference_worker"], "unavailable")

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
        queue = Mock()
        queue.count = 2
        queue.started_job_registry.count = 1
        queue.failed_job_registry.count = 3
        queue.get_job_ids.return_value = ["job-oldest"]
        oldest_job = Mock(enqueued_at=datetime.now().astimezone() - timedelta(seconds=4))

        with (
            patch("services.task_queue.get_task_queue", return_value=queue),
            patch("services.task_queue.get_active_inference_workers", return_value=[Mock(), Mock()]),
            patch("services.task_queue.Job.fetch", return_value=oldest_job),
        ):
            queue_status = get_inference_queue_status()

        self.assertEqual(queue_status["active_workers"], 2)
        self.assertEqual(queue_status["queued_jobs"], 2)
        self.assertEqual(queue_status["running_jobs"], 1)
        self.assertEqual(queue_status["failed_jobs"], 3)
        self.assertGreaterEqual(queue_status["oldest_wait_seconds"], 4)

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

    def test_upload_enqueue_query_and_fetch_result(self) -> None:
        now = datetime.fromisoformat("2026-01-01T00:00:00+00:00")
        with TemporaryDirectory() as directory:
            task_dir = Path(directory) / "task-http-001"
            task_dir.mkdir()
            input_path = task_dir / "input" / "image.png"
            input_path.parent.mkdir()
            input_path.write_bytes(b"not-used-by-mock")
            frontend_result = task_dir / "frontend_result.json"
            frontend_result.write_text(
                json.dumps(
                    {
                        "task_id": task_dir.name,
                        "image_file": "image.png",
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
                    path="input/image.png",
                    storage_mode="uploaded",
                    size_bytes=1,
                    sha256="a" * 64,
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
                    "api.routes.tasks.initialize_uploaded_task",
                    return_value=input_path,
                ),
                patch("api.routes.tasks.require_task_dir", return_value=task_dir),
                patch(
                    "api.routes.tasks.enqueue_task_run",
                    return_value=(queued_job, False),
                ),
                patch("api.routes.tasks.reconcile_task_job", return_value=record),
                TestClient(app) as client,
            ):
                created = client.post(
                    "/tasks",
                    files={"file": ("image.png", b"image-data", "image/png")},
                    data={"name": "HTTP workflow test"},
                )
                enqueued = client.post(
                    f"/tasks/{task_dir.name}/run-async",
                    json={"threshold": 0.5},
                )
                task_status = client.get(f"/tasks/{task_dir.name}")
                result_file = client.get(
                    f"/tasks/{task_dir.name}/files/frontend_result.json"
                )

        self.assertEqual(created.status_code, status.HTTP_201_CREATED)
        self.assertEqual(created.json()["task_id"], task_dir.name)
        self.assertEqual(enqueued.status_code, status.HTTP_202_ACCEPTED)
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


if __name__ == "__main__":
    unittest.main()

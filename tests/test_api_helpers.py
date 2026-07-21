'''任务路由内部辅助函数的回归测试'''

from __future__ import annotations

import asyncio
from datetime import datetime
import json
from pathlib import Path
import unittest

from fastapi import HTTPException, status
from redis.exceptions import RedisError

from api.app import app
from api.routes import tasks
from api.routes.tasks import (
    bad_request_http_error,
    resolve_run_threshold,
    task_summary_data,
)
from api.routes.runtime import get_liveness, get_readiness
from contracts.task import RunTaskRequest
from core.task_definitions import TaskStatus
from core.task_records import StoredTaskInput, TaskErrorRecord, TaskRecord
from core.settings import SETTINGS
from services.task_lock import TaskLockBusyError, TaskLockUnavailableError
from services.task_queue import TaskQueueUnavailableError
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
        ):
            readiness = get_readiness()

        self.assertEqual(readiness["status"], "ready")
        self.assertEqual(
            readiness["components"],
            {"task_database": "ok", "redis": "ok", "models": "ok"},
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


if __name__ == "__main__":
    unittest.main()

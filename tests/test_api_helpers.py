'''任务路由内部辅助函数的回归测试'''

from __future__ import annotations

import asyncio
from datetime import datetime
import json
import unittest

from fastapi import status

from api.app import app
from api.routes.tasks import (
    bad_request_http_error,
    resolve_run_threshold,
    task_summary_data,
)
from contracts.task import RunTaskRequest
from core.task_definitions import TaskStatus
from core.task_records import StoredTaskInput, TaskErrorRecord, TaskRecord
from core.settings import SETTINGS
from services.task_lock import TaskLockBusyError, TaskLockUnavailableError
from services.task_queue import TaskQueueUnavailableError


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


if __name__ == "__main__":
    unittest.main()

'''任务路由内部辅助函数的回归测试'''

from __future__ import annotations

import asyncio
import json
import unittest

from fastapi import status

from api.app import app
from api.routes.tasks import bad_request_http_error, resolve_run_threshold
from contracts.task import RunTaskRequest
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


if __name__ == "__main__":
    unittest.main()

'''任务路由内部辅助函数的回归测试'''

from __future__ import annotations

import unittest

from fastapi import status

from api.routes.tasks import resolve_run_threshold, task_operation_http_error
from contracts.task import RunTaskRequest
from core.settings import SETTINGS
from services.task_lock import TaskLockBusyError, TaskLockUnavailableError
from services.task_queue import TaskQueueUnavailableError


class TaskRouteHelperTests(unittest.TestCase):
    '''验证默认阈值和预期异常的 HTTP 转换规则'''

    def test_resolve_run_threshold_prefers_request_value(self) -> None:
        self.assertEqual(resolve_run_threshold(RunTaskRequest(threshold=0.7)), 0.7)
        self.assertEqual(resolve_run_threshold(None), SETTINGS.default_segment_threshold)

    def test_task_operation_error_statuses_are_stable(self) -> None:
        cases = [
            (TaskLockBusyError("busy"), status.HTTP_409_CONFLICT),
            (TaskLockUnavailableError("lock unavailable"), status.HTTP_503_SERVICE_UNAVAILABLE),
            (TaskQueueUnavailableError("queue unavailable"), status.HTTP_503_SERVICE_UNAVAILABLE),
            (ValueError("invalid request"), status.HTTP_400_BAD_REQUEST),
        ]
        for exc, expected_status in cases:
            with self.subTest(exc=type(exc).__name__):
                response = task_operation_http_error(exc)
                self.assertEqual(response.status_code, expected_status)
                self.assertEqual(response.detail, str(exc))


if __name__ == "__main__":
    unittest.main()

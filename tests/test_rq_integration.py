'''使用真实 Redis 与 RQ SimpleWorker 的可选集成测试'''

from __future__ import annotations

import unittest
from uuid import uuid4

from redis import Redis
from redis.exceptions import RedisError
from rq import Queue, Retry, SimpleWorker
from rq.job import JobStatus as RqJobStatus

from core.settings import SETTINGS


class RqIntegrationTests(unittest.TestCase):
    '''验证 RQ 作业可执行、结果可读且失败后可真实重试'''

    def setUp(self) -> None:
        self.connection = Redis.from_url(
            SETTINGS.redis_url,
            decode_responses=False,
            socket_connect_timeout=1,
            socket_timeout=1,
        )
        try:
            self.connection.ping()
        except RedisError as exc:
            self.skipTest(f"Redis 不可用，跳过 RQ 集成测试：{exc}")

        self.queue = Queue(
            f"btir-test-{uuid4().hex}",
            connection=self.connection,
        )
        self.counter_key = f"btir-test:counter:{uuid4().hex}"

    def tearDown(self) -> None:
        if hasattr(self, "queue"):
            self.queue.delete(delete_jobs=True)
        if hasattr(self, "counter_key"):
            self.connection.delete(self.counter_key)

    def _work_once(self) -> None:
        worker = SimpleWorker([self.queue], connection=self.connection)
        worker.work(burst=True, logging_level="CRITICAL")

    def test_worker_executes_enqueued_job_and_persists_result(self) -> None:
        payload = {"task_id": "rq-integration-001"}
        job = self.queue.enqueue("tests.rq_test_jobs.echo_payload", payload)

        self._work_once()
        job.refresh()

        self.assertEqual(job.get_status(), RqJobStatus.FINISHED)
        self.assertEqual(job.return_value(), payload)

    def test_worker_retries_once_after_a_real_failure(self) -> None:
        job = self.queue.enqueue(
            "tests.rq_test_jobs.fail_once",
            self.counter_key,
            retry=Retry(max=1),
        )

        self._work_once()
        job.refresh()

        self.assertEqual(job.get_status(), RqJobStatus.FINISHED)
        self.assertEqual(job.return_value(), {"attempts": 2})
        self.assertEqual(int(self.connection.get(self.counter_key)), 2)


if __name__ == "__main__":
    unittest.main()

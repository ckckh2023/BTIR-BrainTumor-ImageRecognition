'''使用真实 Redis 与 RQ SimpleWorker 的可选集成测试'''

from __future__ import annotations

from dataclasses import replace
from io import BytesIO
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from uuid import uuid4

from fastapi.testclient import TestClient
from PIL import Image
from redis import Redis
from redis.exceptions import RedisError
from rq import Queue, Retry, SimpleWorker
from rq.job import JobStatus as RqJobStatus

from core.settings import SETTINGS
from api.app import app
from repositories.task_repository import SqliteTaskRepository


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

    def test_http_task_runs_through_real_rq_and_reports_completion(self) -> None:
        '''HTTP 入队后的作业由真实 Redis/RQ 执行，模型调用以轻量替身隔离'''
        with TemporaryDirectory() as directory:
            root = Path(directory)
            settings = replace(
                SETTINGS,
                output_dir=root / "output",
                task_database_path=root / "tasks.db",
                task_queue_name=self.queue.name,
            )
            repository = SqliteTaskRepository(settings.task_database_path)
            image_stream = BytesIO()
            Image.new("RGB", (2, 2), color="white").save(image_stream, format="PNG")

            def fake_run_models(task_dir: Path, _: float) -> SimpleNamespace:
                (task_dir / "frontend_result.json").write_text(
                    json.dumps(
                        {
                            "task_id": task_dir.name,
                            "image_file": "image.png",
                            "classification": {"class": "no"},
                        }
                    ),
                    encoding="utf-8",
                )
                return SimpleNamespace(
                    classification_result={"model_result_path": "classification.json"},
                    segmentation_result={"model_result_path": "segmentation.json"},
                    total_inference_ms=1.0,
                )

            with (
                patch("api.routes.tasks.SETTINGS", settings),
                patch("api.routes.tasks.task_repository", repository),
                patch("services.task_files.SETTINGS", settings),
                patch("services.task_files.task_repository", repository),
                patch("services.task_queue.SETTINGS", settings),
                patch("services.task_queue.task_repository", repository),
                patch("services.task_queue.get_task_queue", return_value=self.queue),
                patch("services.task_state.task_repository", repository),
                patch("workers.inference_jobs.SETTINGS", settings),
                patch("workers.inference_jobs.run_task_models", side_effect=fake_run_models),
                TestClient(app) as client,
            ):
                created = client.post(
                    "/tasks",
                    files={"file": ("image.png", image_stream.getvalue(), "image/png")},
                )
                self.assertEqual(created.status_code, 201)
                task_id = created.json()["task_id"]

                enqueued = client.post(f"/tasks/{task_id}/run-async")
                self.assertEqual(enqueued.status_code, 202)

                self._work_once()
                completed = client.get(f"/tasks/{task_id}")

        self.assertEqual(completed.status_code, 200)
        payload = completed.json()
        self.assertEqual(payload["status"], "succeeded")
        self.assertEqual(payload["job"]["status"], "succeeded")
        self.assertEqual(payload["frontend_result"]["classification"]["class"], "no")


if __name__ == "__main__":
    unittest.main()

'''异步任务入队与 Worker 调度流程的离线回归测试'''

from __future__ import annotations

from contextlib import nullcontext
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, call, patch

from redis.exceptions import RedisError

from services.task_queue import TaskQueueUnavailableError, enqueue_task_run
from services.task_runner import run_task_models
from workers.inference_jobs import run_task_job


class FakeTaskRepository:
    '''仅供测试使用的内存任务仓储'''

    def __init__(self, record: dict[str, object] | None) -> None:
        self.record = deepcopy(record)
        self.saved_records: list[dict[str, object]] = []

    def exists(self, _: Path) -> bool:
        return self.record is not None

    def load(self, _: Path) -> dict[str, object]:
        if self.record is None:
            raise AssertionError("测试仓储中不存在任务")
        return deepcopy(self.record)

    def save(self, _: Path, record: dict[str, object]) -> Path:
        self.record = deepcopy(record)
        self.saved_records.append(deepcopy(record))
        return Path("task.db")


class FakeQueue:
    '''记录入队请求并返回固定 RQ 作业 ID'''

    def __init__(self) -> None:
        self.enqueue = Mock(return_value=SimpleNamespace(id="job-001"))


class AsyncQueueTests(unittest.TestCase):
    '''验证 RQ 入队、去重与队列异常'''

    def setUp(self) -> None:
        self.task_dir = Path("output") / "task-async-001"
        self.record = {
            "task_id": self.task_dir.name,
            "name": "异步测试任务",
            "status": "created",
            "created_at": "2026-01-01T00:00:00+00:00",
            "updated_at": "2026-01-01T00:00:00+00:00",
            "completed_models": [],
            "input": {},
        }

    @staticmethod
    def _no_lock(_: str):
        return nullcontext()

    def test_duplicate_enqueue_reuses_existing_job(self) -> None:
        repository = FakeTaskRepository(self.record)
        queue = FakeQueue()

        with (
            patch("services.task_queue.task_repository", repository),
            patch("services.task_queue.task_write_lock", self._no_lock),
            patch("services.task_queue.get_task_queue", return_value=queue),
        ):
            first_job, first_reused = enqueue_task_run(self.task_dir, 0.5)
            second_job, second_reused = enqueue_task_run(self.task_dir, 0.5)

        self.assertFalse(first_reused)
        self.assertTrue(second_reused)
        self.assertEqual(first_job["id"], "job-001")
        self.assertEqual(second_job["id"], "job-001")
        self.assertEqual(queue.enqueue.call_count, 1)
        self.assertEqual(repository.record["status"], "queued")

    def test_queue_error_is_converted_to_service_error(self) -> None:
        repository = FakeTaskRepository(self.record)
        queue = FakeQueue()
        queue.enqueue.side_effect = RedisError("Redis unavailable")

        with (
            patch("services.task_queue.task_repository", repository),
            patch("services.task_queue.task_write_lock", self._no_lock),
            patch("services.task_queue.get_task_queue", return_value=queue),
            self.assertRaises(TaskQueueUnavailableError),
        ):
            enqueue_task_run(self.task_dir, 0.5)

        self.assertEqual(repository.record["status"], "created")


class TaskRunnerTests(unittest.TestCase):
    '''验证完整推理统一入口的调用顺序与返回结果'''

    def test_runner_executes_and_persists_both_models(self) -> None:
        task_dir = Path("output") / "task-runner-001"
        image_path = task_dir / "input" / "image.png"
        run_dir = task_dir / "runs" / "segmentation" / "run-001"
        classification_result = {"model_result_path": "classification.json"}
        segmentation_result = {"model_result_path": "segmentation.json"}

        with (
            patch("services.task_runner.load_task_image", return_value=image_path),
            patch(
                "services.task_runner.classify",
                return_value={"class": "yes"},
            ) as classify,
            patch("services.task_runner.create_run_dir", return_value=run_dir),
            patch(
                "services.task_runner.segment",
                return_value={"tumor_pixels": 1},
            ) as segment,
            patch(
                "services.task_runner.persist_model_result",
                side_effect=[classification_result, segmentation_result],
            ) as persist_result,
        ):
            result = run_task_models(task_dir, 0.5)

        self.assertEqual(result.image_path, image_path)
        self.assertEqual(result.classification_result, classification_result)
        self.assertEqual(result.segmentation_result, segmentation_result)
        classify.assert_called_once_with(image_path)
        segment.assert_called_once_with(
            image_path=image_path,
            threshold=0.5,
            output_dir=run_dir,
        )
        self.assertEqual(persist_result.call_count, 2)
        self.assertEqual(
            persist_result.call_args_list,
            [
                call(
                    task_dir=task_dir,
                    image_path=image_path,
                    model_name="classification",
                    result={"class": "yes"},
                ),
                call(
                    task_dir=task_dir,
                    image_path=image_path,
                    model_name="segmentation",
                    result={"tumor_pixels": 1},
                    run_dir=run_dir,
                ),
            ],
        )


class InferenceWorkerTests(unittest.TestCase):
    '''验证 Worker 的成功和失败状态转换'''

    def setUp(self) -> None:
        self.task_id = "task-worker-001"
        self.task_dir = Path("output") / self.task_id
        self.image_path = self.task_dir / "input" / "image.png"
        self.run_dir = self.task_dir / "runs" / "segmentation" / "run-001"
        self.job = SimpleNamespace(id="job-worker-001")

    def test_worker_marks_task_succeeded_after_both_models_finish(self) -> None:
        update_status = Mock(
            return_value={
                "status": "succeeded",
                "completed_models": ["classification", "segmentation"],
            }
        )
        classification_result = {"model_result_path": "classification.json"}
        segmentation_result = {"model_result_path": "segmentation.json"}

        with (
            patch("workers.inference_jobs.get_current_job", return_value=self.job),
            patch("workers.inference_jobs.get_task_dir", return_value=self.task_dir),
            patch("workers.inference_jobs.update_task_execution_status", update_status),
            patch(
                "workers.inference_jobs.run_task_models",
                return_value=SimpleNamespace(
                    classification_result=classification_result,
                    segmentation_result=segmentation_result,
                ),
            ) as run_models,
        ):
            result = run_task_job(self.task_id, 0.5)

        self.assertEqual(result["status"], "succeeded")
        self.assertEqual(result["completed_models"], ["classification", "segmentation"])
        self.assertEqual(result["classification_result_file"], "classification.json")
        self.assertEqual(result["segmentation_result_file"], "segmentation.json")
        run_models.assert_called_once_with(self.task_dir, 0.5)
        self.assertEqual(
            update_status.call_args_list,
            [
                call(
                    self.task_dir,
                    "running",
                    job_id=self.job.id,
                    queue_name=unittest.mock.ANY,
                ),
                call(self.task_dir, "succeeded", job_id=self.job.id),
            ],
        )

    def test_worker_marks_task_failed_when_model_raises_error(self) -> None:
        update_status = Mock()

        with (
            patch("workers.inference_jobs.get_current_job", return_value=self.job),
            patch("workers.inference_jobs.get_task_dir", return_value=self.task_dir),
            patch("workers.inference_jobs.update_task_execution_status", update_status),
            patch(
                "workers.inference_jobs.run_task_models",
                side_effect=RuntimeError("simulated inference failure"),
            ),
            self.assertRaisesRegex(RuntimeError, "simulated inference failure"),
        ):
            run_task_job(self.task_id, 0.5)

        self.assertEqual(update_status.call_args_list[0].args[1], "running")
        self.assertEqual(update_status.call_args_list[1].args[1], "failed")
        self.assertEqual(update_status.call_args_list[1].kwargs["job_id"], self.job.id)
        self.assertIn(
            "RuntimeError: simulated inference failure",
            update_status.call_args_list[1].kwargs["error"],
        )


if __name__ == "__main__":
    unittest.main()

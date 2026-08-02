'''异步任务入队与 Worker 调度流程的离线回归测试'''

from __future__ import annotations

from contextlib import nullcontext
from copy import deepcopy
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import ANY, Mock, call, patch

from redis.exceptions import RedisError
from rq.exceptions import InvalidJobOperation
from rq.job import JobStatus as RqJobStatus

from core.settings import SETTINGS
from core.task_definitions import JobStatus, ModelName, TaskStatus
from core.task_records import StoredTaskInput, TaskErrorRecord, TaskJobRecord, TaskRecord
from services.inference_service import preload_inference_models
from services.task_queue import (
    TaskQueueUnavailableError,
    cancel_task_run,
    clear_task_queue_state,
    enqueue_task_run,
    reconcile_active_tasks,
    reconcile_task_job,
)
from services.task_runner import (
    TaskCancellationRequested,
    run_task_models,
)
from services.task_results import build_frontend_result
from services.task_lock import TaskLockBusyError
from services.task_state import mark_task_queued, update_task_execution_status
from workers.inference_jobs import run_task_job
from workers import run_worker


class FakeTaskRepository:
    '''仅供测试使用的内存任务仓储'''

    def __init__(self, record: TaskRecord | None) -> None:
        self.record = deepcopy(record)
        self.saved_records: list[TaskRecord] = []

    def exists(self, _: Path) -> bool:
        return self.record is not None

    def load(self, _: Path) -> TaskRecord:
        if self.record is None:
            raise AssertionError("测试仓储中不存在任务")
        return deepcopy(self.record)

    def save(self, _: Path, record: TaskRecord) -> Path:
        self.record = deepcopy(record)
        self.saved_records.append(deepcopy(record))
        return Path("task.db")


class FakeQueue:
    '''记录入队请求并返回固定 RQ 作业 ID'''

    def __init__(self) -> None:
        self.name = "inference-test"
        self.enqueue = Mock(return_value=SimpleNamespace(id="job-001"))


class AsyncQueueTests(unittest.TestCase):
    '''验证 RQ 入队、去重与队列异常'''

    def setUp(self) -> None:
        self.task_dir = Path("output") / "task-async-001"
        self.record = TaskRecord.model_validate(
            {
                "task_id": self.task_dir.name,
                "name": "异步测试任务",
                "status": "created",
                "created_at": "2026-01-01T00:00:00+00:00",
                "updated_at": "2026-01-01T00:00:00+00:00",
                "completed_models": [],
                "input": {
                    "size_bytes": 1,
                    "sha256": "a" * 64,
                },
            }
        )

    @staticmethod
    def _no_lock(_: str):
        return nullcontext()

    @staticmethod
    def _empty_queue(name: str) -> Mock:
        queue = Mock()
        queue.name = name
        queue.get_job_ids.return_value = []
        for attribute in (
            "started_job_registry",
            "failed_job_registry",
            "finished_job_registry",
            "deferred_job_registry",
            "scheduled_job_registry",
            "canceled_job_registry",
        ):
            registry = Mock()
            registry.get_job_ids.return_value = []
            setattr(queue, attribute, registry)
        return queue

    def test_duplicate_enqueue_reuses_existing_job(self) -> None:
        repository = FakeTaskRepository(self.record)
        queue = FakeQueue()

        with (
            patch("services.task_queue.task_repository", repository),
            patch("services.task_queue.task_write_lock", self._no_lock),
            patch("services.task_queue.get_task_queue", return_value=queue),
            patch(
                "services.task_queue.SETTINGS",
                replace(SETTINGS, task_job_max_retries=1),
            ),
        ):
            first_job, first_reused = enqueue_task_run(self.task_dir)
            second_job, second_reused = enqueue_task_run(self.task_dir)

        self.assertFalse(first_reused)
        self.assertTrue(second_reused)
        self.assertEqual(first_job["id"], "job-001")
        self.assertEqual(second_job["id"], "job-001")
        self.assertEqual(queue.enqueue.call_count, 1)
        self.assertEqual(queue.enqueue.call_args.kwargs["retry"].max, 1)
        self.assertEqual(repository.record.status, TaskStatus.QUEUED)

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
            enqueue_task_run(self.task_dir)

        self.assertEqual(repository.record.status, TaskStatus.CREATED)

    def test_3d_task_is_enqueued_on_the_3d_queue(self) -> None:
        record = deepcopy(self.record)
        record.analysis_mode = "3d"
        repository = FakeTaskRepository(record)
        queue = FakeQueue()
        queue.name = "inference-3d-test"

        with (
            patch("services.task_queue.task_repository", repository),
            patch("services.task_queue.task_write_lock", self._no_lock),
            patch(
                "services.task_queue.get_task_queue",
                return_value=queue,
            ) as get_queue,
        ):
            job, reused = enqueue_task_run(self.task_dir)

        self.assertFalse(reused)
        get_queue.assert_called_once_with()
        self.assertEqual(job["queue"], "inference-3d-test")

    def test_clear_queue_dry_run_only_reports_project_state(self) -> None:
        queue = Mock()
        queue.get_job_ids.return_value = ["queued-job"]
        registries = [Mock() for _ in range(6)]
        for registry in registries:
            registry.get_job_ids.return_value = []
        registries[1].get_job_ids.return_value = ["failed-job"]
        (
            queue.started_job_registry,
            queue.failed_job_registry,
            queue.finished_job_registry,
            queue.deferred_job_registry,
            queue.scheduled_job_registry,
            queue.canceled_job_registry,
        ) = registries
        redis_client = Mock()
        redis_client.scan_iter.return_value = [b"btir:task:task-001:write"]
        with (
            patch(
                "services.task_queue.get_task_queue",
                return_value=queue,
            ),
            patch("services.task_queue.get_redis_client", return_value=redis_client),
            patch(
                "services.task_queue.get_active_inference_workers",
                return_value=[Mock()],
            ),
        ):
            report = clear_task_queue_state(dry_run=True)

        self.assertEqual(report.queued_job_count, 1)
        self.assertEqual(report.registry_job_count, 1)
        self.assertEqual(report.task_lock_count, 1)
        self.assertEqual(report.active_worker_count, 1)
        queue.delete.assert_not_called()
        redis_client.delete.assert_not_called()

    def test_clear_queue_removes_only_queue_jobs_registries_and_task_locks(self) -> None:
        queue = Mock()
        queue.get_job_ids.return_value = ["queued-job"]
        registries = [Mock() for _ in range(6)]
        for registry in registries:
            registry.get_job_ids.return_value = []
        registries[1].get_job_ids.return_value = ["failed-job"]
        (
            queue.started_job_registry,
            queue.failed_job_registry,
            queue.finished_job_registry,
            queue.deferred_job_registry,
            queue.scheduled_job_registry,
            queue.canceled_job_registry,
        ) = registries
        redis_client = Mock()
        redis_client.scan_iter.return_value = [b"btir:task:task-001:write"]
        failed_job = Mock()
        with (
            patch(
                "services.task_queue.get_task_queue",
                return_value=queue,
            ),
            patch("services.task_queue.get_redis_client", return_value=redis_client),
            patch(
                "services.task_queue.get_active_inference_workers",
                return_value=[],
            ),
            patch("services.task_queue.Job.fetch", return_value=failed_job),
        ):
            clear_task_queue_state(dry_run=False)

        queue.delete.assert_called_once_with(delete_jobs=True)
        registries[1].remove.assert_called_once_with(
            "failed-job",
            delete_job=False,
        )
        failed_job.delete.assert_called_once_with()
        redis_client.delete.assert_called_once_with(
            b"btir:task:task-001:write"
        )

    def test_clear_queue_rejects_active_worker(self) -> None:
        queue = Mock()
        queue.get_job_ids.return_value = []
        registries = [Mock() for _ in range(6)]
        for registry in registries:
            registry.get_job_ids.return_value = []
        (
            queue.started_job_registry,
            queue.failed_job_registry,
            queue.finished_job_registry,
            queue.deferred_job_registry,
            queue.scheduled_job_registry,
            queue.canceled_job_registry,
        ) = registries
        redis_client = Mock()
        redis_client.scan_iter.return_value = []
        with (
            patch(
                "services.task_queue.get_task_queue",
                return_value=queue,
            ),
            patch("services.task_queue.get_redis_client", return_value=redis_client),
            patch(
                "services.task_queue.get_active_inference_workers",
                return_value=[Mock()],
            ),
            self.assertRaisesRegex(ValueError, "请先停止"),
        ):
            clear_task_queue_state(dry_run=False)

        queue.delete.assert_not_called()

    def test_manual_retry_rejects_nonfailed_task(self) -> None:
        record = deepcopy(self.record)
        record.status = TaskStatus.SUCCEEDED
        repository = FakeTaskRepository(record)

        with (
            patch("services.task_queue.task_repository", repository),
            patch("services.task_queue.task_write_lock", self._no_lock),
            self.assertRaisesRegex(ValueError, "仅失败任务"),
        ):
            enqueue_task_run(self.task_dir, retry_failed_only=True)

    def test_manual_retry_enqueues_failed_task(self) -> None:
        record = deepcopy(self.record)
        record.status = TaskStatus.FAILED
        repository = FakeTaskRepository(record)
        queue = FakeQueue()

        with (
            patch("services.task_queue.task_repository", repository),
            patch("services.task_queue.task_write_lock", self._no_lock),
            patch("services.task_queue.get_task_queue", return_value=queue),
        ):
            job, reused = enqueue_task_run(
                self.task_dir,
                retry_failed_only=True,
            )

        self.assertFalse(reused)
        self.assertEqual(job["status"], "queued")
        self.assertEqual(repository.record.status, TaskStatus.QUEUED)

    def test_queued_task_is_canceled_immediately(self) -> None:
        record = deepcopy(self.record)
        record.status = TaskStatus.QUEUED
        record.job = TaskJobRecord(
            id="job-cancel-001",
            queue="inference",
            status=JobStatus.QUEUED,
        )
        repository = FakeTaskRepository(record)
        rq_job = Mock()
        rq_job.get_status.return_value = RqJobStatus.QUEUED

        with (
            patch("services.task_queue.task_repository", repository),
            patch("services.task_queue.task_write_lock", self._no_lock),
            patch("services.task_queue.get_redis_client", return_value=Mock()),
            patch("services.task_queue.Job.fetch", return_value=rq_job),
        ):
            canceled = cancel_task_run(self.task_dir)

        rq_job.cancel.assert_called_once_with()
        self.assertEqual(canceled.status, TaskStatus.CANCELED)
        self.assertEqual(canceled.job.status, JobStatus.CANCELED)

    def test_already_canceled_rq_job_keeps_cancellation_idempotent(self) -> None:
        record = deepcopy(self.record)
        record.status = TaskStatus.QUEUED
        record.job = TaskJobRecord(
            id="job-cancel-idempotent",
            queue="inference",
            status=JobStatus.QUEUED,
        )
        repository = FakeTaskRepository(record)
        rq_job = Mock()
        rq_job.get_status.return_value = RqJobStatus.QUEUED
        rq_job.cancel.side_effect = InvalidJobOperation("already canceled")

        with (
            patch("services.task_queue.task_repository", repository),
            patch("services.task_queue.task_write_lock", self._no_lock),
            patch("services.task_queue.get_redis_client", return_value=Mock()),
            patch("services.task_queue.Job.fetch", return_value=rq_job),
        ):
            canceled = cancel_task_run(self.task_dir)

        self.assertEqual(canceled.status, TaskStatus.CANCELED)

    def test_running_task_records_a_cooperative_cancellation_request(self) -> None:
        record = deepcopy(self.record)
        record.status = TaskStatus.RUNNING
        record.job = TaskJobRecord(
            id="job-cancel-002",
            queue="inference",
            status=JobStatus.RUNNING,
        )
        repository = FakeTaskRepository(record)
        rq_job = Mock(meta={})
        rq_job.get_status.return_value = RqJobStatus.STARTED

        with (
            patch("services.task_queue.task_repository", repository),
            patch("services.task_queue.task_write_lock", self._no_lock),
            patch("services.task_queue.get_redis_client", return_value=Mock()),
            patch("services.task_queue.Job.fetch", return_value=rq_job),
        ):
            cancellation_requested = cancel_task_run(self.task_dir)

        self.assertEqual(cancellation_requested.status, TaskStatus.CANCEL_REQUESTED)
        self.assertTrue(rq_job.meta["cancel_requested"])
        rq_job.save_meta.assert_called_once_with()


class TaskRunnerTests(unittest.TestCase):
    '''验证完整推理统一入口的调用顺序与返回结果'''

    def test_runner_dispatches_3d_task_to_volume_classification_and_segmentation(self) -> None:
        task_dir = Path("output") / "task-runner-3d-001"
        input_dir = task_dir / "input"
        run_dir = task_dir / "runs" / "segmentation" / "run-3d-001"
        modality_paths = {
            modality: input_dir / f"{modality}.nii.gz"
            for modality in ("flair", "t1ce", "t1", "t2")
        }
        classification_result = {"model_result_path": "classification.json"}
        segmentation_result = {"model_result_path": "segmentation.json"}

        with (
            patch(
                "services.task_runner.load_task_modalities",
                return_value=modality_paths,
            ),
            patch(
                "services.task_runner.classify_volume",
                return_value={
                    "classification": {
                        "class": "yes",
                        "method": "vit_binary_multislice_mean",
                    },
                },
            ) as classify_3d,
            patch("services.task_runner.create_run_dir", return_value=run_dir),
            patch(
                "services.task_runner.segment_volume",
                return_value={
                    "mask_path": run_dir / "prediction.nii.gz",
                },
            ) as segment_3d,
            patch(
                "services.task_runner.persist_model_result",
                side_effect=[classification_result, segmentation_result],
            ) as persist_result,
        ):
            result = run_task_models(task_dir)

        self.assertEqual(result.classification_result, classification_result)
        self.assertEqual(result.segmentation_result, segmentation_result)
        classify_3d.assert_called_once_with(modality_paths)
        segment_3d.assert_called_once_with(
            modality_paths=modality_paths,
            output_dir=run_dir,
        )
        self.assertEqual(
            persist_result.call_args_list[0].kwargs["model_name"],
            ModelName.CLASSIFICATION,
        )
        self.assertEqual(
            persist_result.call_args_list[1].kwargs["model_name"],
            ModelName.SEGMENTATION,
        )


class InferenceWorkerTests(unittest.TestCase):
    '''验证 Worker 的成功和失败状态转换'''

    def setUp(self) -> None:
        self.task_id = "task-worker-001"
        self.task_dir = Path("output") / self.task_id
        self.job = SimpleNamespace(id="job-worker-001")

    def test_worker_marks_task_succeeded_after_both_models_finish(self) -> None:
        update_status = Mock(
            return_value=TaskRecord.model_validate(
                {
                    "task_id": self.task_id,
                    "name": "worker 测试任务",
                    "status": "succeeded",
                    "created_at": "2026-01-01T00:00:00+00:00",
                    "updated_at": "2026-01-01T00:00:00+00:00",
                    "completed_models": ["classification", "segmentation"],
                    "input": {
                        "size_bytes": 1,
                        "sha256": "a" * 64,
                    },
                }
            )
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
                    total_inference_ms=12.5,
                ),
            ) as run_models,
        ):
            result = run_task_job(self.task_id)

        self.assertEqual(result["status"], "succeeded")
        self.assertEqual(result["completed_models"], ["classification", "segmentation"])
        self.assertEqual(result["classification_result_file"], "classification.json")
        self.assertEqual(result["segmentation_result_file"], "segmentation.json")
        run_models.assert_called_once_with(
            self.task_dir,
            should_cancel=ANY,
            progress_callback=ANY,
        )
        self.assertEqual(
            update_status.call_args_list,
            [
                call(
                    self.task_dir,
                    "running",
                    job_id=self.job.id,
                    queue_name=unittest.mock.ANY,
                ),
                call(
                    self.task_dir,
                    "succeeded",
                    job_id=self.job.id,
                    execution_ms=unittest.mock.ANY,
                ),
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
            run_task_job(self.task_id)

        self.assertEqual(update_status.call_args_list[0].args[1], "running")
        self.assertEqual(update_status.call_args_list[1].args[1], "failed")
        self.assertEqual(update_status.call_args_list[1].kwargs["job_id"], self.job.id)
        self.assertEqual(
            update_status.call_args_list[1].kwargs["error"],
            "模型推理失败，请稍后重试或联系管理员",
        )
        self.assertEqual(
            update_status.call_args_list[1].kwargs["error_code"],
            "inference_failed",
        )
        self.assertIn(
            "RuntimeError: simulated inference failure",
            update_status.call_args_list[1].kwargs["error_detail"],
        )

    def test_worker_marks_task_canceled_between_models(self) -> None:
        canceled_record = SimpleNamespace(
            status=TaskStatus.CANCELED,
            completed_models=[ModelName.CLASSIFICATION],
        )
        update_status = Mock(return_value=canceled_record)

        with (
            patch("workers.inference_jobs.get_current_job", return_value=self.job),
            patch("workers.inference_jobs.get_task_dir", return_value=self.task_dir),
            patch("workers.inference_jobs.update_task_execution_status", update_status),
            patch(
                "workers.inference_jobs.run_task_models",
                side_effect=TaskCancellationRequested("canceled"),
            ),
        ):
            result = run_task_job(self.task_id)

        self.assertEqual(result["status"], "canceled")
        self.assertEqual(result["completed_models"], ["classification"])
        self.assertEqual(update_status.call_args_list[0].args[1], JobStatus.RUNNING)
        self.assertEqual(update_status.call_args_list[1].args[1], JobStatus.CANCELED)

    def test_worker_requeues_first_failure_when_rq_retry_is_available(self) -> None:
        retrying_job = SimpleNamespace(
            id=self.job.id,
            should_retry=Mock(return_value=True),
        )
        update_status = Mock()

        with (
            patch("workers.inference_jobs.get_current_job", return_value=retrying_job),
            patch("workers.inference_jobs.get_task_dir", return_value=self.task_dir),
            patch("workers.inference_jobs.update_task_execution_status", update_status),
            patch(
                "workers.inference_jobs.run_task_models",
                side_effect=RuntimeError("transient inference failure"),
            ),
            self.assertRaisesRegex(RuntimeError, "transient inference failure"),
        ):
            run_task_job(self.task_id)

        self.assertEqual(update_status.call_args_list[0].args[1], "running")
        self.assertEqual(update_status.call_args_list[1].args[1], "queued")
        self.assertIsNone(update_status.call_args_list[1].kwargs["error"])


class TaskReconciliationTests(unittest.TestCase):
    '''验证任务状态会跟随 RQ 的实际状态收敛。'''

    def setUp(self) -> None:
        self.task_dir = Path("output") / "task-reconcile-001"
        now = datetime.now(timezone.utc)
        self.record = TaskRecord(
            task_id=self.task_dir.name,
            name="对账测试任务",
            status=TaskStatus.RUNNING,
            created_at=now,
            updated_at=now,
            completed_models=[ModelName.CLASSIFICATION, ModelName.SEGMENTATION],
            input=StoredTaskInput(
                size_bytes=1,
                sha256="a" * 64,
            ),
            job=TaskJobRecord(
                id="job-reconcile-001",
                queue="inference",
                status=JobStatus.RUNNING,
                queued_at=now - timedelta(seconds=5),
                started_at=now,
            ),
        )

    def test_finished_rq_job_recovers_missing_success_writeback(self) -> None:
        repository = FakeTaskRepository(self.record)
        rq_job = SimpleNamespace(get_status=Mock(return_value=RqJobStatus.FINISHED))
        update_status = Mock(return_value=self.record)

        with (
            patch("services.task_queue.task_repository", repository),
            patch("services.task_queue.get_redis_client", return_value=Mock()),
            patch("services.task_queue.Job.fetch", return_value=rq_job),
            patch("services.task_queue.update_task_execution_status", update_status),
        ):
            reconcile_task_job(self.task_dir)

        update_status.assert_called_once_with(
            self.task_dir,
            JobStatus.SUCCEEDED,
            job_id="job-reconcile-001",
            queue_name="inference",
        )

    def test_stale_running_job_is_marked_failed(self) -> None:
        self.record.job.started_at = datetime.now(timezone.utc) - timedelta(seconds=10)
        repository = FakeTaskRepository(self.record)
        rq_job = SimpleNamespace(get_status=Mock(return_value=RqJobStatus.STARTED))
        update_status = Mock(return_value=self.record)

        with (
            patch("services.task_queue.task_repository", repository),
            patch("services.task_queue.get_redis_client", return_value=Mock()),
            patch("services.task_queue.Job.fetch", return_value=rq_job),
            patch("services.task_queue.update_task_execution_status", update_status),
            patch(
                "services.task_queue.SETTINGS",
                replace(SETTINGS, task_stale_after_seconds=1),
            ),
        ):
            reconcile_task_job(self.task_dir)

        self.assertEqual(update_status.call_args.args[1], JobStatus.FAILED)
        self.assertIn("超过允许执行时长", update_status.call_args.kwargs["error"])

    def test_active_task_sweep_reconciles_every_active_record(self) -> None:
        queued_record = deepcopy(self.record)
        queued_record.task_id = "task-reconcile-queued"
        queued_record.status = TaskStatus.QUEUED
        queued_record.job.id = "job-reconcile-queued"
        reconciled_record = deepcopy(self.record)
        reconciled_record.status = TaskStatus.SUCCEEDED
        reconciled_record.job.status = JobStatus.SUCCEEDED
        repository = Mock()
        repository.list_active_tasks.return_value = [self.record, queued_record]

        with (
            patch("services.task_queue.task_repository", repository),
            patch(
                "services.task_queue.reconcile_task_job",
                side_effect=[reconciled_record, queued_record],
            ) as reconcile_job,
        ):
            report = reconcile_active_tasks(limit=20)

        self.assertEqual(report.scanned_task_count, 2)
        self.assertEqual(report.changed_task_ids, ["task-reconcile-001"])
        self.assertEqual(reconcile_job.call_count, 2)
        self.assertEqual(report.skipped_task_ids, [])

    def test_active_task_sweep_skips_a_task_currently_being_written(self) -> None:
        repository = Mock()
        repository.list_active_tasks.return_value = [self.record]

        with (
            patch("services.task_queue.task_repository", repository),
            patch(
                "services.task_queue.reconcile_task_job",
                side_effect=TaskLockBusyError("busy"),
            ),
        ):
            report = reconcile_active_tasks(limit=20)

        self.assertEqual(report.scanned_task_count, 0)
        self.assertEqual(report.changed_task_ids, [])
        self.assertEqual(report.skipped_task_ids, ["task-reconcile-001"])


class TaskPerformanceRecordTests(unittest.TestCase):
    '''验证任务性能字段会被持久化，并作为结果 JSON 的补充信息输出'''

    def setUp(self) -> None:
        self.task_dir = Path("output") / "task-performance-001"
        now = datetime.now(timezone.utc)
        self.record = TaskRecord(
            task_id=self.task_dir.name,
            name="性能记录测试任务",
            status=TaskStatus.QUEUED,
            created_at=now,
            updated_at=now,
            completed_models=[],
            input=StoredTaskInput(
                size_bytes=1,
                sha256="a" * 64,
            ),
            job=TaskJobRecord(
                id="job-performance-001",
                queue="inference",
                status=JobStatus.QUEUED,
                queued_at=now - timedelta(seconds=2),
            ),
        )

    def test_job_records_queue_wait_and_execution_time(self) -> None:
        repository = FakeTaskRepository(self.record)

        with (
            patch("services.task_state.task_repository", repository),
            patch("services.task_state.task_write_lock", lambda _: nullcontext()),
        ):
            running = update_task_execution_status(
                self.task_dir,
                JobStatus.RUNNING,
                job_id="job-performance-001",
            )
            completed = update_task_execution_status(
                self.task_dir,
                JobStatus.SUCCEEDED,
                job_id="job-performance-001",
                execution_ms=123.456,
            )

        self.assertIsNotNone(running.job.queue_wait_ms)
        self.assertGreater(running.job.queue_wait_ms, 1_000)
        self.assertEqual(completed.job.queue_wait_ms, running.job.queue_wait_ms)
        self.assertEqual(completed.job.execution_ms, 123.456)

    def test_queue_transition_is_owned_by_task_state(self) -> None:
        record = deepcopy(self.record)
        record.status = TaskStatus.FAILED
        record.error = TaskErrorRecord(
            message="previous attempt failed",
            updated_at=datetime.now(timezone.utc),
        )
        repository = FakeTaskRepository(record)

        updated = mark_task_queued(
            self.task_dir,
            job_id="job-performance-002",
            queue_name="inference",
            max_retries=1,
            record=record,
            repository=repository,
        )

        self.assertEqual(updated.status, TaskStatus.QUEUED)
        self.assertEqual(updated.job.id, "job-performance-002")
        self.assertEqual(updated.job.max_retries, 1)
        self.assertIsNone(updated.error)
        self.assertEqual(repository.record.job.id, "job-performance-002")

    def test_frontend_result_includes_model_timings(self) -> None:
        result = build_frontend_result(
            self.task_dir,
            input_files={"flair": "flair.nii.gz"},
            classification={
                "model": "classification",
                "classification": {
                    "class": "yes",
                    "confidence": 0.9,
                },
                "run_directory": "runs/classification/run-001",
                "timing": {"inference_ms": 12.5},
            },
            segmentation={
                "model": "segmentation",
                "spatial": {"shape": [1, 1, 1]},
                "labels": {"scheme": "BraTS"},
                "regions": {},
                "mask_path": self.task_dir / "runs" / "segmentation" / "run-001" / "mask.nii.gz",
                "run_directory": "runs/segmentation/run-001",
                "timing": {"inference_ms": 34.5},
            },
        )

        self.assertEqual(
            result["timing"],
            {"classification_inference_ms": 12.5, "segmentation_inference_ms": 34.5},
        )
        self.assertEqual(result["schema_version"], "1.0")
        self.assertEqual(result["classification"]["model"], "classification")
        self.assertEqual(result["segmentation"]["model"], "segmentation")

    def test_frontend_result_supports_local_vit_classification(self) -> None:
        result = build_frontend_result(
            self.task_dir,
            input_files={"flair": "flair.nii.gz"},
            classification={
                "model": "models/classification/vit-binary",
                "classification": {
                    "class": "yes",
                    "confidence": 0.91,
                    "method": "vit_binary_multislice_mean",
                    "experimental": True,
                    "evaluated_slices": 32,
                },
                "run_directory": "runs/classification/run-3d-001",
            },
        )

        self.assertEqual(result["analysis_mode"], "3d")
        self.assertEqual(result["status"], "partial")
        self.assertEqual(result["completed_models"], ["classification"])
        self.assertEqual(
            result["classification"]["method"],
            "vit_binary_multislice_mean",
        )
        self.assertTrue(result["classification"]["experimental"])
        self.assertEqual(
            result["classification"]["model"],
            "models/classification/vit-binary",
        )

    def test_frontend_result_preserves_local_vit_threshold(self) -> None:
        result = build_frontend_result(
            self.task_dir,
            input_files={"flair": "flair.nii.gz"},
            classification={
                "model": "models/classification/vit-binary",
                "classification": {
                    "class": "no",
                    "confidence": 0.72,
                    "method": "vit_binary_multislice_mean",
                    "experimental": True,
                    "threshold": 0.5,
                },
                "run_directory": "runs/classification/run-native-3d-001",
            },
        )

        classification = result["classification"]
        self.assertEqual(classification["method"], "vit_binary_multislice_mean")
        self.assertEqual(classification["threshold"], 0.5)
        self.assertEqual(
            classification["model"],
            "models/classification/vit-binary",
        )


class ModelPreloadTests(unittest.TestCase):
    '''验证模型预热会填充现有缓存，并且不会因单模型失败阻断 worker。'''

    def test_preload_loads_all_route_models(self) -> None:
        vit_classifier_model = Mock()
        segmentation_3d_model = Mock()
        with (
            patch(
                "services.inference_service._load_vit_classifier_namespace",
                return_value={"torch": Mock()},
            ),
            patch(
                "services.inference_service._load_3d_segmentation_namespace",
                return_value={"torch": Mock()},
            ),
            patch("services.inference_service.resolve_device", return_value="cpu"),
            patch(
                "services.inference_service._load_vit_classifier_model",
                vit_classifier_model,
            ),
            patch(
                "services.inference_service._load_3d_segmentation_model",
                segmentation_3d_model,
            ),
        ):
            outcomes = preload_inference_models()

        vit_classifier_model.assert_called_once_with("cpu")
        segmentation_3d_model.assert_called_once_with("cpu")
        self.assertIsInstance(outcomes["classification"], float)
        self.assertIsInstance(outcomes["segmentation"], float)

    def test_preload_continues_when_one_model_fails(self) -> None:
        segmentation_3d_model = Mock()
        with (
            patch(
                "services.inference_service._load_vit_classifier_namespace",
                return_value={"torch": Mock()},
            ),
            patch(
                "services.inference_service._load_3d_segmentation_namespace",
                return_value={"torch": Mock()},
            ),
            patch("services.inference_service.resolve_device", return_value="cpu"),
            patch(
                "services.inference_service._load_vit_classifier_model",
                side_effect=RuntimeError("classifier unavailable"),
            ),
            patch(
                "services.inference_service._load_3d_segmentation_model",
                segmentation_3d_model,
            ),
        ):
            outcomes = preload_inference_models()

        self.assertIn("failed: RuntimeError", outcomes["classification"])
        segmentation_3d_model.assert_called_once_with("cpu")
        self.assertIsInstance(outcomes["segmentation"], float)

    def test_windows_worker_preloads_before_processing_queue(self) -> None:
        worker = Mock()
        with (
            patch("workers.run_worker.os.name", "nt"),
            patch(
                "workers.run_worker.get_task_queue",
                return_value=Mock(),
            ) as get_queue,
            patch("workers.run_worker.get_redis_client", return_value=Mock()),
            patch("workers.run_worker.SimpleWorker", return_value=worker),
            patch(
                "workers.run_worker.preload_inference_models", return_value={}
            ) as preload,
            patch(
                "workers.run_worker.SETTINGS",
                replace(SETTINGS, worker_preload_models=True),
            ),
        ):
            run_worker.main([])

        preload.assert_called_once_with()
        get_queue.assert_called_once_with()
        worker.work.assert_called_once_with()

    def test_linux_simple_worker_preloads_without_forking(self) -> None:
        worker = Mock()
        with (
            patch("workers.run_worker.os.name", "posix"),
            patch("workers.run_worker.get_task_queue", return_value=Mock()),
            patch("workers.run_worker.get_redis_client", return_value=Mock()),
            patch("workers.run_worker.SimpleWorker", return_value=worker),
            patch("workers.run_worker.Worker") as standard_worker,
            patch(
                "workers.run_worker.preload_inference_models", return_value={}
            ) as preload,
            patch(
                "workers.run_worker.SETTINGS",
                replace(
                    SETTINGS,
                    worker_preload_models=True,
                    linux_worker_mode="simple",
                ),
            ),
        ):
            run_worker.main([])

        preload.assert_called_once_with()
        standard_worker.assert_not_called()
        worker.work.assert_called_once_with()

    def test_linux_standard_worker_keeps_preload_disabled(self) -> None:
        worker = Mock()
        with (
            patch("workers.run_worker.os.name", "posix"),
            patch("workers.run_worker.get_task_queue", return_value=Mock()),
            patch("workers.run_worker.get_redis_client", return_value=Mock()),
            patch("workers.run_worker.Worker", return_value=worker),
            patch("workers.run_worker.SimpleWorker") as simple_worker,
            patch("workers.run_worker.preload_inference_models") as preload,
            patch(
                "workers.run_worker.SETTINGS",
                replace(
                    SETTINGS,
                    worker_preload_models=True,
                    linux_worker_mode="standard",
                ),
            ),
        ):
            run_worker.main([])

        preload.assert_not_called()
        simple_worker.assert_not_called()
        worker.work.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()

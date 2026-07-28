'''RQ 推理队列的提交入口'''

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from redis.exceptions import RedisError
from rq import Queue, Retry, Worker
from rq.exceptions import InvalidJobOperation, NoSuchJobError
from rq.job import Job, JobStatus as RqJobStatus

from core.settings import SETTINGS
from core.task_definitions import (
    ACTIVE_ASYNC_TASK_STATUSES,
    ALL_MODELS,
    JobStatus,
    TaskStatus,
)
from core.task_records import TaskRecord
from repositories.task_repository import task_repository
from repositories.task_repository_contracts import TaskNotFoundError
from services.redis_client import get_redis_client
from services.task_lock import TaskLockBusyError, task_write_lock
from services.task_state import mark_task_queued, update_task_execution_status


class TaskQueueUnavailableError(RuntimeError):
    '''Redis 或 RQ 队列不可用'''


@dataclass(frozen=True)
class TaskReconciliationReport:
    '''一次活动任务巡检的摘要'''

    scanned_task_count: int
    changed_task_ids: list[str]
    skipped_task_ids: list[str]


PENDING_RQ_STATUSES = frozenset(
    {
        RqJobStatus.QUEUED,
        RqJobStatus.SCHEDULED,
        RqJobStatus.DEFERRED,
    }
)


@lru_cache(maxsize=1)
def get_task_queue() -> Queue:
    '''获取推理任务队列'''
    return Queue(
        SETTINGS.task_queue_name,
        connection=get_redis_client(),
        default_timeout=SETTINGS.task_job_timeout_seconds,
    )


def get_active_inference_workers() -> list[Worker]:
    '''获取当前推理队列中仍被 RQ 注册为存活的 worker'''
    return [
        worker
        for worker in Worker.all(connection=get_redis_client())
        if SETTINGS.task_queue_name in worker.queue_names()
    ]


def has_active_inference_worker() -> bool:
    '''检查当前推理队列是否有仍被 RQ 注册为存活的 worker'''
    return bool(get_active_inference_workers())


def get_inference_queue_status() -> dict[str, int | float | None]:
    '''汇总推理队列的只读运维状态'''
    queue = get_task_queue()
    oldest_wait_seconds = _get_oldest_queue_wait_seconds(queue)
    return {
        "active_workers": len(get_active_inference_workers()),
        "queued_jobs": queue.count,
        "running_jobs": queue.started_job_registry.count,
        "failed_jobs": queue.failed_job_registry.count,
        "oldest_wait_seconds": oldest_wait_seconds,
    }


def _get_oldest_queue_wait_seconds(queue: Queue) -> float | None:
    job_ids = queue.get_job_ids(offset=0, length=1)
    if not job_ids:
        return None
    try:
        queued_at = Job.fetch(job_ids[0], connection=get_redis_client()).enqueued_at
    except NoSuchJobError:
        return None
    if queued_at is None:
        return None
    now = datetime.now().astimezone()
    if queued_at.tzinfo is None:
        queued_at = queued_at.replace(tzinfo=now.tzinfo)
    return round(max(0.0, (now - queued_at).total_seconds()), 3)


def enqueue_task_run(
    task_dir: Path,
    threshold: float,
    *,
    retry_failed_only: bool = False,
) -> tuple[dict[str, object], bool]:
    '''提交一次完整推理；同一任务已有活动作业时返回原作业'''
    if not task_repository.exists(task_dir):
        raise TaskNotFoundError("任务元数据不存在")

    with task_write_lock(task_dir.name):
        record = task_repository.load(task_dir)
        current_status = record.status
        existing_job = record.job
        if current_status in ACTIVE_ASYNC_TASK_STATUSES and existing_job:
            return existing_job.model_dump(mode="json"), True
        if current_status is TaskStatus.CANCELED:
            raise ValueError("已取消任务不能再次提交")
        if retry_failed_only and current_status is not TaskStatus.FAILED:
            raise ValueError("仅失败任务可以手动重试")

        try:
            retry = (
                Retry(max=SETTINGS.task_job_max_retries)
                if SETTINGS.task_job_max_retries
                else None
            )
            job = get_task_queue().enqueue(
                "workers.inference_jobs.run_task_job",
                task_dir.name,
                threshold,
                job_timeout=SETTINGS.task_job_timeout_seconds,
                result_ttl=SETTINGS.task_job_result_ttl_seconds,
                failure_ttl=SETTINGS.task_job_result_ttl_seconds,
                retry=retry,
            )
        except RedisError as exc:
            raise TaskQueueUnavailableError("Redis 队列不可用，任务无法提交") from exc

        updated_record = mark_task_queued(
            task_dir,
            job_id=job.id,
            queue_name=SETTINGS.task_queue_name,
            max_retries=SETTINGS.task_job_max_retries,
            record=record,
            repository=task_repository,
        )
        return updated_record.job.model_dump(mode="json"), False


def cancel_task_run(task_dir: Path) -> TaskRecord:
    '''取消未执行任务，或请求运行中的任务在安全阶段停止'''
    with task_write_lock(task_dir.name):
        record = task_repository.load(task_dir)
        if record.status is TaskStatus.CANCELED:
            return record
        if record.status is TaskStatus.CREATED:
            return _mark_task_canceled(task_dir, record)
        if record.job is None:
            raise ValueError("当前任务没有可取消的异步作业")

        try:
            job = Job.fetch(record.job.id, connection=get_redis_client())
            rq_status = job.get_status()
        except NoSuchJobError:
            return _mark_task_canceled(task_dir, record)
        except RedisError as exc:
            raise TaskQueueUnavailableError("Redis 队列不可用，无法取消任务") from exc

        if rq_status in PENDING_RQ_STATUSES:
            try:
                job.cancel()
            except InvalidJobOperation:
                # 并发取消时，RQ 已将作业转为 canceled；接口保持幂等。
                pass
            return _mark_task_canceled(task_dir, record)
        if rq_status is RqJobStatus.STARTED:
            job.meta["cancel_requested"] = True
            job.save_meta()
            record.status = TaskStatus.CANCEL_REQUESTED
            record.updated_at = datetime.now().astimezone()
            record.error = None
            task_repository.save(task_dir, record)
            return record
        if rq_status is RqJobStatus.CANCELED:
            return _mark_task_canceled(task_dir, record)
        raise ValueError("仅排队或运行中的任务可以取消")


def reconcile_active_tasks(
    *,
    limit: int = SETTINGS.task_reconcile_batch_size,
) -> TaskReconciliationReport:
    '''批量对账活动任务，使 worker 异常后的状态无需等待用户查询即可收敛'''
    records = task_repository.list_active_tasks(limit=limit)
    scanned_task_count = 0
    changed_task_ids: list[str] = []
    skipped_task_ids: list[str] = []

    for record in records:
        task_dir = SETTINGS.output_dir / record.task_id
        before = (record.status, record.job)
        try:
            reconciled = reconcile_task_job(task_dir)
        except TaskLockBusyError:
            skipped_task_ids.append(record.task_id)
            continue
        scanned_task_count += 1
        if (reconciled.status, reconciled.job) != before:
            changed_task_ids.append(record.task_id)

    return TaskReconciliationReport(
        scanned_task_count=scanned_task_count,
        changed_task_ids=changed_task_ids,
        skipped_task_ids=skipped_task_ids,
    )


def reconcile_task_job(task_dir: Path) -> TaskRecord:
    '''将本地活动任务与 RQ 作业状态对账，修复异常中断后的悬挂状态'''
    record = task_repository.load(task_dir)
    if record.status not in ACTIVE_ASYNC_TASK_STATUSES or record.job is None:
        return record

    try:
        rq_job = Job.fetch(record.job.id, connection=get_redis_client())
        rq_status = rq_job.get_status()
    except NoSuchJobError:
        return _mark_reconciled_task_failed(
            task_dir,
            record,
            "RQ 作业记录不存在或已过期",
        )
    except RedisError as exc:
        raise TaskQueueUnavailableError("Redis 队列不可用，无法对账任务状态") from exc

    if rq_status in PENDING_RQ_STATUSES:
        return _update_reconciled_status(task_dir, record, JobStatus.QUEUED)

    if rq_status is RqJobStatus.STARTED:
        if _is_stale_running_task(record):
            return _mark_reconciled_task_failed(
                task_dir,
                record,
                "推理作业超过允许执行时长，已标记为失败",
            )
        return _update_reconciled_status(task_dir, record, JobStatus.RUNNING)

    if rq_status is RqJobStatus.CANCELED:
        return _update_reconciled_status(task_dir, record, JobStatus.CANCELED)

    if rq_status is RqJobStatus.FINISHED:
        if ALL_MODELS <= set(record.completed_models):
            return _update_reconciled_status(task_dir, record, JobStatus.SUCCEEDED)
        return _mark_reconciled_task_failed(
            task_dir,
            record,
            "RQ 作业已结束，但模型结果未完整写入",
        )

    should_retry = getattr(rq_job, "should_retry", False)
    retry_pending = should_retry() if callable(should_retry) else bool(should_retry)
    if rq_status is RqJobStatus.FAILED and retry_pending:
        return _update_reconciled_status(task_dir, record, JobStatus.QUEUED)

    if rq_status in {
        RqJobStatus.FAILED,
        RqJobStatus.STOPPED,
    }:
        return _mark_reconciled_task_failed(
            task_dir,
            record,
            f"RQ 作业状态为 {rq_status.value}",
        )

    return record


def _is_stale_running_task(record: TaskRecord) -> bool:
    '''仅对已实际开始、超出允许时长的作业判定为悬挂'''
    if record.status not in {TaskStatus.RUNNING, TaskStatus.CANCEL_REQUESTED} or record.job is None:
        return False
    if record.job.started_at is None:
        return False
    elapsed_seconds = (datetime.now().astimezone() - record.job.started_at).total_seconds()
    return elapsed_seconds > SETTINGS.task_stale_after_seconds


def _update_reconciled_status(
    task_dir: Path,
    record: TaskRecord,
    status: JobStatus,
) -> TaskRecord:
    if record.status is TaskStatus(status.value):
        return record
    return update_task_execution_status(
        task_dir,
        status,
        job_id=record.job.id,
        queue_name=record.job.queue,
    )


def _mark_reconciled_task_failed(
    task_dir: Path,
    record: TaskRecord,
    error: str,
) -> TaskRecord:
    return update_task_execution_status(
        task_dir,
        JobStatus.FAILED,
        job_id=record.job.id,
        queue_name=record.job.queue,
        error=error,
        error_code="task_reconciliation_failed",
    )


def _mark_task_canceled(task_dir: Path, record: TaskRecord) -> TaskRecord:
    now = datetime.now().astimezone()
    record.status = TaskStatus.CANCELED
    if record.job is not None:
        record.job.status = JobStatus.CANCELED
        record.job.finished_at = now
    record.updated_at = now
    record.error = None
    task_repository.save(task_dir, record)
    return record

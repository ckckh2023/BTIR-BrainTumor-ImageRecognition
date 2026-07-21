'''RQ 推理队列的提交入口'''

from __future__ import annotations

from datetime import datetime
from functools import lru_cache
from pathlib import Path
from redis.exceptions import RedisError
from rq import Queue, Retry
from rq.exceptions import NoSuchJobError
from rq.job import Job, JobStatus as RqJobStatus

from core.settings import SETTINGS
from core.task_definitions import ALL_MODELS, JobStatus, TaskStatus
from core.task_records import TaskJobRecord, TaskRecord
from repositories.task_repository import TaskNotFoundError, task_repository
from services.redis_client import get_redis_client
from services.task_lock import task_write_lock
from services.task_state import update_task_execution_status


class TaskQueueUnavailableError(RuntimeError):
    '''Redis 或 RQ 队列不可用'''


ACTIVE_TASK_STATUSES = frozenset({TaskStatus.QUEUED, TaskStatus.RUNNING})
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
        if current_status in ACTIVE_TASK_STATUSES and existing_job:
            return existing_job.model_dump(mode="json"), True
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

        now = datetime.now().astimezone()
        job_record = TaskJobRecord(
            id=job.id,
            queue=SETTINGS.task_queue_name,
            status=JobStatus.QUEUED,
            max_retries=SETTINGS.task_job_max_retries,
            queued_at=now,
        )
        record.status = TaskStatus.QUEUED
        record.job = job_record
        record.updated_at = now
        record.error = None
        task_repository.save(task_dir, record)
        return job_record.model_dump(mode="json"), False


def reconcile_task_job(task_dir: Path) -> TaskRecord:
    '''将本地活动任务与 RQ 作业状态对账，修复异常中断后的悬挂状态'''
    record = task_repository.load(task_dir)
    if record.status not in ACTIVE_TASK_STATUSES or record.job is None:
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

    if rq_status is RqJobStatus.FINISHED:
        if ALL_MODELS <= set(record.completed_models):
            return _update_reconciled_status(task_dir, record, JobStatus.SUCCEEDED)
        return _mark_reconciled_task_failed(
            task_dir,
            record,
            "RQ 作业已结束，但模型结果未完整写入",
        )

    if rq_status is RqJobStatus.FAILED and rq_job.should_retry():
        return _update_reconciled_status(task_dir, record, JobStatus.QUEUED)

    if rq_status in {
        RqJobStatus.FAILED,
        RqJobStatus.STOPPED,
        RqJobStatus.CANCELED,
    }:
        return _mark_reconciled_task_failed(
            task_dir,
            record,
            f"RQ 作业状态为 {rq_status.value}",
        )

    return record


def _is_stale_running_task(record: TaskRecord) -> bool:
    '''仅对已实际开始、超出允许时长的作业判定为悬挂'''
    if record.status is not TaskStatus.RUNNING or record.job is None:
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

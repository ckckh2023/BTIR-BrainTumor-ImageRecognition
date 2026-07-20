'''RQ 推理队列的提交入口'''

from __future__ import annotations

from datetime import datetime
from functools import lru_cache
from pathlib import Path
from redis.exceptions import RedisError
from rq import Queue

from core.settings import SETTINGS
from core.task_definitions import JobStatus, TaskStatus
from core.task_records import TaskJobRecord
from repositories.task_repository import TaskNotFoundError, task_repository
from services.redis_client import get_redis_client
from services.task_lock import task_write_lock


class TaskQueueUnavailableError(RuntimeError):
    '''Redis 或 RQ 队列不可用'''


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
) -> tuple[dict[str, object], bool]:
    '''提交一次完整推理；同一任务已有活动作业时返回原作业'''
    if not task_repository.exists(task_dir):
        raise TaskNotFoundError("任务元数据不存在")

    with task_write_lock(task_dir.name):
        record = task_repository.load(task_dir)
        current_status = record.status
        existing_job = record.job
        if current_status in {
            TaskStatus.QUEUED,
            TaskStatus.RUNNING,
        } and existing_job:
            return existing_job.model_dump(mode="json"), True

        try:
            job = get_task_queue().enqueue(
                "workers.inference_jobs.run_task_job",
                task_dir.name,
                threshold,
                job_timeout=SETTINGS.task_job_timeout_seconds,
                result_ttl=SETTINGS.task_job_result_ttl_seconds,
                failure_ttl=SETTINGS.task_job_result_ttl_seconds,
            )
        except RedisError as exc:
            raise TaskQueueUnavailableError("Redis 队列不可用，任务无法提交") from exc

        now = datetime.now().astimezone()
        job_record = TaskJobRecord(
            id=job.id,
            queue=SETTINGS.task_queue_name,
            status=JobStatus.QUEUED,
            queued_at=now,
        )
        record.status = TaskStatus.QUEUED
        record.job = job_record
        record.updated_at = now
        record.error = None
        task_repository.save(task_dir, record)
        return job_record.model_dump(mode="json"), False

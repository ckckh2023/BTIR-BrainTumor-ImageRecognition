'''RQ 推理队列的提交入口'''

from __future__ import annotations

from datetime import datetime
from functools import lru_cache
from pathlib import Path
from typing import Any

from redis import Redis
from redis.exceptions import RedisError
from rq import Queue

from core.settings import SETTINGS
from repositories.task_repository import TaskNotFoundError, task_repository
from services.task_lock import task_write_lock


class TaskQueueUnavailableError(RuntimeError):
    '''Redis 或 RQ 队列不可用'''


@lru_cache(maxsize=1)
def get_queue_redis() -> Redis:
    '''获取 RQ 与任务锁共用的 Redis 连接'''
    return Redis.from_url(
        SETTINGS.redis_url,
        socket_connect_timeout=3,
        socket_timeout=3,
    )


@lru_cache(maxsize=1)
def get_task_queue() -> Queue:
    '''获取推理任务队列'''
    return Queue(
        SETTINGS.task_queue_name,
        connection=get_queue_redis(),
        default_timeout=SETTINGS.task_job_timeout_seconds,
    )


def enqueue_task_run(
    task_dir: Path,
    threshold: float,
) -> tuple[dict[str, Any], bool]:
    '''提交一次完整推理；同一任务已有活动作业时返回原作业'''
    if not task_repository.exists(task_dir):
        raise TaskNotFoundError("任务元数据不存在")

    with task_write_lock(task_dir.name):
        record = task_repository.load(task_dir)
        current_status = record.get("status")
        existing_job = record.get("job")
        if current_status in {"queued", "running"} and existing_job:
            return existing_job, True

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

        now = datetime.now().astimezone().isoformat()
        job_record = {
            "id": job.id,
            "queue": SETTINGS.task_queue_name,
            "status": "queued",
            "queued_at": now,
        }
        record["status"] = "queued"
        record["job"] = job_record
        record["updated_at"] = now
        record.pop("error", None)
        task_repository.save(task_dir, record)
        return job_record, False

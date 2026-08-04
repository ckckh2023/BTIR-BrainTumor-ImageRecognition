'''Redis 任务结果写回锁'''

from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator

from redis.exceptions import LockError, RedisError

from core.settings import SETTINGS
from services.redis_client import get_redis_client


class TaskLockBusyError(RuntimeError):
    '''同一任务正在写入结果'''


class TaskLockUnavailableError(RuntimeError):
    '''Redis 不可用，无法保证任务结果一致'''


@contextmanager
def _distributed_lock(
    *,
    name: str,
    busy_message: str,
    unavailable_message: str,
) -> Iterator[None]:
    lock = get_redis_client().lock(
        name=name,
        timeout=SETTINGS.task_lock_timeout_seconds,
        blocking_timeout=SETTINGS.task_lock_wait_seconds,
    )
    try:
        acquired = lock.acquire(blocking=True)
    except RedisError as exc:
        raise TaskLockUnavailableError(unavailable_message) from exc

    if not acquired:
        raise TaskLockBusyError(busy_message)

    try:
        yield
    finally:
        try:
            lock.release()
        except (LockError, RedisError):
            '''保留原业务异常'''
            pass


@contextmanager
def task_write_lock(task_id: str) -> Iterator[None]:
    '''锁住一个任务的共享结果文件写入阶段'''
    with _distributed_lock(
        name=f"btir:task:{task_id}:write",
        busy_message="该任务正在更新结果，请稍后重试",
        unavailable_message="Redis 不可用，任务结果暂时无法写入",
    ):
        yield


@contextmanager
def user_quota_lock(user_id: str) -> Iterator[None]:
    '''串行化同一用户的活动任务配额检查与入队'''
    with _distributed_lock(
        name=f"btir:user:{user_id}:quota",
        busy_message="该用户的任务配额正在更新，请稍后重试",
        unavailable_message="Redis 不可用，无法校验用户任务配额",
    ):
        yield

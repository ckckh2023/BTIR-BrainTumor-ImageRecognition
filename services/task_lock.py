'''Redis 任务结果写回锁'''

from __future__ import annotations

from contextlib import contextmanager

from redis.exceptions import LockError, RedisError

from core.settings import SETTINGS
from services.redis_client import get_redis_client


class TaskLockBusyError(RuntimeError):
    '''同一任务正在写入结果'''


class TaskLockUnavailableError(RuntimeError):
    '''Redis 不可用，无法保证任务结果一致'''


@contextmanager
def task_write_lock(task_id: str):
    '''锁住一个任务的共享结果文件写入阶段'''
    lock = get_redis_client().lock(
        name=f"btir:task:{task_id}:write",
        timeout=SETTINGS.task_lock_timeout_seconds,
        blocking_timeout=SETTINGS.task_lock_wait_seconds,
    )

    try:
        acquired = lock.acquire(blocking=True)
    except RedisError as exc:
        raise TaskLockUnavailableError("Redis 不可用，任务结果暂时无法写入") from exc
    
    if not acquired:
        raise TaskLockBusyError("该任务正在更新结果，请稍后重试")
    
    try:
        yield
    finally:
        try:
            lock.release()
        except LockError:
            # 当锁已超时或已释放，不覆盖前面的业务异常
            pass
        except RedisError:
            # 结果已通过原子写入落盘，释放失败交给 Redis 锁超时处理
            pass

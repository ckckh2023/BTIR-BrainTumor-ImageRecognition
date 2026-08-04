'''Redis 客户端的唯一创建入口'''

from __future__ import annotations

from functools import lru_cache

from redis import Redis

from core.settings import SETTINGS


@lru_cache(maxsize=1)
def get_redis_client() -> Redis:
    '''返回供 RQ 队列和任务锁共用的 Redis 客户端'''
    return Redis.from_url(
        SETTINGS.redis_url,
        decode_responses=False,
        socket_connect_timeout=SETTINGS.redis_socket_timeout_seconds,
        socket_timeout=SETTINGS.redis_socket_timeout_seconds,
    )

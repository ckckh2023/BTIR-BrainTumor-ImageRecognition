'''基于 Redis 的认证接口固定窗口限流'''

from __future__ import annotations

from dataclasses import dataclass
import hashlib

from services.redis_client import get_redis_client


_CONSUME_SCRIPT = """
local count = redis.call('INCR', KEYS[1])
if count == 1 then
    redis.call('EXPIRE', KEYS[1], ARGV[1])
end
local ttl = redis.call('TTL', KEYS[1])
return {count, ttl}
"""


@dataclass(frozen=True)
class AuthRateLimitExceededError(RuntimeError):
    retry_after_seconds: int


def _rate_limit_key(scope: str, identity: str) -> str:
    digest = hashlib.sha256(identity.encode("utf-8")).hexdigest()
    return f"btir:auth-rate:{scope}:{digest}"


def consume_auth_rate_limit(
    scope: str,
    identity: str,
    *,
    limit: int,
    window_seconds: int,
) -> None:
    '''消费一次认证请求配额；超过窗口限制时抛出带等待时间的异常'''
    result = get_redis_client().eval(
        _CONSUME_SCRIPT,
        1,
        _rate_limit_key(scope, identity),
        window_seconds,
    )
    count = int(result[0])
    ttl = max(1, int(result[1]))
    if count > limit:
        raise AuthRateLimitExceededError(retry_after_seconds=ttl)


def clear_auth_rate_limit(scope: str, identity: str) -> None:
    '''在认证成功后清除指定账号维度的失败窗口'''
    get_redis_client().delete(_rate_limit_key(scope, identity))

'''Redis 客户端集中创建逻辑的回归测试'''

from __future__ import annotations

import unittest
from unittest.mock import Mock, patch

from core.settings import SETTINGS
from services.redis_client import get_redis_client


class RedisClientTests(unittest.TestCase):
    '''验证队列和任务锁共用的 Redis 客户端配置'''

    def setUp(self) -> None:
        get_redis_client.cache_clear()

    def tearDown(self) -> None:
        get_redis_client.cache_clear()

    def test_client_is_cached_and_keeps_binary_responses(self) -> None:
        client = Mock()
        with patch(
            "services.redis_client.Redis.from_url",
            return_value=client,
        ) as from_url:
            self.assertIs(get_redis_client(), client)
            self.assertIs(get_redis_client(), client)

        from_url.assert_called_once_with(
            SETTINGS.redis_url,
            decode_responses=False,
            socket_connect_timeout=3,
            socket_timeout=3,
        )


if __name__ == "__main__":
    unittest.main()

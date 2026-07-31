'''认证限流服务回归测试'''

from __future__ import annotations

import unittest
from unittest.mock import Mock, patch

from services.auth_rate_limit import (
    AuthRateLimitExceededError,
    clear_auth_rate_limit,
    consume_auth_rate_limit,
)


class AuthRateLimitTests(unittest.TestCase):

    def test_limit_exceeded_reports_redis_ttl(self) -> None:
        redis_client = Mock()
        redis_client.eval.return_value = [4, 27]
        with patch(
            "services.auth_rate_limit.get_redis_client",
            return_value=redis_client,
        ):
            with self.assertRaises(AuthRateLimitExceededError) as raised:
                consume_auth_rate_limit(
                    "login-user",
                    "alice",
                    limit=3,
                    window_seconds=300,
                )

        self.assertEqual(raised.exception.retry_after_seconds, 27)
        key = redis_client.eval.call_args.args[2]
        self.assertTrue(key.startswith("btir:auth-rate:login-user:"))
        self.assertNotIn("alice", key)

    def test_clear_uses_the_same_hashed_key(self) -> None:
        redis_client = Mock()
        redis_client.eval.return_value = [1, 300]
        with patch(
            "services.auth_rate_limit.get_redis_client",
            return_value=redis_client,
        ):
            consume_auth_rate_limit(
                "login-user",
                "alice",
                limit=3,
                window_seconds=300,
            )
            clear_auth_rate_limit("login-user", "alice")

        consumed_key = redis_client.eval.call_args.args[2]
        redis_client.delete.assert_called_once_with(consumed_key)


if __name__ == "__main__":
    unittest.main()

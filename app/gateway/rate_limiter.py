# app/gateway/rate_limiter.py
"""
Gateway — Token-bucket rate limiter (per-user).
Algorithm: refill tokens over time, consume 1 per request.
Default: 20 requests per minute per user.
"""
import time
import logging
from typing import Dict, Tuple
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class _Bucket:
    """Internal token bucket for a single user."""
    tokens: float
    last_refill: float
    max_tokens: float
    refill_rate: float  # tokens per second


class RateLimiter:
    """
    Token-bucket rate limiter.
    - 20 requests/min/user by default.
    - In-memory dict keyed by user_id with timestamps.
    - Thread-safe enough for asyncio (single-threaded event loop).
    """

    def __init__(
        self,
        max_requests: int = 20,
        window_seconds: int = 60,
    ) -> None:
        self._max_tokens: float = float(max_requests)
        self._refill_rate: float = max_requests / window_seconds
        self._buckets: Dict[str, _Bucket] = {}

    def check(self, user_id: str) -> Tuple[bool, float]:
        """
        Check if a request is allowed for the given user.

        Returns:
            (allowed, retry_after_seconds)
            - allowed=True, retry_after=0.0 if request passes.
            - allowed=False, retry_after>0 if rate limited.
        """
        now = time.time()

        if user_id not in self._buckets:
            self._buckets[user_id] = _Bucket(
                tokens=self._max_tokens,
                last_refill=now,
                max_tokens=self._max_tokens,
                refill_rate=self._refill_rate,
            )

        bucket = self._buckets[user_id]

        # Refill tokens based on elapsed time
        elapsed = now - bucket.last_refill
        bucket.tokens = min(bucket.max_tokens, bucket.tokens + elapsed * bucket.refill_rate)
        bucket.last_refill = now

        # Try to consume 1 token
        if bucket.tokens >= 1.0:
            bucket.tokens -= 1.0
            return True, 0.0

        # Calculate how long until 1 token is available
        retry_after = (1.0 - bucket.tokens) / bucket.refill_rate
        logger.debug(
            f"Rate limited user {user_id}: retry_after={retry_after:.2f}s, "
            f"tokens={bucket.tokens:.2f}"
        )
        return False, retry_after

    def reset(self, user_id: str) -> None:
        """Reset rate limit for a specific user (e.g., after admin override)."""
        self._buckets.pop(user_id, None)

    def cleanup_stale(self, max_idle_seconds: float = 300.0) -> int:
        """
        Remove buckets that have been idle for too long.
        Call periodically to prevent memory leaks.

        Returns:
            Number of buckets removed.
        """
        now = time.time()
        stale_keys = [
            uid for uid, bucket in self._buckets.items()
            if now - bucket.last_refill > max_idle_seconds
        ]
        for key in stale_keys:
            del self._buckets[key]
        return len(stale_keys)

    @property
    def active_users(self) -> int:
        """Number of tracked user buckets."""
        return len(self._buckets)

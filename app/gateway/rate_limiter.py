"""
Gateway — Token-bucket rate limiter (per-user, per-workspace).
"""
import time
from typing import Dict, Tuple
from dataclasses import dataclass, field


@dataclass
class Bucket:
    tokens: float
    last_refill: float
    max_tokens: float
    refill_rate: float  # tokens per second

    def consume(self, cost: float = 1.0) -> bool:
        """Try to consume tokens. Returns True if allowed."""
        now = time.time()
        elapsed = now - self.last_refill
        self.tokens = min(self.max_tokens, self.tokens + elapsed * self.refill_rate)
        self.last_refill = now

        if self.tokens >= cost:
            self.tokens -= cost
            return True
        return False


class RateLimiter:
    """
    Simple token-bucket rate limiter.
    Default: 20 requests per minute per user.
    """

    def __init__(self, max_requests: int = 20, window_seconds: int = 60):
        self._buckets: Dict[str, Bucket] = {}
        self._max_tokens = float(max_requests)
        self._refill_rate = max_requests / window_seconds

    def allow(self, user_id: str) -> Tuple[bool, float]:
        """
        Check if request is allowed for user.
        
        Returns:
            (allowed, retry_after_seconds)
        """
        if user_id not in self._buckets:
            self._buckets[user_id] = Bucket(
                tokens=self._max_tokens,
                last_refill=time.time(),
                max_tokens=self._max_tokens,
                refill_rate=self._refill_rate,
            )

        bucket = self._buckets[user_id]
        if bucket.consume():
            return True, 0.0

        # Calculate retry-after
        retry_after = (1.0 - bucket.tokens) / self._refill_rate
        return False, retry_after

    def reset(self, user_id: str):
        """Reset rate limit for a user."""
        if user_id in self._buckets:
            del self._buckets[user_id]


# Global instance
rate_limiter = RateLimiter()

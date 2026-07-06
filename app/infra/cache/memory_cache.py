# app/infra/cache/memory_cache.py
"""
In-memory cache — Phase 1.
Simple dict with TTL expiration. Phase 2: Redis.
"""
import time
import logging
from typing import Any, Optional, Dict, Tuple
from app.infra.cache.base import CacheBackend
logger = logging.getLogger(__name__)


class InMemoryCache(CacheBackend):
    """Simple dict-based cache with TTL expiration."""

    def __init__(self):
        self._store: Dict[str, Tuple[Any, float]] = {}  # key → (value, expires_at)

    async def get(self, key: str) -> Optional[Any]:
        if key in self._store:
            value, expires_at = self._store[key]
            if time.time() < expires_at:
                return value
            # Expired — remove lazily
            del self._store[key]
        return None

    async def set(self, key: str, value: Any, ttl: int = 300) -> None:
        self._store[key] = (value, time.time() + ttl)

    async def delete(self, key: str) -> None:
        self._store.pop(key, None)

    async def exists(self, key: str) -> bool:
        if key in self._store:
            _, expires_at = self._store[key]
            if time.time() < expires_at:
                return True
            del self._store[key]
        return False

    async def clear(self) -> None:
        self._store.clear()

    def cleanup_expired(self) -> int:
        """Remove all expired entries. Returns count of removed entries."""
        now = time.time()
        expired_keys = [k for k, (_, exp) in self._store.items() if now >= exp]
        for k in expired_keys:
            del self._store[k]
        return len(expired_keys)

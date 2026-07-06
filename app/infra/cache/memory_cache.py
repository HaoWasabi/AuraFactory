"""In-memory cache with TTL support."""

import logging
import time
from typing import Any, Dict, Optional, Tuple

from .base import CacheBase

logger = logging.getLogger(__name__)


class InMemoryCache(CacheBase):
    """Thread-safe in-memory cache with per-key TTL expiration."""

    def __init__(self, default_ttl: int = 300) -> None:
        """Initialize the cache.

        Args:
            default_ttl: Default time-to-live in seconds (default 5 minutes).
        """
        self._store: Dict[str, Tuple[Any, float]] = {}
        self._default_ttl = default_ttl

    def _is_expired(self, key: str) -> bool:
        """Check if a key has expired."""
        if key not in self._store:
            return True
        _, expiry = self._store[key]
        if expiry == 0:
            return False  # No expiry set
        return time.time() > expiry

    def _cleanup_key(self, key: str) -> None:
        """Remove a key if it has expired."""
        if self._is_expired(key):
            self._store.pop(key, None)

    async def get(self, key: str) -> Optional[Any]:
        """Retrieve a value by key. Returns None if not found or expired."""
        self._cleanup_key(key)
        if key in self._store:
            value, _ = self._store[key]
            return value
        return None

    async def set(self, key: str, value: Any, ttl: Optional[int] = None) -> None:
        """Store a value with an optional TTL in seconds."""
        effective_ttl = ttl if ttl is not None else self._default_ttl
        expiry = time.time() + effective_ttl if effective_ttl > 0 else 0
        self._store[key] = (value, expiry)

    async def delete(self, key: str) -> bool:
        """Delete a key. Returns True if the key existed."""
        if key in self._store:
            del self._store[key]
            return True
        return False

    async def exists(self, key: str) -> bool:
        """Check if a key exists and is not expired."""
        self._cleanup_key(key)
        return key in self._store

    async def clear(self) -> None:
        """Remove all entries from the cache."""
        self._store.clear()
        logger.debug("Cache cleared")

    @property
    def size(self) -> int:
        """Return the number of entries currently in the cache (including expired)."""
        return len(self._store)

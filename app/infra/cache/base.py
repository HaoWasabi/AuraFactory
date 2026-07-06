# app/infra/cache/base.py
"""
CacheBackend ABC.
Phase 1: In-memory dict. Phase 2: Redis.
"""
from abc import ABC, abstractmethod
from typing import Any, Optional


class CacheBackend(ABC):
    """Abstract interface for caching."""

    @abstractmethod
    async def get(self, key: str) -> Optional[Any]:
        """Get a value by key. Returns None if not found or expired."""
        ...

    @abstractmethod
    async def set(self, key: str, value: Any, ttl: int = 300) -> None:
        """Set a value with TTL (seconds)."""
        ...

    @abstractmethod
    async def delete(self, key: str) -> None:
        """Delete a key."""
        ...

    @abstractmethod
    async def exists(self, key: str) -> bool:
        """Check if key exists and is not expired."""
        ...

    @abstractmethod
    async def clear(self) -> None:
        """Clear all cached entries."""
        ...

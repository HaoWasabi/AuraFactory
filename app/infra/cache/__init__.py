# app/infra/cache/__init__.py
"""Cache infrastructure."""
from app.infra.cache.base import CacheBackend
from app.infra.cache.memory_cache import InMemoryCache

__all__ = ["CacheBackend", "InMemoryCache"]

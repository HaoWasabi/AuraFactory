"""Data layer — Repository pattern for all storage backends."""

from app.data.knowledge_store import KnowledgeStore
from app.data.redis_cache import RedisCache

__all__ = ["KnowledgeStore", "RedisCache"]

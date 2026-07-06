# app/infra/database/connection.py
"""
Async PostgreSQL connection pool.
Migrated from app/db/connection.py — wrapped in class-based pattern per spec.
Phase 2: Only change DATABASE_URL to point to RDS.
"""
import logging
from typing import Optional, List, Any
import asyncpg
logger = logging.getLogger(__name__)


class DatabasePool:
    """
    Async PostgreSQL connection pool wrapper.
    Provides typed query methods and lifecycle management.
    """

    def __init__(self, pool: asyncpg.Pool):
        self._pool = pool

    @classmethod
    async def create(
        cls,
        database_url: str,
        min_size: int = 2,
        max_size: int = 10,
        command_timeout: int = 30,
    ) -> "DatabasePool":
        """Create a new connection pool."""
        pool = await asyncpg.create_pool(
            dsn=database_url,
            min_size=min_size,
            max_size=max_size,
            command_timeout=command_timeout,
        )
        logger.info(f"Database pool created (min={min_size}, max={max_size})")
        return cls(pool)

    async def execute(self, query: str, *args: Any) -> str:
        """Execute a query and return status string."""
        async with self._pool.acquire() as conn:
            return await conn.execute(query, *args)

    async def fetch(self, query: str, *args: Any) -> List[dict]:
        """Fetch multiple rows as list of dicts."""
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(query, *args)
            return [dict(r) for r in rows]

    async def fetchrow(self, query: str, *args: Any) -> Optional[dict]:
        """Fetch a single row as dict."""
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(query, *args)
            return dict(row) if row else None

    async def fetchval(self, query: str, *args: Any) -> Any:
        """Fetch a single value."""
        async with self._pool.acquire() as conn:
            return await conn.fetchval(query, *args)

    async def executemany(self, query: str, args: List[tuple]) -> None:
        """Execute a query with multiple sets of arguments."""
        async with self._pool.acquire() as conn:
            await conn.executemany(query, args)

    async def close(self) -> None:
        """Close the connection pool."""
        await self._pool.close()
        logger.info("Database pool closed")

    @property
    def pool(self) -> asyncpg.Pool:
        """Direct access to the underlying pool (for advanced usage)."""
        return self._pool

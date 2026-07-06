"""Async database connection management using asyncpg."""

import logging
from typing import Any, List, Optional

import asyncpg

from .models import SCHEMA_SQL

logger = logging.getLogger(__name__)


class Database:
    """Async PostgreSQL database manager using asyncpg connection pool."""

    def __init__(self, dsn: str, min_size: int = 2, max_size: int = 10) -> None:
        self._dsn = dsn
        self._min_size = min_size
        self._max_size = max_size
        self._pool: Optional[asyncpg.Pool] = None

    @property
    def pool(self) -> asyncpg.Pool:
        """Return the connection pool, raising if not connected."""
        if self._pool is None:
            raise RuntimeError("Database not connected. Call connect() first.")
        return self._pool

    async def connect(self) -> None:
        """Establish the connection pool."""
        logger.info("Connecting to database...")
        self._pool = await asyncpg.create_pool(
            dsn=self._dsn,
            min_size=self._min_size,
            max_size=self._max_size,
        )
        logger.info("Database connection pool established (min=%d, max=%d)", self._min_size, self._max_size)

    async def disconnect(self) -> None:
        """Close the connection pool."""
        if self._pool is not None:
            await self._pool.close()
            self._pool = None
            logger.info("Database connection pool closed")

    async def execute(self, query: str, *args: Any) -> str:
        """Execute a query and return the status string."""
        async with self.pool.acquire() as conn:
            result = await conn.execute(query, *args)
            return result

    async def fetch(self, query: str, *args: Any) -> List[asyncpg.Record]:
        """Execute a query and return all rows."""
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(query, *args)
            return rows

    async def fetchrow(self, query: str, *args: Any) -> Optional[asyncpg.Record]:
        """Execute a query and return a single row."""
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(query, *args)
            return row

    async def init_schema(self) -> None:
        """Create all tables defined in the schema."""
        logger.info("Initializing database schema...")
        async with self.pool.acquire() as conn:
            await conn.execute(SCHEMA_SQL)
        logger.info("Database schema initialized successfully")

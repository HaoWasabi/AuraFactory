import asyncpg
import logging
import ssl
import os
from typing import Any, List, Optional
from contextlib import asynccontextmanager
from pathlib import Path

from .config import config

logger = logging.getLogger(__name__)


class Database:
    """Async database connection pool using asyncpg."""
    
    def __init__(self) -> None:
        self.pool: Optional[asyncpg.Pool] = None
    
    async def connect(self) -> None:
        """Create connection pool."""
        # Render free-tier PostgreSQL allows ~5 connections
        # Use SSL if DATABASE_URL contains render.com (external requires SSL)
        kwargs = {}
        db_url = config.DATABASE_URL
        if 'render.com' in db_url or 'onrender.com' in db_url:
            ssl_ctx = ssl.create_default_context()
            ssl_ctx.check_hostname = False
            ssl_ctx.verify_mode = ssl.CERT_NONE
            kwargs['ssl'] = ssl_ctx
        
        self.pool = await asyncpg.create_pool(
            db_url,
            min_size=2,
            max_size=5,
            **kwargs,
        )
    
    async def disconnect(self) -> None:
        """Close connection pool."""
        if self.pool:
            await self.pool.close()
            self.pool = None
    
    async def execute(self, query: str, *args: Any) -> str:
        """Execute query and return result as string."""
        if not self.pool:
            raise RuntimeError('Database not connected')
        async with self.pool.acquire() as conn:
            result = await conn.execute(query, *args)
            return str(result)
    
    async def fetch(self, query: str, *args: Any) -> List[asyncpg.Record]:
        """Fetch multiple rows."""
        if not self.pool:
            raise RuntimeError('Database not connected')
        async with self.pool.acquire() as conn:
            return await conn.fetch(query, *args)
    
    async def fetchrow(self, query: str, *args: Any) -> Optional[asyncpg.Record]:
        """Fetch single row."""
        if not self.pool:
            raise RuntimeError('Database not connected')
        async with self.pool.acquire() as conn:
            return await conn.fetchrow(query, *args)
    
    async def fetchval(self, query: str, *args: Any) -> Any:
        """Fetch single value."""
        if not self.pool:
            raise RuntimeError('Database not connected')
        async with self.pool.acquire() as conn:
            return await conn.fetchval(query, *args)
    
    @asynccontextmanager
    async def transaction(self):
        """Async context manager for transactions."""
        if not self.pool:
            raise RuntimeError('Database not connected')
        async with self.pool.acquire() as conn:
            async with conn.transaction():
                yield conn
    
    async def run_migrations(self, migrations_dir: str) -> None:
        """Read and execute all .sql migration files in order, tracking applied files."""
        if not self.pool:
            raise RuntimeError('Database not connected')

        migrations_path = Path(migrations_dir)
        if not migrations_path.exists():
            return

        # Create tracking table and fetch already-applied migrations
        async with self.pool.acquire() as conn:
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS schema_migrations (
                    filename TEXT PRIMARY KEY,
                    applied_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )
            """)
            applied_rows = await conn.fetch("SELECT filename FROM schema_migrations")
            applied = {r["filename"] for r in applied_rows}

        sql_files = sorted(migrations_path.glob('*.sql'))

        async with self.pool.acquire() as conn:
            for sql_file in sql_files:
                if sql_file.name in applied:
                    logger.info("Migration already applied, skipping: %s", sql_file.name)
                    continue
                sql = sql_file.read_text()
                try:
                    async with conn.transaction():
                        await conn.execute(sql)
                        await conn.execute(
                            "INSERT INTO schema_migrations (filename) VALUES ($1)",
                            sql_file.name
                        )
                    logger.info("Migration applied: %s", sql_file.name)
                except Exception as e:
                    logger.error("Migration FAILED: %s — %s", sql_file.name, e)
                    raise  # Stop migration sequence


# Global database instance
db = Database()

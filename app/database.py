import asyncpg
import ssl
import os
from typing import Any, List, Optional
from contextlib import asynccontextmanager
from pathlib import Path

from .config import config


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
        """Read and execute all .sql migration files in order."""
        if not self.pool:
            raise RuntimeError('Database not connected')
        
        migrations_path = Path(migrations_dir)
        if not migrations_path.exists():
            return
        
        sql_files = sorted(migrations_path.glob('*.sql'))
        
        async with self.pool.acquire() as conn:
            for sql_file in sql_files:
                with open(sql_file, 'r') as f:
                    migration_sql = f.read()
                await conn.execute(migration_sql)


# Global database instance
db = Database()

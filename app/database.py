import asyncpg
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
        self.pool = await asyncpg.create_pool(
            config.DATABASE_URL,
            min_size=10,
            max_size=20,
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

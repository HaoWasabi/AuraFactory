"""SQLite + FTS5 Knowledge Store — per-guild local knowledge base.

Provides:
  - Knowledge ingestion (rules, FAQs, pins, etc.)
  - Full-text search via FTS5
  - Conversation persistence and search
  - User preferences per guild
  - Guild data isolation (one DB per guild)
  - Deduplication by source_id

Design: Each guild gets its own SQLite database file for isolation.
FTS5 is used for fast, relevant text search without external dependencies.
"""

from __future__ import annotations

import asyncio
import logging
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class KnowledgeStore:
    """Per-guild SQLite + FTS5 knowledge store.

    Each guild has its own database file: {data_dir}/{guild_id}.db
    This ensures complete data isolation between guilds.
    """

    def __init__(self, data_dir: str | Path) -> None:
        self._data_dir = Path(data_dir)
        self._data_dir.mkdir(parents=True, exist_ok=True)
        self._connections: Dict[int, sqlite3.Connection] = {}

    def _get_db(self, guild_id: int) -> sqlite3.Connection:
        """Get or create a SQLite connection for a guild."""
        if guild_id not in self._connections:
            db_path = self._data_dir / f"{guild_id}.db"
            conn = sqlite3.connect(str(db_path))
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA foreign_keys=ON")
            self._init_schema(conn)
            self._connections[guild_id] = conn
        return self._connections[guild_id]

    def _init_schema(self, conn: sqlite3.Connection) -> None:
        """Initialize database schema with FTS5 tables."""
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS knowledge (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                category TEXT NOT NULL,
                source TEXT NOT NULL,
                source_id TEXT,
                title TEXT,
                content TEXT NOT NULL,
                priority INTEGER DEFAULT 5,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE UNIQUE INDEX IF NOT EXISTS idx_knowledge_source_id
                ON knowledge(source, source_id) WHERE source_id IS NOT NULL;

            CREATE VIRTUAL TABLE IF NOT EXISTS knowledge_fts USING fts5(
                title, content, category,
                content='knowledge',
                content_rowid='id'
            );

            -- Triggers to keep FTS in sync
            CREATE TRIGGER IF NOT EXISTS knowledge_ai AFTER INSERT ON knowledge BEGIN
                INSERT INTO knowledge_fts(rowid, title, content, category)
                VALUES (new.id, new.title, new.content, new.category);
            END;

            CREATE TRIGGER IF NOT EXISTS knowledge_ad AFTER DELETE ON knowledge BEGIN
                INSERT INTO knowledge_fts(knowledge_fts, rowid, title, content, category)
                VALUES ('delete', old.id, old.title, old.content, old.category);
            END;

            CREATE TRIGGER IF NOT EXISTS knowledge_au AFTER UPDATE ON knowledge BEGIN
                INSERT INTO knowledge_fts(knowledge_fts, rowid, title, content, category)
                VALUES ('delete', old.id, old.title, old.content, old.category);
                INSERT INTO knowledge_fts(rowid, title, content, category)
                VALUES (new.id, new.title, new.content, new.category);
            END;

            CREATE TABLE IF NOT EXISTS conversations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                user_id INTEGER NOT NULL,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                created_at TEXT NOT NULL
            );

            CREATE VIRTUAL TABLE IF NOT EXISTS conversations_fts USING fts5(
                content,
                content='conversations',
                content_rowid='id'
            );

            CREATE TRIGGER IF NOT EXISTS conv_ai AFTER INSERT ON conversations BEGIN
                INSERT INTO conversations_fts(rowid, content)
                VALUES (new.id, new.content);
            END;

            CREATE TABLE IF NOT EXISTS preferences (
                user_id INTEGER NOT NULL,
                key TEXT NOT NULL,
                value TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                PRIMARY KEY (user_id, key)
            );
        """)
        conn.commit()

    async def ingest_knowledge(
        self,
        guild_id: int,
        category: str,
        source: str,
        content: str,
        title: str = "",
        priority: int = 5,
        source_id: Optional[str] = None,
    ) -> int:
        """Ingest a knowledge entry. Upserts if source_id already exists.

        Returns:
            Row ID of the inserted/updated entry.
        """
        now = datetime.now(timezone.utc).isoformat()
        conn = self._get_db(guild_id)

        if source_id:
            # Upsert by source_id
            existing = conn.execute(
                "SELECT id FROM knowledge WHERE source = ? AND source_id = ?",
                (source, source_id),
            ).fetchone()

            if existing:
                conn.execute(
                    """UPDATE knowledge SET category=?, content=?, title=?, priority=?, updated_at=?
                       WHERE id=?""",
                    (category, content, title, priority, now, existing["id"]),
                )
                conn.commit()
                return existing["id"]

        cursor = conn.execute(
            """INSERT INTO knowledge (category, source, source_id, title, content, priority, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (category, source, source_id, title, content, priority, now, now),
        )
        conn.commit()
        return cursor.lastrowid

    async def search_knowledge(
        self,
        guild_id: int,
        query: str,
        category: Optional[str] = None,
        limit: int = 10,
    ) -> List[Dict[str, Any]]:
        """Search knowledge using FTS5.

        Returns list of matching entries ranked by relevance.
        """
        conn = self._get_db(guild_id)

        sql = """
            SELECT k.id, k.category, k.source, k.source_id, k.title, k.content,
                   k.priority, k.created_at, rank
            FROM knowledge_fts
            JOIN knowledge k ON k.id = knowledge_fts.rowid
            WHERE knowledge_fts MATCH ?
        """
        params: list = [query]

        if category:
            sql += " AND k.category = ?"
            params.append(category)

        sql += " ORDER BY rank LIMIT ?"
        params.append(limit)

        rows = conn.execute(sql, params).fetchall()
        return [dict(row) for row in rows]

    async def append_conversation(
        self,
        guild_id: int,
        session_id: str,
        user_id: int,
        role: str,
        content: str,
    ) -> None:
        """Append a message to conversation history."""
        now = datetime.now(timezone.utc).isoformat()
        conn = self._get_db(guild_id)
        conn.execute(
            """INSERT INTO conversations (session_id, user_id, role, content, created_at)
               VALUES (?, ?, ?, ?, ?)""",
            (session_id, user_id, role, content, now),
        )
        conn.commit()

    async def get_recent_conversations(
        self,
        guild_id: int,
        session_id: str,
        limit: int = 50,
    ) -> List[Dict[str, Any]]:
        """Get recent conversation messages for a session."""
        conn = self._get_db(guild_id)
        rows = conn.execute(
            """SELECT role, content, created_at FROM conversations
               WHERE session_id = ?
               ORDER BY id ASC
               LIMIT ?""",
            (session_id, limit),
        ).fetchall()
        return [dict(row) for row in rows]

    async def search_conversations(
        self,
        guild_id: int,
        query: str,
        limit: int = 10,
    ) -> List[Dict[str, Any]]:
        """Search conversation history using FTS5."""
        conn = self._get_db(guild_id)
        rows = conn.execute(
            """SELECT c.id, c.session_id, c.user_id, c.role, c.content, c.created_at, rank
               FROM conversations_fts
               JOIN conversations c ON c.id = conversations_fts.rowid
               WHERE conversations_fts MATCH ?
               ORDER BY rank
               LIMIT ?""",
            (query, limit),
        ).fetchall()
        return [dict(row) for row in rows]

    async def set_preference(
        self,
        guild_id: int,
        user_id: int,
        key: str,
        value: str,
    ) -> None:
        """Set a user preference (upserts)."""
        now = datetime.now(timezone.utc).isoformat()
        conn = self._get_db(guild_id)
        conn.execute(
            """INSERT INTO preferences (user_id, key, value, updated_at)
               VALUES (?, ?, ?, ?)
               ON CONFLICT(user_id, key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at""",
            (user_id, key, value, now),
        )
        conn.commit()

    async def get_preference(
        self,
        guild_id: int,
        user_id: int,
        key: str,
    ) -> Optional[str]:
        """Get a user preference value."""
        conn = self._get_db(guild_id)
        row = conn.execute(
            "SELECT value FROM preferences WHERE user_id = ? AND key = ?",
            (user_id, key),
        ).fetchone()
        return row["value"] if row else None

    async def delete_guild_data(self, guild_id: int) -> None:
        """Delete all data for a guild (removes the DB file)."""
        if guild_id in self._connections:
            self._connections[guild_id].close()
            del self._connections[guild_id]
        db_path = self._data_dir / f"{guild_id}.db"
        if db_path.exists():
            db_path.unlink()
            # Also remove WAL/SHM files if present
            for suffix in ("-wal", "-shm"):
                wal_path = db_path.with_suffix(db_path.suffix + suffix)
                if wal_path.exists():
                    wal_path.unlink()

    async def close(self) -> None:
        """Close all database connections."""
        for conn in self._connections.values():
            conn.close()
        self._connections.clear()

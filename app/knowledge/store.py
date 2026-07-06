"""ServerKnowledgeStore — Postgres-backed guild knowledge storage.

Stores guild snapshots as JSON and provides keyword search over
the stored data for context injection into LLM prompts.

Falls back to in-memory storage when no database is configured.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Optional

logger = logging.getLogger(__name__)

CREATE_TABLE_SQL: str = """
CREATE TABLE IF NOT EXISTS knowledge_store (
    guild_id    BIGINT PRIMARY KEY,
    snapshot    JSONB NOT NULL,
    summary     TEXT,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
"""


class ServerKnowledgeStore:
    """Postgres-backed knowledge store for guild snapshots.

    Stores complete guild structure as JSONB and provides keyword
    search plus formatted context strings for LLM injection.

    Falls back to in-memory dict when no db is provided.
    """

    def __init__(self, db: Any = None) -> None:
        """Initialize with optional database connection pool.

        Args:
            db: asyncpg connection pool instance (optional).
                If None, uses in-memory storage.
        """
        self._db = db
        # In-memory fallback when db is not available
        self._memory_store: dict[int, dict[str, Any]] = {}
        self._memory_summaries: dict[int, str] = {}
        logger.info("ServerKnowledgeStore initialized (db=%s)", "connected" if db else "in-memory")

    def set_db(self, db: Any) -> None:
        """Set database connection after initialization."""
        self._db = db

    async def ensure_table(self) -> None:
        """Create the knowledge_store table if it does not exist."""
        if self._db is None:
            return
        async with self._db.acquire() as conn:
            await conn.execute(CREATE_TABLE_SQL)
        logger.info("Ensured knowledge_store table exists")

    async def save_snapshot(self, guild_id: int, snapshot: dict[str, Any]) -> None:
        """Save or update a guild knowledge snapshot.

        Args:
            guild_id: Discord guild identifier.
            snapshot: Full guild knowledge dict (from GuildKnowledge.to_dict()).
        """
        summary = self._build_summary(snapshot)

        if self._db is None:
            # In-memory fallback
            self._memory_store[guild_id] = snapshot
            self._memory_summaries[guild_id] = summary
            logger.info("Saved knowledge snapshot in-memory for guild=%d", guild_id)
            return

        query = """
            INSERT INTO knowledge_store (guild_id, snapshot, summary, updated_at)
            VALUES ($1, $2::jsonb, $3, NOW())
            ON CONFLICT (guild_id) DO UPDATE SET
                snapshot = EXCLUDED.snapshot,
                summary = EXCLUDED.summary,
                updated_at = NOW()
        """
        async with self._db.acquire() as conn:
            await conn.execute(query, guild_id, json.dumps(snapshot), summary)
        logger.info("Saved knowledge snapshot for guild=%d", guild_id)

    async def get_snapshot(self, guild_id: int) -> dict[str, Any] | None:
        """Retrieve the stored snapshot for a guild.

        Args:
            guild_id: Discord guild identifier.

        Returns:
            Snapshot dict or None if not found.
        """
        if self._db is None:
            return self._memory_store.get(guild_id)

        query = "SELECT snapshot FROM knowledge_store WHERE guild_id = $1"
        async with self._db.acquire() as conn:
            row = await conn.fetchrow(query, guild_id)

        if row is None:
            return None

        snapshot = row["snapshot"]
        if isinstance(snapshot, str):
            return json.loads(snapshot)
        return snapshot

    async def load(self, guild_id: int) -> Optional[Any]:
        """Load guild knowledge — returns snapshot as namespace-like object.

        Args:
            guild_id: Discord guild identifier.

        Returns:
            Object with guild attributes or None.
        """
        snapshot = await self.get_snapshot(guild_id)
        if snapshot is None:
            return None

        # Return as a simple namespace for attribute access
        class _KnowledgeView:
            def __init__(self, data: dict):
                self.guild_name = data.get("guild_name", "Unknown")
                self.channels = data.get("channels", [])
                self.roles = data.get("roles", [])
                self.categories = data.get("categories", [])
                self.member_count = data.get("member_count", 0)
                self.rules = data.get("rules", [])
                self.setup_complete = data.get("setup_complete", False)
                self.last_crawled = data.get("crawled_at", None)

        return _KnowledgeView(snapshot)

    async def search(self, guild_id: int, query: str) -> list[dict[str, Any]]:
        """Keyword search over stored snapshot JSON.

        Searches channel names, role names, category names, and rules
        for keyword matches.

        Args:
            guild_id: Discord guild identifier.
            query: Search keyword(s).

        Returns:
            List of matching items with type and name/value.
        """
        snapshot = await self.get_snapshot(guild_id)
        if snapshot is None:
            return []

        query_lower = query.lower()
        results: list[dict[str, Any]] = []

        # Search channels
        for channel in snapshot.get("channels", []):
            name = channel.get("name", "")
            topic = channel.get("topic", "") or ""
            if query_lower in name.lower() or query_lower in topic.lower():
                results.append({"type": "channel", "data": channel})

        # Search roles
        for role in snapshot.get("roles", []):
            name = role.get("name", "")
            if query_lower in name.lower():
                results.append({"type": "role", "data": role})

        # Search categories
        for category in snapshot.get("categories", []):
            name = category.get("name", "")
            if query_lower in name.lower():
                results.append({"type": "category", "data": category})

        # Search rules
        for rule in snapshot.get("rules", []):
            if query_lower in rule.lower():
                results.append({"type": "rule", "data": {"text": rule}})

        logger.debug("Knowledge search guild=%d query='%s' found=%d", guild_id, query, len(results))
        return results

    async def get_summary_string(self, guild_id: int) -> str:
        """Get compact summary string (~200 tokens) for context injection.

        Args:
            guild_id: Discord guild identifier.

        Returns:
            Compact summary or 'No knowledge available' if not found.
        """
        if self._db is None:
            summary = self._memory_summaries.get(guild_id)
            return summary if summary else "No knowledge available for this guild."

        query = "SELECT summary FROM knowledge_store WHERE guild_id = $1"
        async with self._db.acquire() as conn:
            row = await conn.fetchrow(query, guild_id)

        if row is None or row["summary"] is None:
            return "No knowledge available for this guild."
        return row["summary"]

    async def get_context_string(self, guild_id: int) -> str:
        """Get full context dump for rich LLM context injection.

        Args:
            guild_id: Discord guild identifier.

        Returns:
            Detailed context string with all guild info.
        """
        snapshot = await self.get_snapshot(guild_id)
        if snapshot is None:
            return "No knowledge available for this guild."

        parts: list[str] = []
        parts.append(f"Guild: {snapshot.get('guild_name', 'Unknown')} (ID: {guild_id})")
        parts.append(f"Members: {snapshot.get('member_count', 0)}")

        # Categories
        categories = snapshot.get("categories", [])
        if categories:
            parts.append(f"\nCategories ({len(categories)}):")
            for cat in categories:
                parts.append(f"  - {cat.get('name', '?')}")

        # Channels
        channels = snapshot.get("channels", [])
        if channels:
            parts.append(f"\nChannels ({len(channels)}):")
            for ch in channels:
                topic_str = f" — {ch['topic']}" if ch.get("topic") else ""
                parts.append(f"  - #{ch.get('name', '?')} [{ch.get('type', '?')}]{topic_str}")

        # Roles
        roles = snapshot.get("roles", [])
        if roles:
            parts.append(f"\nRoles ({len(roles)}):")
            for role in roles:
                parts.append(f"  - @{role.get('name', '?')}")

        # Rules
        rules = snapshot.get("rules", [])
        if rules:
            parts.append(f"\nRules ({len(rules)}):")
            for i, rule in enumerate(rules, 1):
                parts.append(f"  {i}. {rule}")

        parts.append(f"\nCrawled at: {snapshot.get('crawled_at', 'unknown')}")
        return "\n".join(parts)

    @staticmethod
    def _build_summary(snapshot: dict[str, Any]) -> str:
        """Build a compact summary from snapshot data (~200 tokens).

        Args:
            snapshot: Full guild knowledge dict.

        Returns:
            Compact summary string.
        """
        guild_name = snapshot.get("guild_name", "Unknown")
        member_count = snapshot.get("member_count", 0)
        channels = snapshot.get("channels", [])
        roles = snapshot.get("roles", [])
        categories = snapshot.get("categories", [])
        rules = snapshot.get("rules", [])

        channel_names = [ch.get("name", "") for ch in channels[:10]]
        role_names = [r.get("name", "") for r in roles[:10]]

        parts = [
            f"Guild '{guild_name}' | {member_count} members",
            f"{len(channels)} channels: {', '.join(channel_names)}",
            f"{len(roles)} roles: {', '.join(role_names)}",
            f"{len(categories)} categories",
            f"{len(rules)} rules",
        ]
        return " | ".join(parts)

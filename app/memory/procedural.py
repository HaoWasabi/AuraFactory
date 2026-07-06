"""ProceduralMemory — rule-based conditional memory stored in Postgres.

Stores trigger→action pairs with confidence scores. Used for automated
responses, event-driven behaviors, and learned guild-specific rules.
"""

from __future__ import annotations

import json
import logging
import uuid
from typing import Any

logger = logging.getLogger(__name__)

CREATE_TABLE_SQL: str = """
CREATE TABLE IF NOT EXISTS procedural_memory (
    id          TEXT PRIMARY KEY,
    guild_id    BIGINT NOT NULL,
    trigger_condition JSONB NOT NULL,
    action      JSONB NOT NULL,
    confidence  REAL NOT NULL DEFAULT 1.0,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_procedural_memory_guild
    ON procedural_memory(guild_id);
"""


class ProceduralMemory:
    """Rule-based procedural memory backed by Postgres.

    Each rule has a trigger condition (JSON predicate) and an action
    (JSON spec) with a confidence score.
    """

    def __init__(self, db: Any) -> None:
        """Initialize with database connection pool.

        Args:
            db: asyncpg connection pool instance.
        """
        self._db = db
        logger.info("ProceduralMemory initialized")

    async def ensure_table(self) -> None:
        """Create the procedural_memory table if it does not exist."""
        async with self._db.acquire() as conn:
            await conn.execute(CREATE_TABLE_SQL)
        logger.info("Ensured procedural_memory table exists")

    async def add_rule(
        self,
        guild_id: int,
        trigger_condition: dict[str, Any],
        action: dict[str, Any],
        confidence: float = 1.0,
    ) -> str:
        """Add a new procedural rule.

        Args:
            guild_id: Discord guild identifier.
            trigger_condition: JSON-serializable trigger predicate.
            action: JSON-serializable action specification.
            confidence: Confidence score (0.0 to 1.0).

        Returns:
            Generated rule ID.
        """
        rule_id = str(uuid.uuid4())
        query = """
            INSERT INTO procedural_memory (id, guild_id, trigger_condition, action, confidence)
            VALUES ($1, $2, $3::jsonb, $4::jsonb, $5)
        """
        async with self._db.acquire() as conn:
            await conn.execute(
                query,
                rule_id,
                guild_id,
                json.dumps(trigger_condition),
                json.dumps(action),
                confidence,
            )
        logger.info("Added procedural rule %s for guild=%d", rule_id, guild_id)
        return rule_id

    async def get_rules(self, guild_id: int) -> list[dict[str, Any]]:
        """Get all procedural rules for a guild.

        Args:
            guild_id: Discord guild identifier.

        Returns:
            List of rule dicts with id, trigger_condition, action, confidence.
        """
        query = """
            SELECT id, guild_id, trigger_condition, action, confidence, created_at, updated_at
            FROM procedural_memory
            WHERE guild_id = $1
            ORDER BY confidence DESC, created_at DESC
        """
        async with self._db.acquire() as conn:
            rows = await conn.fetch(query, guild_id)

        rules: list[dict[str, Any]] = []
        for row in rows:
            rules.append(
                {
                    "id": row["id"],
                    "guild_id": row["guild_id"],
                    "trigger_condition": json.loads(row["trigger_condition"])
                    if isinstance(row["trigger_condition"], str)
                    else row["trigger_condition"],
                    "action": json.loads(row["action"])
                    if isinstance(row["action"], str)
                    else row["action"],
                    "confidence": row["confidence"],
                    "created_at": row["created_at"].isoformat(),
                    "updated_at": row["updated_at"].isoformat(),
                }
            )

        logger.debug("Retrieved %d rules for guild=%d", len(rules), guild_id)
        return rules

    async def match_trigger(self, guild_id: int, event: dict[str, Any]) -> list[dict[str, Any]]:
        """Find rules whose trigger conditions match the given event.

        Matching logic:
        - All keys in trigger_condition must be present in event
        - Values must match (supports string equality, list membership, wildcard '*')

        Args:
            guild_id: Discord guild identifier.
            event: Event dict to match against triggers.

        Returns:
            List of matching rule dicts, sorted by confidence descending.
        """
        all_rules = await self.get_rules(guild_id)
        matched: list[dict[str, Any]] = []

        for rule in all_rules:
            trigger = rule["trigger_condition"]
            if self._matches(trigger, event):
                matched.append(rule)

        matched.sort(key=lambda r: r["confidence"], reverse=True)
        logger.debug(
            "Matched %d/%d rules for guild=%d event=%s",
            len(matched),
            len(all_rules),
            guild_id,
            list(event.keys()),
        )
        return matched

    async def delete_rule(self, rule_id: str) -> bool:
        """Delete a procedural rule by ID.

        Args:
            rule_id: Unique rule identifier.

        Returns:
            True if deleted, False if not found.
        """
        query = "DELETE FROM procedural_memory WHERE id = $1"
        async with self._db.acquire() as conn:
            result = await conn.execute(query, rule_id)

        deleted = result.endswith("1")
        if deleted:
            logger.info("Deleted procedural rule %s", rule_id)
        else:
            logger.warning("Rule %s not found for deletion", rule_id)
        return deleted

    @staticmethod
    def _matches(trigger: dict[str, Any], event: dict[str, Any]) -> bool:
        """Check if trigger condition matches an event.

        Args:
            trigger: Trigger condition dict.
            event: Event to check against.

        Returns:
            True if all trigger conditions are satisfied.
        """
        for key, expected in trigger.items():
            if key not in event:
                return False

            actual = event[key]

            # Wildcard matches anything
            if expected == "*":
                continue

            # List membership check
            if isinstance(expected, list):
                if actual not in expected:
                    return False
            # Direct equality
            elif actual != expected:
                return False

        return True

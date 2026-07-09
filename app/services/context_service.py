"""ContextService — manages server_snapshots for providing real-time context."""
import logging
import time
from datetime import datetime, timezone
from typing import Optional

from app.database import Database
from app.mcp import MCPClient

logger = logging.getLogger(__name__)


class ContextService:
    """Provides and caches server context (categories, channels, roles) via server_snapshots."""

    TTL_SECONDS = 60

    def __init__(self, db: Database, mcp_client: MCPClient):
        self.db = db
        self.mcp_client = mcp_client
        self._memory_cache: dict[int, tuple[dict, float]] = {}
        # key=guild_id, value=(data_dict, expire_timestamp using time.monotonic())

    async def get_server_context(self, guild_id: int, force_refresh: bool = False) -> dict:
        """Get current server state. Uses cache if fresh (<60s), else refreshes.

        Returns dict with keys: categories (list), channels (list), roles (list),
        server_info (dict), automod_rules (list).
        All values are always native Python objects (never JSON strings).
        """
        if not force_refresh:
            # Check memory cache first
            entry = self._memory_cache.get(guild_id)
            if entry and entry[1] > time.monotonic():
                return entry[0]
            # Check DB cache
            cached = await self._get_cached(guild_id)
            if cached:
                self._memory_cache[guild_id] = (cached, time.monotonic() + self.TTL_SECONDS)
                return cached

        # Refresh from Discord via MCP tools
        raw = await self._fetch_from_discord(guild_id)

        # Upsert into server_snapshots (store as JSON strings for DB)
        await self.db.execute(
            """INSERT INTO server_snapshots (guild_id, categories, channels, roles, server_info, automod_rules, snapshot_at, stale_after)
               VALUES ($1, $2::jsonb, $3::jsonb, $4::jsonb, $5::jsonb, $6::jsonb, NOW(), NOW() + INTERVAL '60 seconds')
               ON CONFLICT (guild_id) DO UPDATE SET
                   categories = EXCLUDED.categories,
                   channels = EXCLUDED.channels,
                   roles = EXCLUDED.roles,
                   server_info = EXCLUDED.server_info,
                   automod_rules = EXCLUDED.automod_rules,
                   snapshot_at = NOW(),
                   stale_after = NOW() + INTERVAL '60 seconds'""",
            guild_id,
            raw.get("categories", "[]"),
            raw.get("channels", "[]"),
            raw.get("roles", "[]"),
            raw.get("server_info", "{}"),
            raw.get("automod_rules", "[]"),
        )

        # Deserialize to native objects before caching/returning
        context = self._deserialize(raw)
        self._memory_cache[guild_id] = (context, time.monotonic() + self.TTL_SECONDS)
        return context

    async def _get_cached(self, guild_id: int) -> Optional[dict]:
        """Return cached snapshot if still fresh, with all values as native Python objects."""
        row = await self.db.fetchrow(
            "SELECT * FROM server_snapshots WHERE guild_id = $1 AND stale_after > NOW()",
            guild_id,
        )
        if row:
            raw = {
                "categories": row["categories"],
                "channels": row["channels"],
                "roles": row["roles"],
                "server_info": row["server_info"],
                "automod_rules": row.get("automod_rules", []),
            }
            return self._deserialize(raw)
        return None

    @staticmethod
    def _deserialize(raw: dict) -> dict:
        """Ensure all context values are native Python objects (list/dict), not JSON strings."""
        import json

        def _parse(value, fallback):
            if isinstance(value, str):
                try:
                    return json.loads(value) if value.strip() else fallback
                except (json.JSONDecodeError, ValueError):
                    return fallback
            return value if value is not None else fallback

        return {
            "categories": _parse(raw.get("categories"), []),
            "channels": _parse(raw.get("channels"), []),
            "roles": _parse(raw.get("roles"), []),
            "server_info": _parse(raw.get("server_info"), {}),
            "automod_rules": _parse(raw.get("automod_rules"), []),
        }

    async def _fetch_from_discord(self, guild_id: int) -> dict:
        """Fetch live server state via MCP tools."""
        import json

        # Fetch each with error handling — partial failures shouldn't block
        categories = []
        channels = []
        roles = []
        server_info = {}

        try:
            resp = await self.mcp_client.call_tool("discord.categories.list", {"guild_id": guild_id})
            if resp.success and resp.result:
                categories = resp.result.get("categories", []) if isinstance(resp.result, dict) else resp.result
        except Exception as e:
            logger.warning("Failed to fetch categories for guild %d: %s", guild_id, e)

        try:
            resp = await self.mcp_client.call_tool("discord.channels.list", {"guild_id": guild_id})
            if resp.success and resp.result:
                channels = resp.result.get("channels", []) if isinstance(resp.result, dict) else resp.result
        except Exception as e:
            logger.warning("Failed to fetch channels for guild %d: %s", guild_id, e)

        try:
            resp = await self.mcp_client.call_tool("discord.roles.list", {"guild_id": guild_id})
            if resp.success and resp.result:
                roles = resp.result.get("roles", []) if isinstance(resp.result, dict) else resp.result
        except Exception as e:
            logger.warning("Failed to fetch roles for guild %d: %s", guild_id, e)

        try:
            resp = await self.mcp_client.call_tool("discord.guild.get_info", {"guild_id": guild_id})
            if resp.success and resp.result:
                server_info = resp.result
        except Exception as e:
            logger.warning("Failed to fetch guild info for guild %d: %s", guild_id, e)

        automod_rules = []
        try:
            resp = await self.mcp_client.call_tool("discord.automod.list_rules", {"guild_id": guild_id})
            if resp.success and resp.result:
                automod_rules = resp.result.get("rules", []) if isinstance(resp.result, dict) else []
        except Exception as e:
            logger.warning("Failed to fetch automod rules for guild %d: %s", guild_id, e)

        return {
            "categories": json.dumps(categories, default=str),
            "channels": json.dumps(channels, default=str),
            "roles": json.dumps(roles, default=str),
            "server_info": json.dumps(server_info, default=str),
            "automod_rules": json.dumps(automod_rules, default=str),
        }

    async def invalidate(self, guild_id: int) -> None:
        """Mark a snapshot as stale (force refresh on next access)."""
        self._memory_cache.pop(guild_id, None)
        await self.db.execute(
            "UPDATE server_snapshots SET stale_after = NOW() WHERE guild_id = $1",
            guild_id,
        )

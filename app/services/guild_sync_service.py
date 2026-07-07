"""GuildSyncService — syncs guild_admin_cache and manages bot_installs."""
import logging
from typing import List
import aiohttp

from app.config import settings
from app.database import Database

logger = logging.getLogger(__name__)

DISCORD_API = "https://discord.com/api/v10"


class GuildSyncService:
    """Syncs user's admin guilds and bot installation status."""

    def __init__(self, db: Database):
        self.db = db

    async def sync_user_guilds(self, user_id: int, access_token: str) -> List[dict]:
        """Fetch user's guilds from Discord and update guild_admin_cache.

        Returns list of guilds where user is admin/owner, each annotated with bot_installed status.
        """
        # Fetch guilds from Discord
        async with aiohttp.ClientSession() as session:
            headers = {"Authorization": f"Bearer {access_token}"}
            async with session.get(f"{DISCORD_API}/users/@me/guilds", headers=headers) as resp:
                if resp.status != 200:
                    body = await resp.text()
                    logger.error("Failed to fetch guilds for user %d: status=%s body=%s", user_id, resp.status, body[:200])
                    return []
                all_guilds = await resp.json()

        logger.info("Discord returned %d guilds for user %d", len(all_guilds), user_id)

        # Filter guilds where user has Administrator or Manage Server
        admin_guilds = []
        for guild in all_guilds:
            # Discord may return permissions as string or int
            raw_perms = guild.get("permissions", guild.get("permissions_new", "0"))
            try:
                perms = int(raw_perms) if raw_perms else 0
            except (ValueError, TypeError):
                perms = 0
            is_admin = bool(perms & 0x8) or bool(perms & 0x20)  # ADMINISTRATOR | MANAGE_GUILD
            is_owner = guild.get("owner", False)
            # Also check if owner_id field matches (some API versions include this)
            owner_id_match = (int(guild.get("owner_id", 0)) == user_id) if guild.get("owner_id") else False
            if is_admin or is_owner or owner_id_match:
                admin_guilds.append({
                    "guild_id": int(guild["id"]),
                    "guild_name": guild.get("name", ""),
                    "is_owner": is_owner or owner_id_match,
                    "permissions_bitfield": perms,
                    "icon": guild.get("icon", ""),
                })

        logger.info("Filtered %d admin/owner guilds for user %d (total fetched: %d)",
                    len(admin_guilds), user_id, len(all_guilds))

        # Upsert into guild_admin_cache
        for g in admin_guilds:
            await self.db.execute(
                """INSERT INTO guild_admin_cache (user_id, guild_id, guild_name, is_owner, permissions_bitfield, cached_at)
                   VALUES ($1, $2, $3, $4, $5, NOW())
                   ON CONFLICT (user_id, guild_id) DO UPDATE SET
                       guild_name = EXCLUDED.guild_name,
                       is_owner = EXCLUDED.is_owner,
                       permissions_bitfield = EXCLUDED.permissions_bitfield,
                       cached_at = NOW()""",
                user_id, g["guild_id"], g["guild_name"], g["is_owner"], g["permissions_bitfield"],
            )

        # Check bot installation status for each guild
        result = []
        for g in admin_guilds:
            bot_row = await self.db.fetchrow(
                "SELECT is_active FROM bot_installs WHERE guild_id = $1",
                g["guild_id"],
            )
            g["bot_installed"] = bool(bot_row and bot_row["is_active"])
            result.append(g)

        logger.info("Synced %d admin guilds for user %d", len(result), user_id)
        return result

    async def register_bot_install(self, guild_id: int, installed_by: int) -> None:
        """Record that bot was installed in a guild (on guild_create event)."""
        await self.db.execute(
            """INSERT INTO bot_installs (guild_id, installed_by, installed_at, is_active)
               VALUES ($1, $2, NOW(), TRUE)
               ON CONFLICT (guild_id) DO UPDATE SET
                   is_active = TRUE,
                   installed_by = EXCLUDED.installed_by,
                   installed_at = NOW()""",
            guild_id, installed_by,
        )
        logger.info("Registered bot install for guild %d by user %d", guild_id, installed_by)

    async def unregister_bot_install(self, guild_id: int) -> None:
        """Mark bot as removed from guild (on guild_delete event)."""
        await self.db.execute(
            "UPDATE bot_installs SET is_active = FALSE WHERE guild_id = $1",
            guild_id,
        )
        logger.info("Bot removed from guild %d", guild_id)

    async def get_user_guilds(self, user_id: int) -> List[dict]:
        """Get cached guild list for a user (from guild_admin_cache + bot_installs join)."""
        rows = await self.db.fetch(
            """SELECT g.guild_id, g.guild_name, g.is_owner, g.permissions_bitfield,
                      COALESCE(b.is_active, FALSE) as bot_installed
               FROM guild_admin_cache g
               LEFT JOIN bot_installs b ON g.guild_id = b.guild_id
               WHERE g.user_id = $1
               ORDER BY g.guild_name""",
            user_id,
        )
        return [dict(r) for r in rows]

    def get_bot_invite_url(self, guild_id: int) -> str:
        """Generate bot invite URL for a specific guild."""
        # Bot permissions: Administrator for full functionality
        permissions = 8  # ADMINISTRATOR
        return (
            f"https://discord.com/oauth2/authorize"
            f"?client_id={settings.discord_client_id}"
            f"&permissions={permissions}"
            f"&scope=bot"
            f"&guild_id={guild_id}"
        )

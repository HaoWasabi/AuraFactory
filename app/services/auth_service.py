"""AuthService — handles Discord OAuth2 login flow."""
import logging
from datetime import datetime, timezone, timedelta
from typing import Optional
from urllib.parse import urlencode
import aiohttp

from app.config import settings
from app.database import Database

logger = logging.getLogger(__name__)

DISCORD_API = "https://discord.com/api/v10"
DISCORD_OAUTH_TOKEN_URL = "https://discord.com/api/oauth2/token"


class AuthService:
    """Handles Discord OAuth2 authentication."""

    def __init__(self, db: Database):
        self.db = db

    def get_oauth_url(self, state: str) -> str:
        """Generate Discord OAuth2 authorization URL.
        Scopes: identify, guilds
        """
        params = {
            "client_id": settings.DISCORD_CLIENT_ID,
            "redirect_uri": settings.DISCORD_REDIRECT_URI,
            "response_type": "code",
            "scope": "identify guilds",
            "state": state,
        }
        query = urlencode(params)
        return f"https://discord.com/oauth2/authorize?{query}"

    async def exchange_code(self, code: str) -> Optional[dict]:
        """Exchange OAuth2 code for tokens. Returns user info dict or None on failure."""
        async with aiohttp.ClientSession() as session:
            # Exchange code for token
            token_data = {
                "client_id": settings.DISCORD_CLIENT_ID,
                "client_secret": settings.DISCORD_CLIENT_SECRET,
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": settings.DISCORD_REDIRECT_URI,
            }
            async with session.post(DISCORD_OAUTH_TOKEN_URL, data=token_data) as resp:
                if resp.status != 200:
                    logger.error("OAuth token exchange failed: %s", await resp.text())
                    return None
                tokens = await resp.json()

            access_token = tokens["access_token"]
            refresh_token = tokens.get("refresh_token", "")
            expires_in = tokens.get("expires_in", 604800)

            # Get user info
            headers = {"Authorization": f"Bearer {access_token}"}
            async with session.get(f"{DISCORD_API}/users/@me", headers=headers) as resp:
                if resp.status != 200:
                    return None
                user_info = await resp.json()

            # Upsert user in DB
            discord_user_id = int(user_info["id"])
            username = user_info.get("username", "")
            avatar = user_info.get("avatar", "")
            expires_at = datetime.now(timezone.utc) + timedelta(seconds=expires_in)

            # If DB not available, return user info without persisting
            if self.db is None:
                logger.warning("DB unavailable — returning user info without persisting")
                return {"discord_user_id": discord_user_id, "username": username, "avatar": avatar, "access_token": access_token}

            await self.db.execute(
                """INSERT INTO users (discord_user_id, username, avatar_hash, access_token_enc, refresh_token_enc, token_expires_at, last_login_at)
                   VALUES ($1, $2, $3, $4, $5, $6, NOW())
                   ON CONFLICT (discord_user_id) DO UPDATE SET
                       username = EXCLUDED.username,
                       avatar_hash = EXCLUDED.avatar_hash,
                       access_token_enc = EXCLUDED.access_token_enc,
                       refresh_token_enc = EXCLUDED.refresh_token_enc,
                       token_expires_at = EXCLUDED.token_expires_at,
                       last_login_at = NOW()""",
                discord_user_id, username, avatar, access_token, refresh_token, expires_at,
            )

            return {
                "discord_user_id": discord_user_id,
                "username": username,
                "avatar": avatar,
                "access_token": access_token,
            }

    async def get_user_token(self, user_id: int) -> Optional[str]:
        """Get stored access token for a user. Returns None if not found or expired."""
        row = await self.db.fetchrow(
            "SELECT access_token_enc, token_expires_at FROM users WHERE discord_user_id = $1",
            user_id,
        )
        if not row:
            return None
        expires_at = row["token_expires_at"]
        if expires_at and expires_at <= datetime.now(timezone.utc):
            logger.warning(
                "Access token for user %d has expired (expired at %s)",
                user_id,
                expires_at,
            )
            return None
        return row["access_token_enc"]

    async def refresh_user_permissions(self, user_id: int, guild_id: int) -> bool:
        """Refresh user's permissions for a specific guild via Discord API.
        Used before HIGH/CRITICAL actions (§5.6 step 17).
        Returns True if user still has admin/manage_server permission.
        """
        token = await self.get_user_token(user_id)
        if not token:
            return False

        async with aiohttp.ClientSession() as session:
            headers = {"Authorization": f"Bearer {token}"}
            async with session.get(f"{DISCORD_API}/users/@me/guilds", headers=headers) as resp:
                if resp.status != 200:
                    logger.warning("Failed to refresh guilds for user %d", user_id)
                    return False
                guilds = await resp.json()

        for guild in guilds:
            if int(guild["id"]) == guild_id:
                perms = int(guild.get("permissions", 0))
                # Check ADMINISTRATOR (0x8) or MANAGE_GUILD (0x20)
                has_admin = bool(perms & 0x8) or bool(perms & 0x20)
                # Update cache
                await self.db.execute(
                    """INSERT INTO guild_admin_cache (user_id, guild_id, guild_name, is_owner, permissions_bitfield, cached_at)
                       VALUES ($1, $2, $3, $4, $5, NOW())
                       ON CONFLICT (user_id, guild_id) DO UPDATE SET
                           permissions_bitfield = EXCLUDED.permissions_bitfield,
                           is_owner = EXCLUDED.is_owner,
                           cached_at = NOW()""",
                    user_id, guild_id, guild.get("name", ""),
                    guild.get("owner", False), perms,
                )
                return has_admin
        return False

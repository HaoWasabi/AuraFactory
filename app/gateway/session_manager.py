# app/gateway/session_manager.py
"""
Session Manager — handles session lifecycle + user role detection.
- resolve_session: create new or load existing (Postgres + cache).
- detect_user_role: determine user permission level from guild context.
- Session TTL: 24 hours.
"""
import time
import logging
from typing import Optional, Dict, Any
from dataclasses import dataclass, field
from uuid import uuid4

logger = logging.getLogger(__name__)

# Session timeout: 24 hours
SESSION_TTL_SECONDS: int = 86400


@dataclass
class Session:
    """Represents an active user session."""
    session_id: str
    user_id: str
    guild_id: Optional[int]
    channel_id: Optional[int]
    user_role: str = "member"
    created_at: float = field(default_factory=time.time)
    last_active: float = field(default_factory=time.time)
    metadata: Dict[str, Any] = field(default_factory=dict)

    @property
    def is_expired(self) -> bool:
        """Check if session has exceeded TTL."""
        return (time.time() - self.last_active) > SESSION_TTL_SECONDS

    def touch(self) -> None:
        """Update last_active timestamp."""
        self.last_active = time.time()


class SessionManager:
    """
    Manages user sessions with Postgres persistence + in-memory cache.

    Phase 1: In-memory cache serves as primary store.
    Phase 2: Postgres `sessions` table as primary, cache for fast lookup.

    Responsibilities:
    - resolve_session: get or create session for user+guild pair.
    - detect_user_role: inspect guild to determine user permission level.
    """

    def __init__(self, db: Any = None, cache: Optional[Dict[str, Session]] = None) -> None:
        self._db = db  # Postgres connection pool (Phase 2)
        self._cache: Dict[str, Session] = cache if cache is not None else {}

    async def resolve_session(
        self,
        user_id: str,
        guild_id: Optional[int] = None,
        channel_id: Optional[int] = None,
    ) -> Session:
        """
        Get existing session or create a new one.

        Lookup order:
        1. In-memory cache (fast path)
        2. Postgres `sessions` table (Phase 2)
        3. Create new session

        Returns:
            Active Session object.
        """
        cache_key = self._make_key(user_id, guild_id)

        # Check cache first
        if cache_key in self._cache:
            session = self._cache[cache_key]
            if session.is_expired:
                logger.info(
                    f"Session expired: {session.session_id} "
                    f"(user={user_id}, idle={time.time() - session.last_active:.0f}s)"
                )
                del self._cache[cache_key]
                await self._delete_from_db(session.session_id)
            else:
                session.touch()
                return session

        # Phase 2: Check Postgres
        if self._db:
            session = await self._load_from_db(user_id, guild_id)
            if session and not session.is_expired:
                session.touch()
                self._cache[cache_key] = session
                return session

        # Create new session
        session = Session(
            session_id=str(uuid4())[:12],
            user_id=user_id,
            guild_id=guild_id,
            channel_id=channel_id,
        )
        self._cache[cache_key] = session
        await self._persist_to_db(session)

        logger.info(
            f"New session created: {session.session_id} "
            f"(user={user_id}, guild={guild_id})"
        )
        return session

    def detect_user_role(self, user_id: str, guild: Any) -> str:
        """
        Determine user's effective role in the guild.

        Priority levels:
        - owner: guild.owner_id matches user_id
        - admin: user has administrator permission
        - moderator: user has manage_channels or manage_roles permission
        - member: default (no elevated permissions)

        Args:
            user_id: The Discord user ID to check.
            guild: The Discord guild object (discord.py Guild).

        Returns:
            Role string: "owner" | "admin" | "moderator" | "member"
        """
        if guild is None:
            return "member"

        # Check owner
        if hasattr(guild, "owner_id"):
            if str(guild.owner_id) == str(user_id):
                return "owner"

        # Find the member in guild
        member = None
        if hasattr(guild, "get_member"):
            member = guild.get_member(int(user_id)) if user_id.isdigit() else None

        if member is None:
            return "member"

        # Check guild_permissions on the member
        if hasattr(member, "guild_permissions"):
            perms = member.guild_permissions

            # Administrator permission
            if hasattr(perms, "administrator") and perms.administrator:
                return "admin"

            # Moderator permissions
            has_manage_channels = hasattr(perms, "manage_channels") and perms.manage_channels
            has_manage_roles = hasattr(perms, "manage_roles") and perms.manage_roles
            if has_manage_channels or has_manage_roles:
                return "moderator"

        return "member"

    async def end_session(self, session_id: str) -> None:
        """Explicitly end a session."""
        keys_to_remove = [
            k for k, v in self._cache.items() if v.session_id == session_id
        ]
        for key in keys_to_remove:
            del self._cache[key]
        await self._delete_from_db(session_id)
        logger.info(f"Session ended: {session_id}")

    async def cleanup_expired(self) -> int:
        """
        Remove all expired sessions from cache.
        Call periodically (e.g., every 30 minutes).

        Returns:
            Count of removed sessions.
        """
        now = time.time()
        expired_keys = [
            k for k, session in self._cache.items()
            if (now - session.last_active) > SESSION_TTL_SECONDS
        ]
        for key in expired_keys:
            session = self._cache.pop(key)
            await self._delete_from_db(session.session_id)

        if expired_keys:
            logger.info(f"Cleaned up {len(expired_keys)} expired sessions")
        return len(expired_keys)

    # ============================================================
    # DATABASE OPERATIONS (Phase 2 — Postgres `sessions` table)
    # ============================================================

    async def _persist_to_db(self, session: Session) -> None:
        """Persist session to Postgres. No-op if db not configured."""
        if not self._db:
            return
        try:
            await self._db.execute(
                """
                INSERT INTO sessions (session_id, user_id, guild_id, channel_id, user_role, created_at, last_active)
                VALUES ($1, $2, $3, $4, $5, to_timestamp($6), to_timestamp($7))
                ON CONFLICT (session_id) DO UPDATE SET last_active = to_timestamp($7)
                """,
                session.session_id, session.user_id, session.guild_id,
                session.channel_id, session.user_role,
                session.created_at, session.last_active,
            )
        except Exception as e:
            logger.error(f"Failed to persist session {session.session_id}: {e}")

    async def _load_from_db(self, user_id: str, guild_id: Optional[int]) -> Optional[Session]:
        """Load session from Postgres. Returns None if not found or db not configured."""
        if not self._db:
            return None
        try:
            row = await self._db.fetchrow(
                """
                SELECT session_id, user_id, guild_id, channel_id, user_role,
                       EXTRACT(EPOCH FROM created_at) as created_at,
                       EXTRACT(EPOCH FROM last_active) as last_active
                FROM sessions
                WHERE user_id = $1 AND guild_id = $2
                ORDER BY last_active DESC
                LIMIT 1
                """,
                user_id, guild_id,
            )
            if row:
                return Session(
                    session_id=row["session_id"],
                    user_id=row["user_id"],
                    guild_id=row["guild_id"],
                    channel_id=row["channel_id"],
                    user_role=row["user_role"],
                    created_at=row["created_at"],
                    last_active=row["last_active"],
                )
        except Exception as e:
            logger.error(f"Failed to load session from DB: {e}")
        return None

    async def _delete_from_db(self, session_id: str) -> None:
        """Delete session from Postgres. No-op if db not configured."""
        if not self._db:
            return
        try:
            await self._db.execute(
                "DELETE FROM sessions WHERE session_id = $1",
                session_id,
            )
        except Exception as e:
            logger.error(f"Failed to delete session {session_id} from DB: {e}")

    # ============================================================
    # HELPERS
    # ============================================================

    def _make_key(self, user_id: str, guild_id: Optional[int]) -> str:
        """Create unique cache key for user+guild combination."""
        if guild_id:
            return f"{guild_id}:{user_id}"
        return f"dm:{user_id}"

    @property
    def active_count(self) -> int:
        """Number of active sessions in cache."""
        return len(self._cache)

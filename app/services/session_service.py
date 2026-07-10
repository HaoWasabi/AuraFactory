"""SessionService — manages chat sessions and conversation memory."""
import logging
import uuid
from datetime import datetime, timezone
from typing import Optional

from app.database import Database

logger = logging.getLogger(__name__)

# Number of recent messages to include as history context
HISTORY_WINDOW = 10
# Session TTL in minutes for Discord threads (idle sessions)
SESSION_TTL_MINUTES = 60


class SessionService:
    """Creates and manages chat sessions with persistent message history.

    Each session corresponds to one conversation thread:
    - Web: one session per chat window (created on first message after guild select)
    - Discord: one session per bot reply-thread (created when bot opens a thread)

    Messages are stored in the `messages` table linked to a session_id.
    History is read from messages (not the sessions.history JSONB) so it is
    always authoritative and never out of sync.
    """

    def __init__(self, db: Database) -> None:
        self.db = db

    # ------------------------------------------------------------------
    # Session lifecycle
    # ------------------------------------------------------------------

    async def get_or_create_session(
        self,
        guild_id: int,
        user_id: int,
        origin: str = "discord",
        discord_thread_id: Optional[int] = None,
        title: Optional[str] = None,
    ) -> str:
        """Get active session or create a new one.

        For Discord: if discord_thread_id is supplied, look up by thread ID first.
        For Web: always create a new session (caller controls lifecycle).
        Returns session_id as string.
        """
        # Discord: look up by thread ID (thread = session boundary)
        if discord_thread_id:
            row = await self.db.fetchrow(
                "SELECT id FROM sessions WHERE discord_thread_id = $1",
                discord_thread_id,
            )
            if row:
                session_id = str(row["id"])
                await self._touch_session(session_id)
                return session_id

        # Create a new session
        return await self.create_session(
            guild_id=guild_id,
            user_id=user_id,
            origin=origin,
            discord_thread_id=discord_thread_id,
            title=title,
        )

    async def create_session(
        self,
        guild_id: int,
        user_id: int,
        origin: str = "discord",
        discord_thread_id: Optional[int] = None,
        title: Optional[str] = None,
    ) -> str:
        """Create a fresh session and return its ID."""
        session_id = uuid.uuid4()
        now = datetime.now(timezone.utc)
        auto_title = title or f"Chat {now.strftime('%d/%m %H:%M')}"

        await self.db.execute(
            """INSERT INTO sessions
               (id, guild_id, user_id, user_role, history, title,
                discord_thread_id, is_active, created_at, last_active_at)
               VALUES ($1, $2, $3, 'member', '[]'::jsonb, $4, $5, TRUE, $6, $6)""",
            session_id,
            guild_id,
            user_id,
            auto_title,
            discord_thread_id,
            now,
        )
        logger.info(
            "Created session %s (guild=%d user=%d origin=%s thread=%s)",
            session_id, guild_id, user_id, origin, discord_thread_id,
        )
        return str(session_id)

    async def update_thread_id(self, session_id: str, thread_id: int) -> None:
        """Bind a Discord thread ID to an existing session."""
        await self.db.execute(
            "UPDATE sessions SET discord_thread_id = $2 WHERE id = $1",
            uuid.UUID(session_id),
            thread_id,
        )

    async def close_session(self, session_id: str) -> None:
        """Mark a session as inactive (soft-close)."""
        await self.db.execute(
            "UPDATE sessions SET is_active = FALSE WHERE id = $1",
            uuid.UUID(session_id),
        )

    # ------------------------------------------------------------------
    # Message storage
    # ------------------------------------------------------------------

    async def add_message(
        self,
        session_id: str,
        guild_id: int,
        user_id: int,
        role: str,
        content: str,
        origin: str = "discord",
    ) -> str:
        """Persist a single message and update session last_active_at.

        role: 'user' | 'bot'
        Returns message ID as string.
        """
        msg_id = uuid.uuid4()
        await self.db.execute(
            """INSERT INTO messages
               (id, session_id, guild_id, user_id, origin, role, content, created_at)
               VALUES ($1, $2, $3, $4, $5, $6, $7, NOW())""",
            msg_id,
            uuid.UUID(session_id),
            guild_id,
            user_id,
            origin,
            role,
            content,
        )
        await self._touch_session(session_id)
        return str(msg_id)

    # ------------------------------------------------------------------
    # History retrieval
    # ------------------------------------------------------------------

    async def get_history(
        self,
        session_id: str,
        limit: int = HISTORY_WINDOW,
    ) -> list[dict]:
        """Return the last `limit` messages in chronological order.

        Each item: {"role": "user"|"bot", "content": "..."}
        Compatible with the format expected by PlannerService / QueryService.
        """
        rows = await self.db.fetch(
            """SELECT role, content FROM messages
               WHERE session_id = $1
               ORDER BY created_at DESC
               LIMIT $2""",
            uuid.UUID(session_id),
            limit,
        )
        # Reverse so oldest first (chronological)
        return [{"role": r["role"], "content": r["content"]} for r in reversed(rows)]

    async def get_session_messages(
        self,
        session_id: str,
        limit: int = 100,
        before_id: Optional[str] = None,
    ) -> list[dict]:
        """Return full message list for display (with timestamps).

        Supports cursor-based pagination via before_id.
        """
        if before_id:
            rows = await self.db.fetch(
                """SELECT id, role, content, created_at FROM messages
                   WHERE session_id = $1
                     AND created_at < (SELECT created_at FROM messages WHERE id = $2)
                   ORDER BY created_at DESC
                   LIMIT $3""",
                uuid.UUID(session_id),
                uuid.UUID(before_id),
                limit,
            )
        else:
            rows = await self.db.fetch(
                """SELECT id, role, content, created_at FROM messages
                   WHERE session_id = $1
                   ORDER BY created_at DESC
                   LIMIT $2""",
                uuid.UUID(session_id),
                limit,
            )
        return [
            {
                "id": str(r["id"]),
                "role": r["role"],
                "content": r["content"],
                "created_at": r["created_at"].isoformat(),
            }
            for r in reversed(rows)
        ]

    # ------------------------------------------------------------------
    # Session listing (for sidebar)
    # ------------------------------------------------------------------

    async def list_sessions(
        self,
        guild_id: int,
        user_id: int,
        limit: int = 30,
    ) -> list[dict]:
        """List recent sessions for a user in a guild (newest first).

        Returns summary info for sidebar display.
        """
        rows = await self.db.fetch(
            """SELECT s.id, s.title, s.created_at, s.last_active_at,
                      s.discord_thread_id, s.is_active,
                      (SELECT content FROM messages m
                       WHERE m.session_id = s.id
                       ORDER BY m.created_at DESC LIMIT 1) AS last_message
               FROM sessions s
               WHERE s.guild_id = $1 AND s.user_id = $2
               ORDER BY s.last_active_at DESC
               LIMIT $3""",
            guild_id,
            user_id,
            limit,
        )
        return [
            {
                "id": str(r["id"]),
                "title": r["title"] or f"Chat {r['created_at'].strftime('%d/%m %H:%M')}",
                "created_at": r["created_at"].isoformat(),
                "last_active_at": r["last_active_at"].isoformat(),
                "discord_thread_id": str(r["discord_thread_id"]) if r["discord_thread_id"] else None,
                "is_active": r["is_active"],
                "last_message": (r["last_message"] or "")[:80],
            }
            for r in rows
        ]

    async def get_session(self, session_id: str) -> Optional[dict]:
        """Fetch session metadata by ID."""
        row = await self.db.fetchrow(
            "SELECT id, guild_id, user_id, title, discord_thread_id, is_active, created_at, last_active_at FROM sessions WHERE id = $1",
            uuid.UUID(session_id),
        )
        if not row:
            return None
        return {
            "id": str(row["id"]),
            "guild_id": row["guild_id"],
            "user_id": row["user_id"],
            "title": row["title"],
            "discord_thread_id": str(row["discord_thread_id"]) if row["discord_thread_id"] else None,
            "is_active": row["is_active"],
            "created_at": row["created_at"].isoformat(),
            "last_active_at": row["last_active_at"].isoformat(),
        }

    async def rename_session(self, session_id: str, title: str) -> None:
        """Rename a session (user-editable title)."""
        await self.db.execute(
            "UPDATE sessions SET title = $2 WHERE id = $1",
            uuid.UUID(session_id),
            title[:100],
        )

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    async def _touch_session(self, session_id: str) -> None:
        """Update last_active_at timestamp."""
        await self.db.execute(
            "UPDATE sessions SET last_active_at = NOW() WHERE id = $1",
            uuid.UUID(session_id),
        )

# app/gateway/session_manager.py
"""
Session Manager — handles session lifecycle (create, resolve, expire).
Phase 1: In-memory sessions. Phase 2: Redis-backed with TTL.
"""
import time
import logging
from typing import Optional, Dict
from uuid import uuid4

logger = logging.getLogger(__name__)

# Session timeout: 30 minutes of inactivity
SESSION_TIMEOUT_SECONDS = 1800


class SessionManager:
    """Manages user conversation sessions."""

    def __init__(self, timeout: int = SESSION_TIMEOUT_SECONDS):
        self._timeout = timeout
        self._sessions: Dict[str, dict] = {}  # session_key → session_data

    async def get_or_create_session(
        self,
        user_id: str,
        guild_id: Optional[int] = None,
        channel_id: Optional[int] = None,
    ) -> str:
        """Get existing session or create new one. Returns session_id."""
        session_key = self._make_key(user_id, guild_id)

        if session_key in self._sessions:
            session = self._sessions[session_key]
            # Check if expired
            if time.time() - session["last_active"] > self._timeout:
                # Session expired — clean up and create new
                old_id = session["id"]
                logger.info(f"Session expired: {old_id}")
                del self._sessions[session_key]
            else:
                # Active session — update last_active
                session["last_active"] = time.time()
                return session["id"]

        # Create new session
        session_id = str(uuid4())[:8]
        self._sessions[session_key] = {
            "id": session_id,
            "user_id": user_id,
            "guild_id": guild_id,
            "channel_id": channel_id,
            "created_at": time.time(),
            "last_active": time.time(),
        }
        logger.info(f"New session created: {session_id} for user {user_id}")
        return session_id

    async def end_session(self, session_id: str) -> None:
        """Explicitly end a session."""
        keys_to_remove = [
            k for k, v in self._sessions.items() if v["id"] == session_id
        ]
        for k in keys_to_remove:
            del self._sessions[k]

    async def cleanup_expired(self) -> int:
        """Remove all expired sessions. Returns count removed."""
        now = time.time()
        expired = [
            k for k, v in self._sessions.items()
            if now - v["last_active"] > self._timeout
        ]
        for k in expired:
            del self._sessions[k]
        if expired:
            logger.info(f"Cleaned up {len(expired)} expired sessions")
        return len(expired)

    def _make_key(self, user_id: str, guild_id: Optional[int]) -> str:
        """Create a unique session key."""
        if guild_id:
            return f"{guild_id}:{user_id}"
        return f"dm:{user_id}"

    @property
    def active_count(self) -> int:
        return len(self._sessions)

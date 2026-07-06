# app/memory/working.py
"""
Working Memory — current session context (volatile).
Phase 1: In-memory dict. Phase 2: Redis with TTL.
"""
import time
import logging
from typing import Dict, List, Any, Optional
from collections import defaultdict

logger = logging.getLogger(__name__)


class WorkingMemory:
    """
    Fast-access session context.
    Stores conversation history and working state per session.
    """

    def __init__(self, cache=None, max_messages: int = 20):
        self._cache = cache  # CacheBackend (Phase 2: Redis)
        self._max_messages = max_messages
        # In-memory storage (Phase 1)
        self._sessions: Dict[str, Dict[str, Any]] = {}
        self._messages: Dict[str, List[dict]] = defaultdict(list)

    async def get_context(self, session_id: str) -> dict:
        """Get full working context for a session."""
        return self._sessions.get(session_id, {})

    async def set(self, key: str, value: Any, ttl_seconds: int = 0) -> None:
        """Set a key-value pair in working memory (e.g., pending plans)."""
        self._sessions.setdefault("_kv_store", {})[key] = {
            "value": value,
            "expires_at": time.time() + ttl_seconds if ttl_seconds > 0 else 0,
        }

    async def get(self, key: str) -> Optional[Any]:
        """Get a value by key. Returns None if expired or missing."""
        kv = self._sessions.get("_kv_store", {})
        entry = kv.get(key)
        if entry is None:
            return None
        if entry["expires_at"] > 0 and time.time() > entry["expires_at"]:
            kv.pop(key, None)
            return None
        return entry["value"]

    async def delete(self, key: str) -> None:
        """Delete a key from working memory."""
        self._sessions.get("_kv_store", {}).pop(key, None)

    async def update(self, session_id: str, key: str, value: Any) -> None:
        """Update a working memory slot."""
        if session_id not in self._sessions:
            self._sessions[session_id] = {}
        self._sessions[session_id][key] = value

    async def add_message(
        self,
        session_id: str,
        user_id: str,
        role: str,
        content: str,
        guild_id: Optional[int] = None,
    ) -> None:
        """Add a message to session conversation history."""
        msg = {
            "role": role,
            "content": content,
            "user_id": user_id,
            "guild_id": guild_id,
            "timestamp": time.time(),
        }
        self._messages[session_id].append(msg)

        # Trim to max
        if len(self._messages[session_id]) > self._max_messages:
            self._messages[session_id] = self._messages[session_id][-self._max_messages:]

    async def get_conversation_history(
        self, session_id: str, limit: int = 10
    ) -> List[dict]:
        """Get recent conversation messages."""
        return self._messages.get(session_id, [])[-limit:]

    async def clear_session(self, session_id: str) -> None:
        """Clear all working memory for a session."""
        self._sessions.pop(session_id, None)
        self._messages.pop(session_id, None)

    @property
    def session_count(self) -> int:
        """Number of active sessions."""
        return len(self._messages)

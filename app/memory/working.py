"""WorkingMemory — in-memory, session-scoped short-term storage.

Stores conversation buffers, pending HITL plans, and transient context
that does not persist across bot restarts.
"""

from __future__ import annotations

import logging
from collections import deque
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

MAX_CONVERSATION_BUFFER: int = 10


@dataclass
class Message:
    """A single conversation message."""

    role: str
    content: str


@dataclass
class SessionData:
    """All working memory data for a single session."""

    plan: dict[str, Any] | None = None
    context: dict[str, Any] = field(default_factory=dict)
    conversation: deque[Message] = field(default_factory=lambda: deque(maxlen=MAX_CONVERSATION_BUFFER))


class WorkingMemory:
    """In-memory working memory — session-scoped, non-persistent.

    Holds pending HITL plans, transient context variables, and
    conversation buffers (last 10 messages per session).
    """

    def __init__(self) -> None:
        self._sessions: dict[str, SessionData] = {}
        logger.info("WorkingMemory initialized (in-memory)")

    def _ensure_session(self, session_id: str) -> SessionData:
        """Get or create session data."""
        if session_id not in self._sessions:
            self._sessions[session_id] = SessionData()
        return self._sessions[session_id]

    # ── Plan Management ─────────────────────────────────────────────

    def store_plan(self, session_id: str, plan: dict[str, Any]) -> None:
        """Store a HITL pending plan for the session.

        Args:
            session_id: Unique session identifier.
            plan: Plan dict (steps, metadata, etc.).
        """
        session = self._ensure_session(session_id)
        session.plan = plan
        logger.debug("Stored plan for session=%s", session_id)

    def get_plan(self, session_id: str) -> dict[str, Any] | None:
        """Retrieve pending plan for session.

        Args:
            session_id: Unique session identifier.

        Returns:
            Plan dict or None if no plan stored.
        """
        session = self._sessions.get(session_id)
        if session is None:
            return None
        return session.plan

    def clear_plan(self, session_id: str) -> None:
        """Clear the pending plan for session.

        Args:
            session_id: Unique session identifier.
        """
        session = self._sessions.get(session_id)
        if session is not None:
            session.plan = None
            logger.debug("Cleared plan for session=%s", session_id)

    # ── Context Management ──────────────────────────────────────────

    def store_context(self, session_id: str, key: str, value: Any) -> None:
        """Store a transient context variable.

        Args:
            session_id: Unique session identifier.
            key: Context key.
            value: Context value (any serializable type).
        """
        session = self._ensure_session(session_id)
        session.context[key] = value
        logger.debug("Stored context key='%s' for session=%s", key, session_id)

    def get_context(self, session_id: str) -> dict[str, Any]:
        """Get all context variables for session.

        Args:
            session_id: Unique session identifier.

        Returns:
            Dict of context key-value pairs (empty if no session).
        """
        session = self._sessions.get(session_id)
        if session is None:
            return {}
        return dict(session.context)

    # ── Conversation Buffer ─────────────────────────────────────────

    def get_conversation_buffer(self, session_id: str) -> list[dict[str, str]]:
        """Get last N messages for session.

        Args:
            session_id: Unique session identifier.

        Returns:
            List of message dicts with 'role' and 'content' keys.
        """
        session = self._sessions.get(session_id)
        if session is None:
            return []
        return [{"role": msg.role, "content": msg.content} for msg in session.conversation]

    def add_message(self, session_id: str, role: str, content: str) -> None:
        """Add a message to the conversation buffer.

        Buffer is capped at MAX_CONVERSATION_BUFFER (10) messages.
        Oldest messages are automatically evicted.

        Args:
            session_id: Unique session identifier.
            role: Message role (user, assistant, system).
            content: Message text content.
        """
        session = self._ensure_session(session_id)
        session.conversation.append(Message(role=role, content=content))
        logger.debug(
            "Added message role='%s' to session=%s (buffer=%d)",
            role,
            session_id,
            len(session.conversation),
        )

    # ── Session Management ──────────────────────────────────────────

    def clear(self, session_id: str) -> None:
        """Clear all working memory for a session.

        Args:
            session_id: Unique session identifier.
        """
        if session_id in self._sessions:
            del self._sessions[session_id]
            logger.info("Cleared all working memory for session=%s", session_id)

    def active_sessions(self) -> list[str]:
        """List all active session IDs.

        Returns:
            List of session ID strings.
        """
        return list(self._sessions.keys())

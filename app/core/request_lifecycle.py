"""Request Lifecycle — Stateful FSM for managing request flow.

Each user request = 1 RequestLifecycle object with defined state transitions.
Solves: concurrent access, expiration, restart resilience, approval flow.

Key = (guild_id, user_id) — two users in same guild never conflict.
"""

from __future__ import annotations

import logging
import time
import uuid
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


class RequestState(Enum):
    """All possible states of a request lifecycle."""
    RECEIVED = "received"
    PLANNING = "planning"
    AWAITING_APPROVAL = "awaiting_approval"
    EXECUTING = "executing"
    COMPLETED = "completed"
    FAILED = "failed"
    EXPIRED = "expired"
    CANCELLED = "cancelled"


# Valid state transitions (current_state → allowed_next_states)
_VALID_TRANSITIONS: Dict[RequestState, List[RequestState]] = {
    RequestState.RECEIVED: [RequestState.PLANNING, RequestState.FAILED],
    RequestState.PLANNING: [
        RequestState.AWAITING_APPROVAL,
        RequestState.EXECUTING,
        RequestState.COMPLETED,  # Text-only response, no execution needed
        RequestState.FAILED,
    ],
    RequestState.AWAITING_APPROVAL: [
        RequestState.EXECUTING,
        RequestState.CANCELLED,
        RequestState.EXPIRED,
    ],
    RequestState.EXECUTING: [
        RequestState.COMPLETED,
        RequestState.FAILED,
    ],
    # Terminal states — no transitions out
    RequestState.COMPLETED: [],
    RequestState.FAILED: [],
    RequestState.EXPIRED: [],
    RequestState.CANCELLED: [],
}


class RequestLifecycle:
    """A single user request with full state tracking.

    Attributes:
        id: Unique request ID
        guild_id: Discord guild
        user_id: User who initiated
        state: Current FSM state
        payload: Arbitrary data attached at each state (tool calls, params, results)
        created_at: Unix timestamp
        ttl: Time-to-live in seconds (for auto-expiration)
    """

    def __init__(
        self,
        guild_id: int,
        user_id: int,
        content: str,
        ttl: float = 300.0,
    ) -> None:
        self.id = uuid.uuid4().hex[:8]
        self.guild_id = guild_id
        self.user_id = user_id
        self.content = content
        self.state = RequestState.RECEIVED
        self.created_at = time.time()
        self.ttl = ttl
        self.payload: Dict[str, Any] = {}
        self._state_history: List[Tuple[RequestState, float]] = [
            (RequestState.RECEIVED, self.created_at)
        ]

    @property
    def is_expired(self) -> bool:
        """Check if request has exceeded its TTL."""
        return time.time() - self.created_at > self.ttl

    @property
    def is_terminal(self) -> bool:
        """Check if request is in a terminal state (no further transitions possible)."""
        return self.state in (
            RequestState.COMPLETED,
            RequestState.FAILED,
            RequestState.EXPIRED,
            RequestState.CANCELLED,
        )

    @property
    def is_awaiting_approval(self) -> bool:
        return self.state == RequestState.AWAITING_APPROVAL

    @property
    def age_seconds(self) -> float:
        return time.time() - self.created_at

    def transition(self, new_state: RequestState) -> bool:
        """Attempt state transition. Returns True if valid, False if rejected.

        Invalid transitions are logged but do NOT raise — fail-safe behavior.
        """
        # Auto-expire check
        if self.is_expired and new_state != RequestState.EXPIRED:
            logger.warning(
                "Request %s: attempted transition %s→%s but expired (age=%.0fs, ttl=%.0fs)",
                self.id, self.state.value, new_state.value, self.age_seconds, self.ttl,
            )
            self.state = RequestState.EXPIRED
            self._state_history.append((RequestState.EXPIRED, time.time()))
            return False

        allowed = _VALID_TRANSITIONS.get(self.state, [])
        if new_state not in allowed:
            logger.warning(
                "Request %s: invalid transition %s→%s (allowed: %s)",
                self.id, self.state.value, new_state.value,
                [s.value for s in allowed],
            )
            return False

        self.state = new_state
        self._state_history.append((new_state, time.time()))
        return True

    def set_payload(self, key: str, value: Any) -> None:
        """Attach data to this request lifecycle."""
        self.payload[key] = value

    def get_payload(self, key: str, default: Any = None) -> Any:
        """Retrieve attached data."""
        return self.payload.get(key, default)


class RequestStore:
    """Manages all active request lifecycles.

    Key: (guild_id, user_id) — ensures one active request per user per guild.
    Auto-expires old requests on access.

    Thread-safe: designed for single asyncio event loop (no threading needed).
    """

    def __init__(self, default_ttl: float = 300.0) -> None:
        self._active: Dict[Tuple[int, int], RequestLifecycle] = {}
        self._default_ttl = default_ttl

    def create(self, guild_id: int, user_id: int, content: str) -> RequestLifecycle:
        """Create a new request, replacing any existing one for this user.

        If there's an existing non-terminal request → auto-expire it.
        """
        key = (guild_id, user_id)
        existing = self._active.get(key)

        if existing and not existing.is_terminal:
            # Auto-expire the old request
            existing.transition(RequestState.EXPIRED)
            logger.info(
                "Request %s auto-expired (replaced by new request from user %d)",
                existing.id, user_id,
            )

        req = RequestLifecycle(guild_id, user_id, content, ttl=self._default_ttl)
        self._active[key] = req
        return req

    def get_active(self, guild_id: int, user_id: int) -> Optional[RequestLifecycle]:
        """Get the active (non-terminal, non-expired) request for a user.

        Returns None if no active request or if expired.
        """
        key = (guild_id, user_id)
        req = self._active.get(key)

        if req is None:
            return None

        if req.is_terminal:
            return None

        if req.is_expired:
            req.transition(RequestState.EXPIRED)
            return None

        return req

    def get_awaiting_approval(self, guild_id: int, user_id: int) -> Optional[RequestLifecycle]:
        """Get request waiting for user approval, if any."""
        req = self.get_active(guild_id, user_id)
        if req and req.is_awaiting_approval:
            return req
        return None

    def complete(self, guild_id: int, user_id: int) -> None:
        """Mark the active request as completed."""
        req = self.get_active(guild_id, user_id)
        if req:
            req.transition(RequestState.COMPLETED)

    def fail(self, guild_id: int, user_id: int, reason: str = "") -> None:
        """Mark the active request as failed."""
        req = self.get_active(guild_id, user_id)
        if req:
            req.set_payload("failure_reason", reason)
            req.transition(RequestState.FAILED)

    def cleanup_expired(self) -> int:
        """Remove all expired/terminal requests from memory. Returns count removed."""
        to_remove = []
        for key, req in self._active.items():
            if req.is_terminal or req.is_expired:
                to_remove.append(key)

        for key in to_remove:
            del self._active[key]

        return len(to_remove)

    @property
    def active_count(self) -> int:
        """Number of non-terminal requests."""
        return sum(1 for r in self._active.values() if not r.is_terminal and not r.is_expired)

    @property
    def total_count(self) -> int:
        return len(self._active)

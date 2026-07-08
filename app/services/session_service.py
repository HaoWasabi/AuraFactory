"""SessionMemoryService — in-memory TTL session store for Aura Companion.

Key design decisions:
- Per-session asyncio.Lock for concurrent access safety
- meta_lock protects the store/locks dicts themselves
- TTL reset on every access (sliding window)
- No DB writes — pure in-memory
- Shared via app.state.session_store between DiscordBot and API routes
"""
from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Optional

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass
class SessionMemory:
    """Per-user session state within a guild."""
    guild_id: int
    user_id: int

    # Discord entities mentioned/created in this session
    # {"channels": {"name": "id"}, "roles": {"name": "id"}, "categories": {"name": "id"}, "members": {"name": "id"}}
    recent_entities: dict = field(default_factory=lambda: {
        "channels": {}, "roles": {}, "categories": {}, "members": {},
    })

    # Last 6 conversation turns [{role, content}]
    conversation_history: list = field(default_factory=list)

    # Pending clarification state
    # {"context": str, "round": int (1|2), "question": str} or None
    pending_clarification: Optional[dict] = None

    # Conversation mode
    conversation_mode: str = "normal"  # "normal" | "clarifying" | "diagnostic"

    # TTL tracking — monotonic time of last access
    last_accessed: float = field(default_factory=time.monotonic)

    # Archetype detected for this server/conversation
    archetype: Optional[str] = None  # key into ARCHETYPE_MAP

    # Clarification round counter (reset when intent succeeds)
    clarification_rounds: int = 0

    # Tips already shown in this session — prevent repetition
    shown_tips: set = field(default_factory=set)

    def touch(self) -> None:
        """Reset TTL (update last_accessed to now)."""
        self.last_accessed = time.monotonic()

    def add_history(self, role: str, content: str, max_turns: int = 6) -> None:
        """Append a conversation turn, keeping at most max_turns entries."""
        self.conversation_history.append({"role": role, "content": content})
        if len(self.conversation_history) > max_turns:
            self.conversation_history = self.conversation_history[-max_turns:]

    def update_from_execution(self, tool_name: str, result: dict) -> None:
        """Extract Discord IDs from execution result and store in recent_entities.

        Called after each successful ExecutorService step to enable
        ID forwarding in subsequent Planner prompts.

        Examples:
            discord.channels.create → result{"id": "111", "name": "lobby"}
              → recent_entities["channels"]["lobby"] = "111"
            discord.roles.create → result{"id": "222", "name": "Admin"}
              → recent_entities["roles"]["Admin"] = "222"
        """
        if not isinstance(result, dict):
            return

        entity_id = str(result.get("id", ""))
        entity_name = str(result.get("name", ""))
        if not entity_id or not entity_name:
            return

        tool_lower = tool_name.lower()
        if "channel" in tool_lower:
            self.recent_entities.setdefault("channels", {})[entity_name] = entity_id
        elif "role" in tool_lower:
            self.recent_entities.setdefault("roles", {})[entity_name] = entity_id
        elif "category" in tool_lower or "categor" in tool_lower:
            self.recent_entities.setdefault("categories", {})[entity_name] = entity_id
        elif "member" in tool_lower or "user" in tool_lower:
            self.recent_entities.setdefault("members", {})[entity_name] = entity_id


# ---------------------------------------------------------------------------
# Context string formatter
# ---------------------------------------------------------------------------

def format_context_string(session: SessionMemory) -> str:
    """Build a compact context string to inject into the Planner user prompt.

    Returns empty string if no entities have been tracked yet.

    Example output:
        ## Recent Session Context
        - Categories: "GAME" → id: 987654321
        - Channels: "#lobby" → id: 111222333, "#rules" → id: 444555666
        - Roles: "@Admin" → id: 222333444
    """
    lines = []

    categories = session.recent_entities.get("categories", {})
    if categories:
        cats_str = ", ".join(f'"{n}" → id: {i}' for n, i in categories.items())
        lines.append(f"- Categories: {cats_str}")

    channels = session.recent_entities.get("channels", {})
    if channels:
        chs_str = ", ".join(f'"#{n}" → id: {i}' for n, i in channels.items())
        lines.append(f"- Channels: {chs_str}")

    roles = session.recent_entities.get("roles", {})
    if roles:
        rls_str = ", ".join(f'"@{n}" → id: {i}' for n, i in roles.items())
        lines.append(f"- Roles: {rls_str}")

    members = session.recent_entities.get("members", {})
    if members:
        mbs_str = ", ".join(f'"{n}" → id: {i}' for n, i in members.items())
        lines.append(f"- Members: {mbs_str}")

    if not lines:
        return ""

    return "## Recent Session Context\n" + "\n".join(lines)


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------

class SessionMemoryService:
    """In-memory TTL session store. Thread-safe via asyncio.Lock per session.

    Shared across DiscordBot and API routes via app.state.session_store.
    No DB dependency — pure in-memory. Sessions expire after TTL_SECONDS
    of inactivity (sliding window).
    """

    TTL_SECONDS: int = 1800       # 30 minutes
    CLEANUP_INTERVAL: int = 300   # run cleanup every 5 minutes
    MAX_SESSIONS: int = 10_000    # force-expire oldest sessions above this limit
    HISTORY_MAX: int = 6          # max conversation turns per session

    def __init__(self) -> None:
        # key = (guild_id, user_id)
        self._store: dict[tuple[int, int], SessionMemory] = {}
        self._locks: dict[tuple[int, int], asyncio.Lock] = {}
        self._meta_lock = asyncio.Lock()   # protects _store and _locks dicts
        self._cleanup_task: Optional[asyncio.Task] = None
        self._stats = {
            "hit": 0,
            "miss": 0,
            "evicted": 0,
        }

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """Start the background cleanup task. Call once in app lifespan."""
        self._cleanup_task = asyncio.create_task(
            self._cleanup_loop(), name="session_cleanup"
        )
        active = await self.get_active_count()
        logger.info(
            "[SessionMemory] started — active_sessions=%d ttl=%ds cleanup_interval=%ds",
            active, self.TTL_SECONDS, self.CLEANUP_INTERVAL,
        )

    async def stop(self) -> None:
        """Cancel the cleanup task. Call in app shutdown."""
        if self._cleanup_task and not self._cleanup_task.done():
            self._cleanup_task.cancel()
            try:
                await self._cleanup_task
            except asyncio.CancelledError:
                pass
        logger.info("[SessionMemory] stopped")

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def get_session(self, guild_id: int, user_id: int) -> SessionMemory:
        """Get existing session or create a new one. Resets TTL on access."""
        key = (guild_id, user_id)

        async with self._meta_lock:
            if key not in self._locks:
                self._locks[key] = asyncio.Lock()

        session_lock = self._locks[key]
        async with session_lock:
            if key in self._store:
                session = self._store[key]
                session.touch()
                self._stats["hit"] += 1
                logger.debug(
                    "[SessionMemory] HIT guild=%d user=%d",
                    guild_id, user_id,
                )
                return session

            # Create new session
            session = SessionMemory(guild_id=guild_id, user_id=user_id)
            self._store[key] = session
            self._stats["miss"] += 1
            logger.info(
                "[SessionMemory] MISS guild=%d user=%d — created new session",
                guild_id, user_id,
            )
            return session

    async def update_session(
        self,
        guild_id: int,
        user_id: int,
        data: dict,
    ) -> None:
        """Update session fields and reset TTL.

        Supported data keys: any field of SessionMemory.
        Special handling for list fields (conversation_history → append).
        """
        key = (guild_id, user_id)

        # Ensure session and lock exist
        session = await self.get_session(guild_id, user_id)

        session_lock = self._locks.get(key)
        if not session_lock:
            return

        async with session_lock:
            for field_name, value in data.items():
                if hasattr(session, field_name):
                    setattr(session, field_name, value)
            session.touch()

    async def clear_session(self, guild_id: int, user_id: int) -> None:
        """Delete session and release its lock."""
        key = (guild_id, user_id)
        async with self._meta_lock:
            self._store.pop(key, None)
            self._locks.pop(key, None)
        logger.debug("[SessionMemory] cleared guild=%d user=%d", guild_id, user_id)

    async def get_active_count(self) -> int:
        """Count sessions that haven't expired yet."""
        now = time.monotonic()
        async with self._meta_lock:
            return sum(
                1 for s in self._store.values()
                if now - s.last_accessed < self.TTL_SECONDS
            )

    async def get_stats(self) -> dict:
        """Return service stats."""
        active = await self.get_active_count()
        oldest_age = 0.0
        async with self._meta_lock:
            if self._store:
                now = time.monotonic()
                oldest_age = max(now - s.last_accessed for s in self._store.values())
        total_requests = self._stats["hit"] + self._stats["miss"]
        hit_rate = self._stats["hit"] / total_requests if total_requests > 0 else 0.0
        return {
            "active_sessions": active,
            "total_sessions": len(self._store),
            "oldest_session_age_s": round(oldest_age, 1),
            "ttl_seconds": self.TTL_SECONDS,
            "cache_hit_rate": round(hit_rate, 3),
            "evicted": self._stats["evicted"],
        }

    # ------------------------------------------------------------------
    # Background cleanup
    # ------------------------------------------------------------------

    async def _cleanup_loop(self) -> None:
        """Run cleanup every CLEANUP_INTERVAL seconds."""
        while True:
            try:
                await asyncio.sleep(self.CLEANUP_INTERVAL)
                removed = await self._run_cleanup()
                if removed:
                    logger.info("[SessionMemory] cleanup removed %d expired sessions", removed)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.warning("[SessionMemory] cleanup error: %s", e)

    async def _run_cleanup(self) -> int:
        """Expire sessions past TTL. Returns count of removed sessions.

        If store exceeds MAX_SESSIONS, force-evicts oldest sessions first.
        """
        now = time.monotonic()
        to_remove: list[tuple[int, int]] = []

        async with self._meta_lock:
            # Force-evict oldest sessions if over limit
            if len(self._store) > self.MAX_SESSIONS:
                sorted_keys = sorted(
                    self._store.keys(),
                    key=lambda k: self._store[k].last_accessed,
                )
                excess = len(self._store) - self.MAX_SESSIONS
                to_remove.extend(sorted_keys[:excess])
                logger.warning(
                    "[SessionMemory] MAX_SESSIONS exceeded — force-evicting %d oldest sessions",
                    excess,
                )

            # Normal TTL expiry
            for key, session in self._store.items():
                if key not in to_remove and now - session.last_accessed >= self.TTL_SECONDS:
                    to_remove.append(key)

            for key in to_remove:
                self._store.pop(key, None)
                self._locks.pop(key, None)
                self._stats["evicted"] += 1

        return len(to_remove)

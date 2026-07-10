"""Safety Layer — Production guard rails for tool execution.

Implements:
  1. Approval Gate — destructive actions require user confirmation
  2. Rate Limiter — prevent Discord API rate limits
  3. Guild Lock — only allowed guilds can be managed
  4. Audit Logger — full trail of who did what, when
  5. Retry Logic — exponential backoff on transient failures
"""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Set

from app.core.spec_loader import SpecRegistry

logger = logging.getLogger(__name__)


# ===========================================================================
# 1. APPROVAL GATE
# ===========================================================================

class ApprovalGate:
    """Determines which actions need user confirmation before execution.

    Rules:
      - risk_level "high" → ask confirmation (describe what will happen)
      - risk_level "critical" → ask confirmation + require explicit "yes"
      - risk_level "low" / "medium" → execute immediately
    """

    def __init__(self, registry: SpecRegistry) -> None:
        self._registry = registry
        # Pending approvals: {request_id: PendingAction}
        self._pending: Dict[str, Dict[str, Any]] = {}

    def needs_approval(self, tool_name: str) -> bool:
        """Check if a tool call requires user approval."""
        spec = self._registry.get_tool(tool_name)
        if spec is None:
            return False
        return spec.risk_level in ("high", "critical")

    def get_risk_level(self, tool_name: str) -> str:
        """Get risk level for a tool."""
        spec = self._registry.get_tool(tool_name)
        return spec.risk_level if spec else "medium"

    def create_approval_request(
        self,
        request_id: str,
        tool_name: str,
        kwargs: Dict[str, Any],
        guild_id: int,
        user_id: int,
    ) -> Dict[str, Any]:
        """Create a pending approval request.

        Returns a description of what will happen (for showing to user).
        """
        spec = self._registry.get_tool(tool_name)
        description = spec.description if spec else tool_name

        # Build human-readable action description
        action_desc = self._describe_action(tool_name, kwargs)

        pending = {
            "request_id": request_id,
            "tool_name": tool_name,
            "kwargs": kwargs,
            "guild_id": guild_id,
            "user_id": user_id,
            "risk_level": spec.risk_level if spec else "high",
            "description": action_desc,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "status": "pending",
        }
        self._pending[request_id] = pending
        return pending

    def approve(self, request_id: str) -> Optional[Dict[str, Any]]:
        """Approve a pending request. Returns the action to execute."""
        pending = self._pending.pop(request_id, None)
        if pending:
            pending["status"] = "approved"
            pending["approved_at"] = datetime.now(timezone.utc).isoformat()
        return pending

    def reject(self, request_id: str) -> Optional[Dict[str, Any]]:
        """Reject a pending request."""
        pending = self._pending.pop(request_id, None)
        if pending:
            pending["status"] = "rejected"
        return pending

    def get_pending(self, guild_id: int) -> List[Dict[str, Any]]:
        """Get all pending approvals for a guild."""
        return [p for p in self._pending.values() if p["guild_id"] == guild_id]

    def cleanup_expired(self, max_age_seconds: int = 300) -> int:
        """Remove approvals older than max_age. Returns count removed."""
        now = time.time()
        expired = []
        for rid, pending in self._pending.items():
            created = datetime.fromisoformat(pending["created_at"]).timestamp()
            if now - created > max_age_seconds:
                expired.append(rid)
        for rid in expired:
            del self._pending[rid]
        return len(expired)

    def _describe_action(self, tool_name: str, kwargs: Dict[str, Any]) -> str:
        """Generate human-readable description of the action."""
        action = tool_name.split(".")[-1] if "." in tool_name else tool_name
        module = tool_name.split(".")[1] if "." in tool_name else "unknown"

        # Build description based on action type
        if "delete" in action or "ban" in action or "kick" in action:
            target = kwargs.get("channel_id") or kwargs.get("role_id") or kwargs.get("member_id") or kwargs.get("name", "unknown")
            return f"⚠️ **{action.upper()}** {module}: target={target}"
        elif "bulk" in action:
            count = len(kwargs.get("member_ids", []))
            return f"⚠️ **BULK {action.upper()}**: {count} targets"
        elif action == "restore":
            return "⚠️ **RESTORE** guild structure from backup (additive)"
        else:
            name = kwargs.get("name", kwargs.get("level", ""))
            return f"⚠️ **{action.upper()}** {module}: {name}"


# ===========================================================================
# 2. RATE LIMITER
# ===========================================================================

class RateLimiter:
    """Prevent hitting Discord API rate limits.

    Strategy:
      - Minimum delay between tool executions: 0.5s (configurable)
      - Max burst: 5 calls without delay
      - After burst: enforce delay
      - Track per-endpoint if needed (future)
    """

    def __init__(self, min_delay: float = 0.5, burst_limit: int = 5) -> None:
        self._min_delay = min_delay
        self._burst_limit = burst_limit
        self._call_times: List[float] = []
        self._lock = asyncio.Lock()

    async def acquire(self) -> None:
        """Wait if necessary to respect rate limits."""
        async with self._lock:
            now = time.time()

            # Clean old timestamps (older than 10s)
            self._call_times = [t for t in self._call_times if now - t < 10]

            # If within burst limit, proceed immediately
            if len(self._call_times) < self._burst_limit:
                self._call_times.append(now)
                return

            # Otherwise, enforce delay since last call
            if self._call_times:
                elapsed = now - self._call_times[-1]
                if elapsed < self._min_delay:
                    wait = self._min_delay - elapsed
                    await asyncio.sleep(wait)

            self._call_times.append(time.time())

    @property
    def recent_calls(self) -> int:
        """Number of calls in last 10 seconds."""
        now = time.time()
        return sum(1 for t in self._call_times if now - t < 10)


# ===========================================================================
# 3. GUILD LOCK
# ===========================================================================

class GuildLock:
    """Restrict bot operations to allowed guilds only.

    In production, this prevents the bot from being invited to random
    servers and executing destructive operations.

    Modes:
      - "whitelist": Only guilds in allowed_ids can use the bot
      - "open": All guilds allowed (dev mode)
    """

    def __init__(self, mode: str = "open", allowed_ids: Optional[Set[int]] = None) -> None:
        self._mode = mode
        self._allowed_ids = allowed_ids or set()

    def is_allowed(self, guild_id: int) -> bool:
        """Check if a guild is allowed to use the bot."""
        if self._mode == "open":
            return True
        return guild_id in self._allowed_ids

    def add_guild(self, guild_id: int) -> None:
        """Add a guild to the whitelist."""
        self._allowed_ids.add(guild_id)

    def remove_guild(self, guild_id: int) -> None:
        """Remove a guild from the whitelist."""
        self._allowed_ids.discard(guild_id)

    @property
    def mode(self) -> str:
        return self._mode

    @property
    def allowed_count(self) -> int:
        return len(self._allowed_ids)


# ===========================================================================
# 4. AUDIT LOGGER
# ===========================================================================

class AuditLogger:
    """Log all tool executions for accountability.

    Phase 1: In-memory + file logging
    Phase 2: DynamoDB persistent storage

    Each entry contains:
      - timestamp, guild_id, user_id
      - tool_name, kwargs (sanitized)
      - result (success/error)
      - risk_level
    """

    def __init__(self, db=None) -> None:
        self._db = db  # Database instance (Phase 2: DynamoDB)
        self._entries: List[Dict[str, Any]] = []
        self._max_memory = 1000  # Keep last 1000 in memory

    async def log_execution(
        self,
        guild_id: int,
        user_id: int,
        tool_name: str,
        kwargs: Dict[str, Any],
        result: Dict[str, Any],
        risk_level: str,
        duration_ms: float,
    ) -> None:
        """Log a tool execution."""
        entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "guild_id": guild_id,
            "user_id": user_id,
            "tool_name": tool_name,
            "kwargs": self._sanitize_kwargs(kwargs),
            "success": result.get("status") != "error" and "error" not in result,
            "risk_level": risk_level,
            "duration_ms": round(duration_ms, 2),
        }

        # Memory storage
        self._entries.append(entry)
        if len(self._entries) > self._max_memory:
            self._entries = self._entries[-self._max_memory:]

        # File logging (always)
        logger.info(
            "AUDIT | guild=%d user=%d tool=%s risk=%s success=%s duration=%.0fms",
            guild_id, user_id, tool_name, risk_level,
            entry["success"], duration_ms,
        )

        # DB storage (Phase 2)
        if self._db:
            try:
                await self._db.execute(
                    """INSERT INTO audit_log (guild_id, user_id, tool_name, tool_params, risk_level, success, duration_ms)
                       VALUES ($1, $2, $3, $4::jsonb, $5, $6, $7)""",
                    guild_id, user_id, tool_name,
                    str(entry["kwargs"])[:500],
                    risk_level, entry["success"], duration_ms,
                )
            except Exception as e:
                logger.warning("Audit DB write failed: %s", e)

    async def log_approval(
        self,
        guild_id: int,
        user_id: int,
        tool_name: str,
        action: str,  # "approved" or "rejected"
    ) -> None:
        """Log an approval decision."""
        logger.info(
            "AUDIT | guild=%d user=%d tool=%s APPROVAL=%s",
            guild_id, user_id, tool_name, action,
        )

    def get_recent(self, guild_id: int, limit: int = 50) -> List[Dict[str, Any]]:
        """Get recent audit entries for a guild."""
        guild_entries = [e for e in self._entries if e["guild_id"] == guild_id]
        return guild_entries[-limit:]

    @staticmethod
    def _sanitize_kwargs(kwargs: Dict[str, Any]) -> Dict[str, Any]:
        """Remove sensitive data from kwargs before logging."""
        sanitized = {}
        sensitive_keys = {"token", "secret", "password", "api_key"}
        for key, value in kwargs.items():
            if key.lower() in sensitive_keys:
                sanitized[key] = "***"
            elif isinstance(value, str) and len(value) > 200:
                sanitized[key] = value[:200] + "..."
            else:
                sanitized[key] = value
        return sanitized


# ===========================================================================
# 5. RETRY LOGIC
# ===========================================================================

class RetryPolicy:
    """Exponential backoff retry for transient Discord API failures.

    Retries on:
      - HTTP 429 (rate limited)
      - HTTP 5xx (server error)
      - Connection errors

    Does NOT retry on:
      - HTTP 403 (permission denied)
      - HTTP 400 (bad request)
      - HTTP 404 (not found)
    """

    def __init__(self, max_retries: int = 3, base_delay: float = 1.0) -> None:
        self._max_retries = max_retries
        self._base_delay = base_delay

    async def execute_with_retry(self, coro_factory, *args, **kwargs) -> Any:
        """Execute an async callable with retry logic.

        Args:
            coro_factory: Async function to call
            *args, **kwargs: Arguments to pass

        Returns:
            Result from successful execution

        Raises:
            Last exception if all retries exhausted
        """
        last_error = None

        for attempt in range(self._max_retries + 1):
            try:
                return await coro_factory(*args, **kwargs)
            except Exception as e:
                last_error = e
                error_str = str(e).lower()

                # Don't retry on non-transient errors
                if any(code in error_str for code in ("403", "forbidden", "400", "bad request", "404", "not found")):
                    raise

                # Retry on transient errors
                if attempt < self._max_retries:
                    delay = self._base_delay * (2 ** attempt)
                    logger.warning(
                        "Retry %d/%d after %.1fs (error: %s)",
                        attempt + 1, self._max_retries, delay, str(e)[:100],
                    )
                    await asyncio.sleep(delay)

        raise last_error


# ===========================================================================
# 6. CONVERSATION MEMORY (Resource Tracking)
# ===========================================================================

class ConversationMemory:
    """Track resources created/modified in the current conversation.

    Allows multi-turn references like:
      "create channel X" → "now make it private"
      (agent knows "it" = channel just created)

    Storage: per-guild, per-conversation session.
    """

    def __init__(self, max_entries: int = 50) -> None:
        # {guild_id: [{resource_type, id, name, action, timestamp}]}
        self._memory: Dict[int, List[Dict[str, Any]]] = {}
        self._max_entries = max_entries

    def record(
        self,
        guild_id: int,
        resource_type: str,  # "channel", "role", "category", etc.
        resource_id: str,
        resource_name: str,
        action: str,  # "created", "edited", "deleted"
    ) -> None:
        """Record a resource operation."""
        if guild_id not in self._memory:
            self._memory[guild_id] = []

        entry = {
            "type": resource_type,
            "id": resource_id,
            "name": resource_name,
            "action": action,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        self._memory[guild_id].append(entry)

        # Trim to max
        if len(self._memory[guild_id]) > self._max_entries:
            self._memory[guild_id] = self._memory[guild_id][-self._max_entries:]

    def get_recent(self, guild_id: int, limit: int = 10) -> List[Dict[str, Any]]:
        """Get recent resource operations for context injection."""
        entries = self._memory.get(guild_id, [])
        return entries[-limit:]

    def get_last_created(self, guild_id: int, resource_type: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """Get the most recently created resource (for 'it' references)."""
        entries = self._memory.get(guild_id, [])
        for entry in reversed(entries):
            if entry["action"] == "created":
                if resource_type is None or entry["type"] == resource_type:
                    return entry
        return None

    def build_context_block(self, guild_id: int) -> str:
        """Build a context string for LLM prompt injection."""
        recent = self.get_recent(guild_id, limit=5)
        if not recent:
            return ""

        lines = ["[Recent actions in this conversation]"]
        for entry in recent:
            lines.append(f"  - {entry['action']} {entry['type']}: \"{entry['name']}\" (id: {entry['id']})")
        return "\n".join(lines)

    def clear(self, guild_id: int) -> None:
        """Clear memory for a guild (session ended)."""
        self._memory.pop(guild_id, None)

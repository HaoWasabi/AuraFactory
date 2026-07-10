"""RedisCache — Hot cache for sessions, snapshots, rate-limits, and locks.

Design principle: FAIL-OPEN. If Redis is unreachable:
  - Sessions → in-memory fallback
  - Snapshots → fetch from Discord directly
  - Rate-limits → allow through
  - Locks → in-memory dict

Namespace: aura:{guild_id}:{entity}:{sub_key}
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class RedisCache:
    """Redis-backed hot cache with in-memory fallback.

    Phase 1: In-memory dict that mimics Redis API (no actual Redis dependency).
    Phase 2: Swap to real Redis (redis-py async) — same interface, just change __init__.

    This approach lets the app work with zero external dependencies while
    maintaining the exact same API that real Redis would use.
    """

    def __init__(self, redis_url: Optional[str] = None) -> None:
        self._redis = None  # Will be aioredis connection in Phase 2
        self._use_memory = True
        self._memory: Dict[str, Any] = {}
        self._expiry: Dict[str, float] = {}  # key → expire_timestamp

        if redis_url:
            try:
                import redis.asyncio as aioredis
                self._redis = aioredis.from_url(redis_url, decode_responses=True)
                self._use_memory = False
                logger.info("RedisCache: connected to %s", redis_url[:20] + "...")
            except ImportError:
                logger.warning("RedisCache: redis package not installed, using in-memory fallback")
            except Exception as e:
                logger.warning("RedisCache: connection failed (%s), using in-memory fallback", e)

    # ===================================================================
    # Session Management
    # ===================================================================

    async def get_session(self, guild_id: int, user_id: int) -> Optional[Dict[str, Any]]:
        """Get active session for a user in a guild."""
        key = f"aura:{guild_id}:session:{user_id}"
        data = await self._hgetall(key)
        if not data:
            return None
        # Parse history JSON
        if "history" in data and isinstance(data["history"], str):
            try:
                data["history"] = json.loads(data["history"])
            except json.JSONDecodeError:
                data["history"] = []
        return data

    async def save_session(
        self, guild_id: int, user_id: int, session_data: Dict[str, Any], ttl: int = 1800
    ) -> None:
        """Save session with TTL (default 30 min)."""
        key = f"aura:{guild_id}:session:{user_id}"
        # Serialize complex fields
        store_data = dict(session_data)
        if "history" in store_data and isinstance(store_data["history"], list):
            store_data["history"] = json.dumps(store_data["history"], default=str)
        await self._hset(key, store_data)
        await self._expire(key, ttl)

    async def delete_session(self, guild_id: int, user_id: int) -> None:
        """Delete a session."""
        key = f"aura:{guild_id}:session:{user_id}"
        await self._delete(key)

    # ===================================================================
    # Server Snapshot Cache
    # ===================================================================

    async def get_snapshot(self, guild_id: int) -> Optional[Dict[str, Any]]:
        """Get cached server snapshot."""
        key = f"aura:{guild_id}:snapshot"
        data = await self._hgetall(key)
        if not data:
            return None
        # Parse JSON fields
        for field in ("categories", "channels", "roles", "server_info"):
            if field in data and isinstance(data[field], str):
                try:
                    data[field] = json.loads(data[field])
                except json.JSONDecodeError:
                    data[field] = []
        return data

    async def set_snapshot(self, guild_id: int, snapshot: Dict[str, Any], ttl: int = 60) -> None:
        """Cache server snapshot with TTL."""
        key = f"aura:{guild_id}:snapshot"
        store_data = {}
        for field, value in snapshot.items():
            if isinstance(value, (list, dict)):
                store_data[field] = json.dumps(value, default=str)
            else:
                store_data[field] = str(value) if value is not None else ""
        await self._hset(key, store_data)
        await self._expire(key, ttl)

    async def invalidate_snapshot(self, guild_id: int) -> None:
        """Force-expire a snapshot (after tool execution modifies server state)."""
        await self._delete(f"aura:{guild_id}:snapshot")

    # ===================================================================
    # Rate Limiting
    # ===================================================================

    async def check_rate_limit(self, guild_id: int, user_id: int, burst_limit: int = 5) -> bool:
        """Check if user is within rate limit. Returns True if allowed."""
        key = f"aura:{guild_id}:ratelimit:{user_id}"
        count = await self._incr(key)
        if count == 1:
            await self._expire(key, 60)  # 60s window
        return count <= burst_limit

    # ===================================================================
    # Guild Execution Lock
    # ===================================================================

    async def acquire_lock(self, guild_id: int, request_id: str, ttl: int = 30) -> bool:
        """Try to acquire guild execution lock (SETNX pattern).

        Returns True if lock acquired, False if already locked.
        """
        key = f"aura:{guild_id}:lock"
        return await self._setnx(key, request_id, ttl)

    async def release_lock(self, guild_id: int, request_id: str) -> None:
        """Release lock only if we own it (compare-and-delete)."""
        key = f"aura:{guild_id}:lock"
        current = await self._get(key)
        if current == request_id:
            await self._delete(key)

    # ===================================================================
    # Approval State
    # ===================================================================

    async def save_approval(self, guild_id: int, request_id: str, approval_data: Dict[str, Any], ttl: int = 300) -> None:
        """Save pending approval state."""
        key = f"aura:{guild_id}:approval:{request_id}"
        store = {k: json.dumps(v) if isinstance(v, (list, dict)) else str(v) for k, v in approval_data.items()}
        await self._hset(key, store)
        await self._expire(key, ttl)

    async def get_approval(self, guild_id: int, request_id: str) -> Optional[Dict[str, Any]]:
        """Get pending approval."""
        key = f"aura:{guild_id}:approval:{request_id}"
        return await self._hgetall(key)

    async def delete_approval(self, guild_id: int, request_id: str) -> None:
        """Remove approval after processing."""
        await self._delete(f"aura:{guild_id}:approval:{request_id}")

    # ===================================================================
    # In-Memory Backend (Phase 1 — mimics Redis API)
    # ===================================================================

    async def _hgetall(self, key: str) -> Optional[Dict[str, Any]]:
        if self._use_memory:
            self._cleanup_expired()
            return self._memory.get(key)
        return await self._redis.hgetall(key) or None

    async def _hset(self, key: str, mapping: Dict[str, Any]) -> None:
        if self._use_memory:
            self._memory[key] = mapping
        else:
            await self._redis.hset(key, mapping=mapping)

    async def _get(self, key: str) -> Optional[str]:
        if self._use_memory:
            self._cleanup_expired()
            val = self._memory.get(key)
            return val if isinstance(val, str) else None
        return await self._redis.get(key)

    async def _setnx(self, key: str, value: str, ttl: int) -> bool:
        if self._use_memory:
            self._cleanup_expired()
            if key in self._memory:
                return False
            self._memory[key] = value
            self._expiry[key] = time.time() + ttl
            return True
        return await self._redis.set(key, value, nx=True, ex=ttl)

    async def _incr(self, key: str) -> int:
        if self._use_memory:
            self._cleanup_expired()
            current = self._memory.get(key, 0)
            if not isinstance(current, int):
                current = 0
            current += 1
            self._memory[key] = current
            return current
        return await self._redis.incr(key)

    async def _expire(self, key: str, ttl: int) -> None:
        if self._use_memory:
            self._expiry[key] = time.time() + ttl
        else:
            await self._redis.expire(key, ttl)

    async def _delete(self, key: str) -> None:
        if self._use_memory:
            self._memory.pop(key, None)
            self._expiry.pop(key, None)
        else:
            await self._redis.delete(key)

    def _cleanup_expired(self) -> None:
        """Remove expired keys from in-memory store."""
        now = time.time()
        expired = [k for k, t in self._expiry.items() if t <= now]
        for k in expired:
            self._memory.pop(k, None)
            self._expiry.pop(k, None)

    # ===================================================================
    # Lifecycle
    # ===================================================================

    async def close(self) -> None:
        """Close Redis connection."""
        if self._redis:
            await self._redis.close()

    @property
    def is_connected(self) -> bool:
        """Check if using real Redis (not fallback)."""
        return not self._use_memory

"""RateLimitService — enforces per-user/guild request rate limits (§Req 2)."""
import logging
from datetime import datetime, timezone
from typing import Optional

from app.database import Database

logger = logging.getLogger(__name__)


class RateLimitService:
    """Enforces rate limiting: max 10 requests per user per guild per minute.
    
    Uses the `rate_limits` table (migration 010) with a sliding window
    truncated to the minute boundary.
    
    Fail-open: if database is unavailable, allows the request through.
    """

    LIMIT: int = 10          # max requests per window
    WINDOW_SECONDS: int = 60  # window size in seconds

    def __init__(self, db: Database) -> None:
        self.db = db

    async def check_and_increment(self, user_id: int, guild_id: int) -> bool:
        """Check rate limit and increment counter if within limit.
        
        Args:
            user_id: Discord user ID.
            guild_id: Discord guild ID.
            
        Returns:
            True if request is allowed, False if rate limit exceeded.
        """
        now = datetime.now(timezone.utc)
        # Truncate to minute boundary (the window key)
        window_start = now.replace(second=0, microsecond=0)

        try:
            row = await self.db.fetchrow(
                """INSERT INTO rate_limits (user_id, guild_id, window_start, request_count)
                   VALUES ($1, $2, $3, 1)
                   ON CONFLICT (user_id, guild_id, window_start)
                   DO UPDATE SET request_count = rate_limits.request_count + 1
                   RETURNING request_count""",
                user_id,
                guild_id,
                window_start,
            )
            count = row["request_count"] if row else 1
            allowed = count <= self.LIMIT
            if not allowed:
                logger.info(
                    "Rate limit exceeded for user=%d guild=%d (count=%d, limit=%d)",
                    user_id, guild_id, count, self.LIMIT,
                )
            return allowed
        except Exception as e:
            # Fail open — availability > strict rate limiting
            logger.warning(
                "Rate limit check failed (DB error): %s — allowing request through",
                e,
            )
            return True

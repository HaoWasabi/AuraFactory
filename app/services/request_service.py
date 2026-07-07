"""RequestService — receives user input, enforces 1-active-request lock."""
import logging
import uuid
from datetime import datetime
from typing import Optional

from app.database import Database

logger = logging.getLogger(__name__)


class RequestService:
    """Handles request creation with concurrency lock (§5.3)."""

    def __init__(self, db: Database):
        self.db = db

    async def create_request(
        self,
        guild_id: int,
        user_id: int,
        message: str,
        origin: str = "discord",
        origin_channel_id: Optional[int] = None,
        session_id: Optional[str] = None,
    ) -> dict:
        """Create a new request after checking the active-request lock.

        Returns:
            {"ok": True, "request_id": ...} or {"ok": False, "reason": ...}
        """
        # Check if there's already an active request for this guild+user
        active = await self.db.fetchrow(
            """SELECT id, message, status FROM requests
               WHERE guild_id = $1 AND user_id = $2
               AND status IN ('planned', 'awaiting_approval', 'executing')
               LIMIT 1""",
            guild_id, user_id,
        )
        if active:
            return {
                "ok": False,
                "reason": "active_request_locked",
                "active_request_id": str(active["id"]),
            }

        # Insert new request
        request_id = uuid.uuid4()
        await self.db.execute(
            """INSERT INTO requests (id, session_id, guild_id, user_id, origin, origin_channel_id, message, status)
               VALUES ($1, $2, $3, $4, $5, $6, $7, 'received')""",
            request_id,
            uuid.UUID(session_id) if session_id else None,
            guild_id,
            user_id,
            origin,
            origin_channel_id,
            message,
        )
        logger.info("Created request %s for guild=%d user=%d", request_id, guild_id, user_id)
        return {"ok": True, "request_id": str(request_id)}

    async def update_status(self, request_id: str, status: str, **extra_fields) -> None:
        """Update request status and optional extra fields."""
        set_clauses = ["status = $2"]
        params = [uuid.UUID(request_id), status]
        idx = 3

        if status in ("completed", "failed", "cancelled"):
            set_clauses.append(f"completed_at = ${idx}")
            params.append(datetime.utcnow())
            idx += 1

        for key, value in extra_fields.items():
            set_clauses.append(f"{key} = ${idx}")
            params.append(value)
            idx += 1

        query = f"UPDATE requests SET {', '.join(set_clauses)} WHERE id = $1"
        await self.db.execute(query, *params)

    async def get_request(self, request_id: str) -> Optional[dict]:
        """Fetch a request by ID."""
        row = await self.db.fetchrow(
            "SELECT * FROM requests WHERE id = $1", uuid.UUID(request_id)
        )
        return dict(row) if row else None

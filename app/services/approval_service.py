"""ApprovalService — shared approval logic for web + Discord (§5.5)."""
import logging
import uuid
from datetime import datetime, timezone
from typing import Optional

from app.database import Database
from app.messages import msg

logger = logging.getLogger(__name__)


class ApprovalService:
    """Handles plan approval/rejection with idempotency and ownership validation."""

    def __init__(self, db: Database):
        self.db = db

    async def approve_plan(self, plan_id: str, approved_by_user_id: int, lang: str = "vi") -> dict:
        """Approve a plan for execution.

        Requirements:
        - Only the request creator can approve (§5.5 step 15)
        - Idempotent: double-approval returns ok without re-processing
        - Uses transaction for atomicity

        Args:
            plan_id: UUID of the plan to approve.
            approved_by_user_id: Discord user ID of the person approving.

        Returns:
            {"ok": True, "plan_id": ...} on success
            {"ok": False, "error": ...} on failure
        """
        plan_uuid = uuid.UUID(plan_id)

        async with self.db.transaction() as conn:
            # Fetch plan with FOR UPDATE lock to prevent race conditions
            plan = await conn.fetchrow(
                "SELECT id, request_id, user_id, status FROM plans WHERE id = $1 FOR UPDATE",
                plan_uuid,
            )

            if not plan:
                return {"ok": False, "error": msg("plan_not_found", lang=lang)}

            # Idempotent: already approved → return ok
            if plan["status"] == "approved":
                logger.info("Plan %s already approved — idempotent return", plan_id)
                return {"ok": True, "plan_id": plan_id, "already_approved": True}

            # Must be awaiting_approval
            if plan["status"] != "awaiting_approval":
                return {
                    "ok": False,
                    "error": msg("plan_not_pending", lang=lang, status=plan['status']),
                }

            # Verify ownership: only the request creator can approve
            if plan["user_id"] != approved_by_user_id:
                logger.warning(
                    "User %d attempted to approve plan %s owned by user %d",
                    approved_by_user_id, plan_id, plan["user_id"],
                )
                return {
                    "ok": False,
                    "error": msg("only_creator_can_approve", lang=lang),
                }

            now = datetime.now(timezone.utc)

            # Update plan status
            await conn.execute(
                """UPDATE plans
                   SET status = 'approved', approved_by = $2, approved_at = $3
                   WHERE id = $1""",
                plan_uuid,
                approved_by_user_id,
                now,
            )

            # Update request status to 'executing'
            await conn.execute(
                "UPDATE requests SET status = 'executing' WHERE id = $1",
                plan["request_id"],
            )

        logger.info("Plan %s approved by user %d", plan_id, approved_by_user_id)
        return {"ok": True, "plan_id": plan_id}

    async def reject_plan(
        self, plan_id: str, rejected_by_user_id: int, reason: Optional[str] = None, lang: str = "vi"
    ) -> dict:
        """Reject/cancel a plan.

        Requirements:
        - Only the request creator can reject
        - Idempotent: double-rejection returns ok
        - Sets plan to 'cancelled', request to 'cancelled'

        Args:
            plan_id: UUID of the plan to reject.
            rejected_by_user_id: Discord user ID of the person rejecting.
            reason: Optional rejection reason.

        Returns:
            {"ok": True} on success
            {"ok": False, "error": ...} on failure
        """
        plan_uuid = uuid.UUID(plan_id)

        async with self.db.transaction() as conn:
            # Fetch plan with lock
            plan = await conn.fetchrow(
                "SELECT id, request_id, user_id, status FROM plans WHERE id = $1 FOR UPDATE",
                plan_uuid,
            )

            if not plan:
                return {"ok": False, "error": msg("plan_not_found", lang=lang)}

            # Idempotent: already cancelled → return ok
            if plan["status"] == "cancelled":
                logger.info("Plan %s already cancelled — idempotent return", plan_id)
                return {"ok": True, "plan_id": plan_id, "already_cancelled": True}

            # Must be awaiting_approval
            if plan["status"] != "awaiting_approval":
                return {
                    "ok": False,
                    "error": msg("plan_not_pending", lang=lang, status=plan['status']),
                }

            # Verify ownership
            if plan["user_id"] != rejected_by_user_id:
                logger.warning(
                    "User %d attempted to reject plan %s owned by user %d",
                    rejected_by_user_id, plan_id, plan["user_id"],
                )
                return {
                    "ok": False,
                    "error": msg("only_creator_can_reject", lang=lang),
                }

            now = datetime.now(timezone.utc)

            # Update plan status
            await conn.execute(
                """UPDATE plans
                   SET status = 'cancelled', rejected_reason = $2, approved_at = $3
                   WHERE id = $1""",
                plan_uuid,
                reason or "",
                now,
            )

            # Update request status to 'cancelled'
            await conn.execute(
                "UPDATE requests SET status = 'cancelled', completed_at = $2 WHERE id = $1",
                plan["request_id"],
                now,
            )

        logger.info("Plan %s rejected by user %d — reason: %s", plan_id, rejected_by_user_id, reason)
        return {"ok": True, "plan_id": plan_id}

    async def get_pending_approval(self, guild_id: int, user_id: int) -> Optional[dict]:
        """Get the plan awaiting approval for a specific user in a guild.

        Used by both the web dashboard and Discord button handler.

        Args:
            guild_id: Discord guild ID.
            user_id: Discord user ID.

        Returns:
            Plan dict with steps if found, None otherwise.
        """
        plan = await self.db.fetchrow(
            """SELECT p.id, p.request_id, p.description, p.risk_level, p.status, p.created_at
               FROM plans p
               JOIN requests r ON r.id = p.request_id
               WHERE p.guild_id = $1 AND p.user_id = $2 AND p.status = 'awaiting_approval'
               ORDER BY p.created_at DESC
               LIMIT 1""",
            guild_id,
            user_id,
        )

        if not plan:
            return None

        # Fetch plan steps
        steps = await self.db.fetch(
            """SELECT step_number, tool_name, tool_params, description, risk_level
               FROM plan_steps
               WHERE plan_id = $1
               ORDER BY step_number ASC""",
            plan["id"],
        )

        return {
            "plan_id": str(plan["id"]),
            "request_id": str(plan["request_id"]),
            "description": plan["description"],
            "risk_level": plan["risk_level"],
            "status": plan["status"],
            "created_at": plan["created_at"].isoformat() if plan["created_at"] else None,
            "steps": [
                {
                    "step_number": s["step_number"],
                    "tool_name": s["tool_name"],
                    "tool_params": s["tool_params"],
                    "description": s["description"],
                    "risk_level": s["risk_level"],
                }
                for s in steps
            ],
        }

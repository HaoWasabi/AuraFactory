# app/gateway/pipeline.py
"""
GatewayPipeline — orchestrates all pre-processing checks before agents.
Message flow: Discord Layer → Gateway → Orchestrator (Agents).

Pipeline order:
1. rate_limit → 2. guardrails → 3. role_detection → 4. session_resolve → 5. cost_check

If ANY step fails, returns immediately with reason (short-circuit).
"""
import logging
from typing import Any, Optional
from dataclasses import dataclass, field

from app.models.messages import IncomingMessage
from app.gateway.rate_limiter import RateLimiter
from app.gateway.guardrails import Guardrails
from app.gateway.session_manager import SessionManager, Session
from app.gateway.cost_tracker import CostTracker

logger = logging.getLogger(__name__)


@dataclass
class GatewayResult:
    """Result of gateway processing."""
    passed: bool
    reason: str = ""
    session: Optional[Session] = None
    user_role: str = "member"
    trace_id: str = ""


class GatewayPipeline:
    """
    Processes incoming messages through the gateway control plane.

    Pipeline steps (in order):
    1. Rate Limiting — token bucket, 20 req/min/user
    2. Guardrails — prompt injection detection
    3. Role Detection — owner/admin/moderator/member
    4. Session Resolution — create or load session
    5. Cost Check — daily budget enforcement per guild

    If any step fails, return immediately with passed=False and reason.
    """

    def __init__(
        self,
        rate_limiter: Optional[RateLimiter] = None,
        guardrails: Optional[Guardrails] = None,
        session_manager: Optional[SessionManager] = None,
        cost_tracker: Optional[CostTracker] = None,
        db: Any = None,
    ) -> None:
        self._rate_limiter = rate_limiter or RateLimiter()
        self._guardrails = guardrails or Guardrails()
        self._session_manager = session_manager or SessionManager(db=db)
        self._cost_tracker = cost_tracker or CostTracker(db=db)

    async def process(self, message: IncomingMessage) -> GatewayResult:
        """
        Run the full gateway pipeline on an incoming message.

        Args:
            message: Standardized incoming message from Discord/API.

        Returns:
            GatewayResult with passed=True if message passes all checks,
            or passed=False with reason if any check fails.
        """
        user_id = message.user_id
        guild_id = message.guild_id

        # ─── Step 1: Rate Limiting ───
        allowed, retry_after = self._rate_limiter.check(user_id)
        if not allowed:
            logger.warning(f"Rate limited user {user_id}: retry_after={retry_after:.1f}s")
            return GatewayResult(
                passed=False,
                reason=f"Bạn đang gửi tin nhắn quá nhanh. Vui lòng đợi {retry_after:.0f} giây.",
            )

        # ─── Step 2: Guardrails (Prompt Injection Detection) ───
        safe, guardrail_reason = self._guardrails.check(message.prompt)
        if not safe:
            logger.warning(f"Guardrails blocked user {user_id}: {guardrail_reason}")
            return GatewayResult(
                passed=False,
                reason="Tin nhắn bị từ chối vì lý do an toàn.",
            )

        # ─── Step 3: Role Detection ───
        # Use guild object from metadata if available, otherwise use message flags
        guild = message.metadata.get("guild_object")
        if guild:
            user_role = self._session_manager.detect_user_role(user_id, guild)
        else:
            # Fallback: use IncomingMessage flags
            user_role = self._detect_role_from_message(message)

        # ─── Step 4: Session Resolution ───
        session = await self._session_manager.resolve_session(
            user_id=user_id,
            guild_id=guild_id,
            channel_id=message.channel_id,
        )
        session.user_role = user_role

        # ─── Step 5: Cost Check ───
        if guild_id:
            budget_ok, remaining = self._cost_tracker.check_budget(guild_id)
            if not budget_ok:
                logger.warning(f"Budget exceeded for guild {guild_id}")
                return GatewayResult(
                    passed=False,
                    reason="Server đã đạt giới hạn sử dụng hôm nay. Vui lòng thử lại ngày mai.",
                    session=session,
                    user_role=user_role,
                )

        # ─── All checks passed ───
        logger.debug(
            f"Gateway passed: user={user_id}, role={user_role}, "
            f"session={session.session_id}"
        )
        return GatewayResult(
            passed=True,
            session=session,
            user_role=user_role,
        )

    def _detect_role_from_message(self, message: IncomingMessage) -> str:
        """
        Fallback role detection from IncomingMessage flags.
        Used when guild object is not available in metadata.
        """
        if message.is_admin:
            return "admin"

        # Check for moderator-like roles in user_roles list
        mod_keywords = ("mod", "moderator", "staff", "helper")
        for role_name in message.user_roles:
            if any(kw in role_name.lower() for kw in mod_keywords):
                return "moderator"

        return "member"

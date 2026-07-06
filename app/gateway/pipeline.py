# app/gateway/pipeline.py
"""
GatewayPipeline — orchestrates all pre-processing checks.
Message flows: Channel → Gateway → Orchestrator.

v2 additions:
- Role detection (admin/mod/member)
- Source context detection (DM, #aura-admin, public channel)
"""
import logging
from typing import Any, Optional
from dataclasses import dataclass, field

from app.models.messages import IncomingMessage
from app.gateway.guardrails import check_injection
from app.gateway.rate_limiter import RateLimiter
from app.gateway.session_manager import SessionManager

logger = logging.getLogger(__name__)


# Admin channel name (created during setup)
ADMIN_CHANNEL_NAME = "aura-admin"


@dataclass
class GatewayContext:
    """Enriched context attached to a message after gateway processing."""
    session_id: str = ""
    trace_id: str = ""
    user_role: str = "member"  # "admin", "moderator", "member"
    source_context: str = "public"  # "admin_channel", "dm", "public"
    is_first_time_guild: bool = False
    memory_context: Any = None  # Injected by Orchestrator after recall


@dataclass
class GatewayResult:
    """Result of gateway processing."""
    allowed: bool
    message: Optional[IncomingMessage] = None
    context: Optional[GatewayContext] = None
    rejection_reason: str = ""


class GatewayPipeline:
    """
    Processes incoming messages through safety + context enrichment:
    1. Rate limiting
    2. Guardrails (prompt injection detection)
    3. Role detection (admin/mod/member)
    4. Source context detection
    5. Session resolution
    6. Input sanitization
    """

    def __init__(
        self,
        rate_limiter: Optional[RateLimiter] = None,
        session_manager: Optional[SessionManager] = None,
        tracer=None,
    ):
        self._rate_limiter = rate_limiter or RateLimiter()
        self._session_manager = session_manager or SessionManager()
        self._tracer = tracer

    async def process(self, message: IncomingMessage) -> GatewayResult:
        """
        Run the full gateway pipeline on an incoming message.
        Returns GatewayResult with allowed=True if message passes all checks.
        """
        trace_id = self._tracer.new_trace() if self._tracer else "no-trace"

        # 1. Rate limiting
        allowed, _wait = self._rate_limiter.allow(message.user_id)
        if not allowed:
            logger.warning(f"[{trace_id}] Rate limited: {message.user_id}")
            return GatewayResult(
                allowed=False,
                rejection_reason="Bạn đang gửi tin nhắn quá nhanh. Vui lòng đợi một chút.",
            )

        # 2. Guardrails (prompt injection)
        is_safe, guardrail_msg = check_injection(message.prompt)
        if not is_safe:
            logger.warning(f"[{trace_id}] Guardrail blocked: {guardrail_msg}")
            if self._tracer:
                self._tracer.log_security(trace_id, "prompt_injection", guardrail_msg)
            return GatewayResult(
                allowed=False,
                rejection_reason="Tin nhắn bị từ chối vì lý do an toàn.",
            )

        # 3. Input sanitization
        message.prompt = self._sanitize_input(message.prompt)

        # 4. Role detection
        user_role = self._detect_role(message)

        # 5. Source context detection
        source_context = self._detect_source_context(message)

        # 6. Session resolution
        session_id = await self._session_manager.get_or_create_session(
            user_id=message.user_id,
            guild_id=message.guild_id,
            channel_id=message.channel_id,
        )

        # Build enriched context
        context = GatewayContext(
            session_id=session_id,
            trace_id=trace_id,
            user_role=user_role,
            source_context=source_context,
        )

        return GatewayResult(
            allowed=True,
            message=message,
            context=context,
        )

    def _detect_role(self, message: IncomingMessage) -> str:
        """
        Determine user's effective role for permission gating.
        Priority: admin > moderator > member
        """
        if message.is_admin:
            return "admin"

        # Check for moderator-like roles
        mod_keywords = ("mod", "moderator", "staff", "helper")
        for role_name in message.user_roles:
            if any(kw in role_name.lower() for kw in mod_keywords):
                return "moderator"

        return "member"

    def _detect_source_context(self, message: IncomingMessage) -> str:
        """
        Detect where the message came from for routing hints.
        - "admin_channel": Message from #aura-admin channel
        - "dm": Direct message to bot
        - "public": Regular public channel
        """
        channel_name = message.metadata.get("channel_name", "")
        is_dm = message.metadata.get("is_dm", False)

        if is_dm:
            return "dm"
        if channel_name == ADMIN_CHANNEL_NAME:
            return "admin_channel"
        return "public"

    def _sanitize_input(self, text: str) -> str:
        """Strip control characters and limit length."""
        # Remove null bytes and control chars (except newlines)
        sanitized = "".join(
            c for c in text if c == "\n" or c == "\t" or (ord(c) >= 32)
        )
        # Limit to reasonable length
        max_length = 4000
        if len(sanitized) > max_length:
            sanitized = sanitized[:max_length] + "..."
        return sanitized.strip()

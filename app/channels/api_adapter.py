# app/channels/api_adapter.py
"""
API Channel Adapter — FastAPI router for REST API interactions.
Provides: chat, approvals (HITL), and health endpoints.
All endpoints require valid session (Authorization header or session cookie).
"""
import logging
import time
from typing import Optional
from dataclasses import dataclass

from fastapi import APIRouter, Request, HTTPException, Depends
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from app.channels.base import ChannelAdapterBase
from app.models.messages import IncomingMessage, OutgoingMessage

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1", tags=["api"])


# ================================================================
# Request/Response Models
# ================================================================

class ChatRequest(BaseModel):
    """Chat message request."""
    message: str = Field(..., min_length=1, max_length=4000)
    guild_id: Optional[int] = None
    channel_id: Optional[int] = None


class ChatResponse(BaseModel):
    """Chat response."""
    content: str
    trace_id: str
    mode: Optional[str] = None
    metadata: dict = Field(default_factory=dict)


class ApprovalItem(BaseModel):
    """Pending approval item."""
    id: str
    action: str
    description: str
    risk_level: str
    steps: list = Field(default_factory=list)
    created_at: str
    guild_id: int
    requested_by: str


class ApprovalAction(BaseModel):
    """Approval/rejection response."""
    success: bool
    message: str


class HealthResponse(BaseModel):
    """Health check response."""
    status: str
    uptime_seconds: float
    version: str = "1.0.0"


# ================================================================
# Rate Limiting (simple in-memory per IP)
# ================================================================

_rate_limit_store: dict = {}  # ip -> (count, window_start)
RATE_LIMIT_WINDOW = 60  # seconds
RATE_LIMIT_MAX = 30  # max requests per window


def _check_rate_limit(client_ip: str) -> bool:
    """Return True if request is allowed, False if rate limited."""
    now = time.time()
    if client_ip not in _rate_limit_store:
        _rate_limit_store[client_ip] = (1, now)
        return True

    count, window_start = _rate_limit_store[client_ip]
    if now - window_start > RATE_LIMIT_WINDOW:
        _rate_limit_store[client_ip] = (1, now)
        return True

    if count >= RATE_LIMIT_MAX:
        return False

    _rate_limit_store[client_ip] = (count + 1, window_start)
    return True


# ================================================================
# Auth Dependency
# ================================================================

async def get_current_user(request: Request) -> dict:
    """
    Extract and validate current user from session.
    Checks Authorization header first, then session cookie.
    """
    app = request.app

    # Check Authorization header (Bearer token = session_id)
    auth_header = request.headers.get("Authorization", "")
    session_id = None

    if auth_header.startswith("Bearer "):
        session_id = auth_header[7:]
    else:
        # Check session cookie
        session_id = request.cookies.get("session_id")

    if not session_id:
        raise HTTPException(status_code=401, detail="Chưa đăng nhập. Vui lòng đăng nhập.")

    # Validate session
    session_store = getattr(app.state, "session_store", {})
    user_data = session_store.get(session_id)
    if not user_data:
        raise HTTPException(status_code=401, detail="Phiên đã hết hạn. Vui lòng đăng nhập lại.")

    return user_data


# ================================================================
# Endpoints
# ================================================================

@router.post("/chat", response_model=ChatResponse)
async def chat_endpoint(
    body: ChatRequest,
    request: Request,
    user: dict = Depends(get_current_user),
):
    """
    Process a chat message via the AuraFactory pipeline.
    Returns the agent response.
    """
    # Rate limit check
    client_ip = request.client.host if request.client else "unknown"
    if not _check_rate_limit(client_ip):
        raise HTTPException(
            status_code=429,
            detail="Bạn đang gửi tin nhắn quá nhanh. Vui lòng đợi một chút.",
        )

    # Build IncomingMessage
    incoming = IncomingMessage(
        user_id=user.get("id", "unknown"),
        user_name=user.get("username", "Unknown"),
        prompt=body.message,
        user_roles=user.get("roles", []),
        is_admin=user.get("is_admin", False),
        guild_id=body.guild_id,
        channel_id=body.channel_id,
        source="api",
        metadata={"web_session": True},
    )

    # Process through pipeline
    process_fn = request.app.state.process_message
    try:
        response: OutgoingMessage = await process_fn(incoming)
        return ChatResponse(
            content=response.content,
            trace_id=response.trace_id,
            mode=response.metadata.get("mode"),
            metadata=response.metadata,
        )
    except Exception as e:
        logger.error(f"API chat error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Lỗi xử lý tin nhắn.")


@router.get("/approvals")
async def list_approvals(
    request: Request,
    guild_id: Optional[int] = None,
    user: dict = Depends(get_current_user),
):
    """List pending approvals for a guild."""
    approval_store = getattr(request.app.state, "approval_store", {})

    # Filter by guild if specified
    effective_guild = guild_id or user.get("current_guild_id")
    pending = []

    for approval_id, item in approval_store.items():
        if item.get("status") != "pending":
            continue
        if effective_guild and item.get("guild_id") != effective_guild:
            continue
        pending.append({
            "id": approval_id,
            "action": item.get("action", ""),
            "description": item.get("description", ""),
            "risk_level": item.get("risk_level", "MEDIUM"),
            "steps": item.get("steps", []),
            "created_at": item.get("created_at", ""),
            "guild_id": item.get("guild_id", 0),
            "requested_by": item.get("requested_by", ""),
        })

    return {"approvals": pending, "count": len(pending)}


@router.post("/approve/{approval_id}", response_model=ApprovalAction)
async def approve_action(
    approval_id: str,
    request: Request,
    user: dict = Depends(get_current_user),
):
    """Approve a pending action."""
    if not user.get("is_admin", False):
        raise HTTPException(status_code=403, detail="Chỉ admin mới có thể phê duyệt.")

    approval_store = getattr(request.app.state, "approval_store", {})
    item = approval_store.get(approval_id)

    if not item:
        raise HTTPException(status_code=404, detail="Không tìm thấy yêu cầu phê duyệt.")

    if item.get("status") != "pending":
        raise HTTPException(status_code=400, detail="Yêu cầu này đã được xử lý.")

    # Mark as approved
    item["status"] = "approved"
    item["approved_by"] = user.get("id")

    # Trigger execution callback if exists
    execute_fn = item.get("execute_callback")
    if execute_fn and callable(execute_fn):
        try:
            await execute_fn()
        except Exception as e:
            logger.error(f"Approval execution error: {e}")
            item["status"] = "error"
            return ApprovalAction(success=False, message=f"Phê duyệt thành công nhưng thực thi lỗi: {e}")

    logger.info(f"✅ Approved: {approval_id} by {user.get('username')}")
    return ApprovalAction(success=True, message="Đã phê duyệt thành công.")


@router.post("/reject/{approval_id}", response_model=ApprovalAction)
async def reject_action(
    approval_id: str,
    request: Request,
    user: dict = Depends(get_current_user),
):
    """Reject a pending action."""
    if not user.get("is_admin", False):
        raise HTTPException(status_code=403, detail="Chỉ admin mới có thể từ chối.")

    approval_store = getattr(request.app.state, "approval_store", {})
    item = approval_store.get(approval_id)

    if not item:
        raise HTTPException(status_code=404, detail="Không tìm thấy yêu cầu phê duyệt.")

    if item.get("status") != "pending":
        raise HTTPException(status_code=400, detail="Yêu cầu này đã được xử lý.")

    # Mark as rejected
    item["status"] = "rejected"
    item["rejected_by"] = user.get("id")

    logger.info(f"❌ Rejected: {approval_id} by {user.get('username')}")
    return ApprovalAction(success=True, message="Đã từ chối yêu cầu.")


@router.get("/health", response_model=HealthResponse)
async def health_check(request: Request):
    """API health check — no auth required."""
    start_time = getattr(request.app.state, "start_time", time.time())
    uptime = time.time() - start_time
    return HealthResponse(
        status="healthy",
        uptime_seconds=round(uptime, 2),
    )


# ================================================================
# Adapter Class (wraps router for DI)
# ================================================================

class APIAdapter(ChannelAdapterBase):
    """
    API adapter — wraps the FastAPI router.
    Provides programmatic access to chat and approval endpoints.
    """

    def __init__(self):
        self._router = router

    @property
    def router(self) -> APIRouter:
        """Get the FastAPI router to include in the app."""
        return self._router

    async def receive(self, raw_input: dict) -> IncomingMessage:
        """Convert raw API dict to IncomingMessage."""
        return IncomingMessage(
            user_id=raw_input.get("user_id", "api-user"),
            user_name=raw_input.get("user_name", "API User"),
            prompt=raw_input.get("message", ""),
            guild_id=raw_input.get("guild_id"),
            channel_id=raw_input.get("channel_id"),
            source="api",
        )

    async def send(self, message: OutgoingMessage, destination=None) -> None:
        """API responses are returned directly — no push needed."""
        pass

    async def start(self) -> None:
        """API adapter starts with FastAPI — nothing to do here."""
        logger.info("📡 API adapter ready (included in FastAPI)")

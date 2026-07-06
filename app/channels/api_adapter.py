# app/channels/api_adapter.py
"""
API Channel Adapter — FastAPI router for REST API interactions.
Provides: chat, approvals (HITL), settings, and health endpoints.
All endpoints require valid session (Authorization header or session cookie).
"""
import logging
import time
from typing import Optional
from dataclasses import dataclass

from fastapi import APIRouter, Request, HTTPException, Depends
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from itsdangerous import URLSafeTimedSerializer, BadSignature, SignatureExpired
from app.config.settings import settings

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
    guild_id: Optional[str] = None
    channel_id: Optional[str] = None


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
    guild_id: str
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


class SettingsRequest(BaseModel):
    """Settings update request."""
    guild_id: str
    assistant_enabled: Optional[bool] = None


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

_serializer = URLSafeTimedSerializer(settings.secret_key)
SESSION_MAX_AGE = 7 * 24 * 3600

# In-memory settings store (guild_id -> settings dict)
_guild_settings_store: dict = {}


async def get_current_user(request: Request) -> dict:
    """
    Extract and validate current user from session.
    Checks Authorization header first, then session cookie.
    """
    app = request.app

    # Check Authorization header (Bearer = session_id)
    auth_header = request.headers.get("Authorization", "")
    session_id = None

    if auth_header.startswith("Bearer "):
        session_id = auth_header[7:]
    else:
        # Check session cookie
        signed_cookie = request.cookies.get("session_id")
        if signed_cookie:
            try:
                session_id = _serializer.loads(signed_cookie, max_age=SESSION_MAX_AGE)
            except (BadSignature, SignatureExpired):
                raise HTTPException(status_code=401, detail="Phiên đã hết hạn. Vui lòng đăng nhập lại.")

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

    # Convert guild_id to int if possible for pipeline compatibility
    guild_id = None
    if body.guild_id:
        try:
            guild_id = int(body.guild_id)
        except (ValueError, TypeError):
            guild_id = body.guild_id

    channel_id = None
    if body.channel_id:
        try:
            channel_id = int(body.channel_id)
        except (ValueError, TypeError):
            channel_id = body.channel_id

    # FIX #3: Web dashboard users are ALWAYS admin
    # They authenticated via Discord OAuth — only admins use the dashboard
    incoming = IncomingMessage(
        user_id=user.get("id", "unknown"),
        user_name=user.get("username", "Unknown"),
        prompt=body.message,
        user_roles=["admin"],  # Web users always get admin role
        is_admin=True,  # Web dashboard users are always admin
        guild_id=guild_id,
        channel_id=channel_id,
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
    guild_id: Optional[str] = None,
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
        if effective_guild:
            item_guild = str(item.get("guild_id", ""))
            if item_guild != str(effective_guild):
                continue
        pending.append({
            "id": approval_id,
            "action": item.get("action", ""),
            "description": item.get("description", ""),
            "risk_level": item.get("risk_level", "MEDIUM"),
            "steps": item.get("steps", []),
            "created_at": item.get("created_at", ""),
            "guild_id": item.get("guild_id", ""),
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
    # Web users are always admin — no need to check is_admin flag
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
    # Web users are always admin — no need to check is_admin flag
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


@router.post("/settings")
async def update_settings(
    body: SettingsRequest,
    request: Request,
    user: dict = Depends(get_current_user),
):
    """
    FIX #5: Update guild settings (e.g., assistant mode toggle).
    Stores in memory for now — persists until restart.
    """
    guild_id = body.guild_id

    # Get or create settings for this guild
    if guild_id not in _guild_settings_store:
        _guild_settings_store[guild_id] = {
            "assistant_enabled": True,
        }

    if body.assistant_enabled is not None:
        _guild_settings_store[guild_id]["assistant_enabled"] = body.assistant_enabled

    logger.info(f"⚙️ Settings updated for guild {guild_id}: {_guild_settings_store[guild_id]}")

    return JSONResponse({
        "success": True,
        "guild_id": guild_id,
        "settings": _guild_settings_store[guild_id],
    })


@router.get("/settings/{guild_id}")
async def get_settings(
    guild_id: str,
    request: Request,
    user: dict = Depends(get_current_user),
):
    """Get guild settings."""
    guild_settings = _guild_settings_store.get(guild_id, {
        "assistant_enabled": True,
    })

    return JSONResponse({
        "guild_id": guild_id,
        "settings": guild_settings,
    })


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

# app/channels/api_adapter.py
"""
REST API Channel Adapter — FastAPI routes for programmatic access.
"""
import logging
import os
from typing import Callable, Awaitable, Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from app.channels.base import ChannelAdapterBase
from app.models.messages import IncomingMessage, OutgoingMessage

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1", tags=["chat"])


# === Pydantic models for API ===

class ChatRequest(BaseModel):
    """Chat API request body."""
    message: str
    user_id: str = "api_user"
    user_name: str = "API User"
    guild_id: Optional[int] = None
    channel_id: Optional[int] = None


class ChatResponse(BaseModel):
    """Chat API response body."""
    content: str
    trace_id: str
    status: str = "success"


class UpdateGeminiTokenRequest(BaseModel):
    """Request body for updating the Gemini API token at runtime."""
    api_key: str


class UpdateGeminiTokenResponse(BaseModel):
    """Response after updating the Gemini API token."""
    status: str
    message: str


# === Adapter ===

class APIAdapter(ChannelAdapterBase):
    """REST API adapter — exposes chat via HTTP endpoints."""

    def __init__(self):
        self._handler: Optional[Callable[[IncomingMessage], Awaitable[OutgoingMessage]]] = None

    @property
    def name(self) -> str:
        return "api"

    async def start(self) -> None:
        """No-op for API adapter (routes are registered with FastAPI app)."""
        pass

    async def stop(self) -> None:
        """No-op for API adapter."""
        pass

    async def send(self, message: OutgoingMessage) -> None:
        """No-op — API responses are returned directly."""
        pass

    def get_router(self) -> APIRouter:
        """Get the FastAPI router with all API endpoints."""
        return router


# === Singleton ===
api_adapter = APIAdapter()


# === Routes ===

@router.post("/chat", response_model=ChatResponse)
async def chat_endpoint(request: ChatRequest):
    """Send a message and get AI response."""
    if not api_adapter._handler:
        raise HTTPException(status_code=503, detail="Chat service not ready")

    incoming = IncomingMessage(
        user_id=request.user_id,
        user_name=request.user_name,
        prompt=request.message,
        guild_id=request.guild_id,
        channel_id=request.channel_id,
        source="api",
    )

    try:
        response = await api_adapter._handler(incoming)
        return ChatResponse(
            content=response.content,
            trace_id=response.trace_id,
        )
    except Exception as e:
        logger.error(f"API chat error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/health")
async def health():
    """API health check."""
    return {"status": "healthy", "channel": "api"}


@router.post(
    "/config/gemini-token",
    response_model=UpdateGeminiTokenResponse,
    tags=["config"],
    summary="Cập nhật Gemini API token tại runtime",
)
async def update_gemini_token(body: UpdateGeminiTokenRequest, request: Request):
    """
    Cập nhật Gemini API key mà không cần restart server.

    - Lưu key vào os.environ để các provider mới dùng được.
    - Nếu LLM hiện tại là GeminiProvider thì reinit luôn.
    - Nếu LLM hiện tại là provider khác, chuyển sang Gemini.
    """
    api_key = body.api_key.strip()
    if not api_key:
        raise HTTPException(status_code=400, detail="api_key không được để trống.")

    # Cập nhật env runtime
    os.environ["GEMINI_API_KEY"] = api_key

    # Truy cập container từ app.state
    from app.main import container  # noqa: PLC0415

    try:
        # Lấy model_id hiện tại nếu đang dùng Gemini, ngược lại dùng default
        current_model = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
        if container.llm is not None:
            try:
                from app.infra.llm.gemini import GeminiProvider  # noqa: PLC0415
                if isinstance(container.llm, GeminiProvider):
                    current_model = container.llm.model_name
            except Exception:
                pass

        from app.infra.llm.gemini import GeminiProvider  # noqa: PLC0415

        new_provider = GeminiProvider(api_key=api_key, model_id=current_model)
        container.llm = new_provider

        # Cập nhật tất cả agents đang dùng llm
        for agent_attr in ("orchestrator", "admin_agent", "assistant_agent"):
            agent = getattr(container, agent_attr, None)
            if agent is not None and hasattr(agent, "_llm"):
                agent._llm = new_provider

        # Cập nhật FastTrackExecutor nếu có
        # (stored inside orchestrator._fast_track)
        orch = getattr(container, "orchestrator", None)
        if orch is not None and hasattr(orch, "_fast_track") and orch._fast_track is not None:
            if hasattr(orch._fast_track, "_llm"):
                orch._fast_track._llm = new_provider

        # Cập nhật specialist agents trong admin_agent (vd: architect)
        admin = getattr(container, "admin_agent", None)
        if admin is not None and hasattr(admin, "_specialists"):
            for specialist in admin._specialists.values():
                if hasattr(specialist, "_llm"):
                    specialist._llm = new_provider

        logger.info("Gemini API token updated successfully at runtime.")
        return UpdateGeminiTokenResponse(
            status="success",
            message=f"Đã cập nhật Gemini token và reinit provider (model: {current_model}).",
        )

    except Exception as e:
        logger.error(f"Failed to update Gemini token: {e}")
        raise HTTPException(status_code=500, detail=f"Lỗi khi cập nhật token: {e}")

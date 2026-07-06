# app/channels/api_adapter.py
"""
REST API Channel Adapter — FastAPI routes for programmatic access.
"""
import logging
from typing import Callable, Awaitable, Optional

from fastapi import APIRouter, HTTPException
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

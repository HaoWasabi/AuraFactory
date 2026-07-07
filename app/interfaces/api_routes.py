"""FastAPI REST API routes for AuraFactory web dashboard."""
import logging
import secrets
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel

logger = logging.getLogger(__name__)


# === Request/Response schemas ===
class ChatRequest(BaseModel):
    message: str
    guild_id: int
    user_id: int

class ApprovalRequest(BaseModel):
    plan_id: str
    action: str  # "approve" or "reject"
    user_id: int
    reason: Optional[str] = None


def create_api_router(services: dict) -> APIRouter:
    """Create API router with injected services."""
    router = APIRouter(prefix="/api", tags=["api"])

    auth_service = services["auth_service"]
    guild_sync_service = services["guild_sync_service"]
    request_service = services["request_service"]
    classifier_service = services["classifier_service"]
    planner_service = services["planner_service"]
    approval_service = services["approval_service"]
    executor_service = services["executor_service"]
    query_service = services["query_service"]

    # === Auth endpoints (§5.1) ===

    @router.get("/auth/login")
    async def login():
        """Start Discord OAuth2 flow. Returns redirect URL."""
        state = secrets.token_urlsafe(32)
        url = auth_service.get_oauth_url(state)
        return {"url": url, "state": state}

    @router.get("/auth/callback")
    async def oauth_callback(code: str, state: str):
        """Handle OAuth2 callback. Returns user info + session token."""
        user = await auth_service.exchange_code(code)
        if not user:
            raise HTTPException(status_code=401, detail="OAuth failed")
        # Sync guilds
        guilds = await guild_sync_service.sync_user_guilds(
            user["discord_user_id"], user["access_token"]
        )
        return {
            "user": {
                "id": user["discord_user_id"],
                "username": user["username"],
                "avatar": user["avatar"],
            },
            "guilds": guilds,
            "token": user["access_token"],  # In production: use JWT
        }

    @router.get("/auth/guilds")
    async def get_guilds(user_id: int):
        """Get cached guild list for user."""
        guilds = await guild_sync_service.get_user_guilds(user_id)
        return {"guilds": guilds}

    @router.get("/auth/bot-invite")
    async def bot_invite(guild_id: int):
        """Get bot invite URL for a specific guild."""
        url = guild_sync_service.get_bot_invite_url(guild_id)
        return {"url": url}

    # === Chat / Pipeline endpoints (§5.3-5.6) ===

    @router.post("/chat")
    async def chat(req: ChatRequest):
        """Main chat endpoint — same pipeline as Discord bot.
        
        Flow: request → classify → plan/query → execute (if auto-approve)
        """
        # Create request
        req_result = await request_service.create_request(
            guild_id=req.guild_id,
            user_id=req.user_id,
            message=req.message,
            origin="web",
        )
        if not req_result["ok"]:
            return {"ok": False, "error": req_result["reason"]}

        request_id = req_result["request_id"]

        # Classify
        classification = await classifier_service.classify(req.message)
        intent = classification["intent"]
        tool_mode = classification["tool_mode"]
        await request_service.update_status(request_id, "classified", intent=intent, tool_mode=tool_mode)

        # Route by intent
        if intent == "query":
            answer = await query_service.answer(req.message, req.guild_id)
            await request_service.update_status(request_id, "completed", response=answer)
            return {"ok": True, "type": "answer", "content": answer, "request_id": request_id}

        if intent in ("clarify", "out_of_scope"):
            msg = ("Bạn có thể mô tả cụ thể hơn?" if intent == "clarify"
                   else "Yêu cầu nằm ngoài phạm vi AuraFactory.")
            await request_service.update_status(request_id, "completed", response=msg)
            return {"ok": True, "type": "clarify", "content": msg, "request_id": request_id}

        # Action intents → plan
        plan_result = await planner_service.create_plan(request_id, req.message, req.guild_id, intent)
        if not plan_result.get("ok"):
            return {"ok": False, "error": plan_result.get("error", "Planning failed")}

        plan = plan_result["plan"]
        plan_id = plan["id"]

        if plan["risk_level"] in ("HIGH", "CRITICAL"):
            # Needs approval
            return {
                "ok": True,
                "type": "approval_needed",
                "plan": plan,
                "request_id": request_id,
            }
        else:
            # Auto-approved → execute
            exec_result = await executor_service.execute_plan(plan_id)
            status = "completed" if exec_result.get("status") == "completed" else "partial"
            return {
                "ok": True,
                "type": "executed",
                "status": status,
                "result": exec_result,
                "request_id": request_id,
            }

    # === Approval endpoints (§5.5) ===

    @router.post("/approval")
    async def handle_approval(req: ApprovalRequest):
        """Approve or reject a plan from web dashboard."""
        if req.action == "approve":
            result = await approval_service.approve_plan(req.plan_id, req.user_id)
            if result["ok"]:
                # Execute after approval
                exec_result = await executor_service.execute_plan(req.plan_id)
                return {"ok": True, "execution": exec_result}
            return result
        elif req.action == "reject":
            return await approval_service.reject_plan(req.plan_id, req.user_id, req.reason or "Rejected via web")
        else:
            raise HTTPException(status_code=400, detail="action must be 'approve' or 'reject'")

    @router.get("/approval/pending")
    async def get_pending(guild_id: int, user_id: int):
        """Get pending approval for a user in a guild."""
        plan = await approval_service.get_pending_approval(guild_id, user_id)
        return {"plan": plan}

    # === Health ===

    @router.get("/health")
    async def health():
        return {"status": "ok", "service": "AuraFactory"}

    return router

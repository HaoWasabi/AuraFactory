"""FastAPI REST API routes for AuraFactory web dashboard."""
import logging
import secrets
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel

from app.messages import msg

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
        """Get cached guild list for user.
        
        Returns guilds split into:
        - ready: bot_installed = True → can use immediately
        - pending: bot_installed = False → needs bot invite
        Each guild includes invite_url for easy activation.
        """
        guilds = await guild_sync_service.get_user_guilds(user_id)
        
        ready = []
        pending = []
        for g in guilds:
            g["invite_url"] = guild_sync_service.get_bot_invite_url(g["guild_id"])
            if g.get("bot_installed"):
                ready.append(g)
            else:
                pending.append(g)
        
        return {
            "ready": ready,
            "pending": pending,
            "total": len(guilds),
        }

    @router.get("/auth/bot-invite")
    async def bot_invite(guild_id: int):
        """Get bot invite URL for a specific guild."""
        url = guild_sync_service.get_bot_invite_url(guild_id)
        return {"url": url, "guild_id": guild_id}

    # === Chat / Pipeline endpoints (§5.3-5.6) ===

    @router.post("/chat")
    async def chat(req: ChatRequest):
        """Main chat endpoint — same pipeline as Discord bot.
        
        Flow: check bot → request → classify → plan/query → execute (if auto-approve)
        """
        # §5.1 step 3: Check bot is installed in this guild
        bot_row = await guild_sync_service.db.fetchrow(
            "SELECT is_active FROM bot_installs WHERE guild_id = $1 AND is_active = TRUE",
            req.guild_id,
        )
        if not bot_row:
            invite_url = guild_sync_service.get_bot_invite_url(req.guild_id)
            return {
                "ok": False,
                "type": "bot_not_installed",
                "error": msg("bot_not_installed", lang="vi", invite_url=invite_url),
                "invite_url": invite_url,
            }

        # Create request
        req_result = await request_service.create_request(
            guild_id=req.guild_id,
            user_id=req.user_id,
            message=req.message,
            origin="web",
        )
        if not req_result["ok"]:
            return {"ok": False, "type": "locked", "error": msg("request_locked", lang="vi")}

        request_id = req_result["request_id"]

        # Classify
        classification = await classifier_service.classify(req.message)
        intent = classification["intent"]
        tool_mode = classification["tool_mode"]
        lang = classification.get("lang", "vi")
        await request_service.update_status(request_id, "classified", intent=intent, tool_mode=tool_mode)

        # Route by intent
        if intent == "query":
            answer = await query_service.answer(req.message, req.guild_id)
            await request_service.update_status(request_id, "completed", response=answer)
            return {"ok": True, "type": "answer", "content": answer, "request_id": request_id}

        if intent in ("clarify", "out_of_scope"):
            reply = msg(intent, lang=lang)
            await request_service.update_status(request_id, "completed", response=reply)
            return {"ok": True, "type": "clarify", "content": reply, "request_id": request_id}

        # Action intents → plan
        plan_result = await planner_service.generate_plan(
            request_id=request_id,
            guild_id=req.guild_id,
            user_id=req.user_id,
            message=req.message,
            intent=intent,
        )
        if not plan_result.get("ok"):
            return {"ok": False, "error": plan_result.get("error", "Planning failed")}

        plan_id = plan_result["plan_id"]

        if plan_result["risk_level"] in ("HIGH", "CRITICAL"):
            # Needs approval
            return {
                "ok": True,
                "type": "approval_needed",
                "plan_id": plan_id,
                "plan": plan_result,
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

    # === Guild status ===

    @router.get("/guild/{guild_id}/status")
    async def guild_status(guild_id: int):
        """Check if bot is installed and active in a guild.
        Returns bot status + invite URL if not installed.
        """
        bot_row = await guild_sync_service.db.fetchrow(
            "SELECT is_active, installed_at FROM bot_installs WHERE guild_id = $1",
            guild_id,
        )
        if bot_row and bot_row["is_active"]:
            return {
                "bot_installed": True,
                "installed_at": bot_row["installed_at"].isoformat() if bot_row["installed_at"] else None,
            }
        return {
            "bot_installed": False,
            "invite_url": guild_sync_service.get_bot_invite_url(guild_id),
            "message": msg("bot_not_installed_short", lang="vi"),
        }

    # === Health ===

    @router.get("/health")
    async def health():
        return {"status": "ok", "service": "AuraFactory"}

    return router

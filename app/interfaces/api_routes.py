"""FastAPI REST API routes for AuraFactory web dashboard."""
import asyncio
import logging
import secrets
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel

from app.messages import msg, msg_for_quota_error

logger = logging.getLogger(__name__)


# === Request/Response schemas ===
class ChatRequest(BaseModel):
    message: str
    guild_id: str  # String to preserve Discord snowflake precision
    user_id: str   # String to preserve Discord snowflake precision
    session_id: Optional[str] = None  # Continue existing session or None for new

class ApprovalRequest(BaseModel):
    plan_id: str
    action: str  # "approve" or "reject"
    user_id: str  # String to preserve Discord snowflake precision
    reason: Optional[str] = None


class CommunityUpgradeRequest(BaseModel):
    """Payload when user confirms or declines the Community upgrade prompt."""
    action: str           # "confirm" or "decline"
    user_id: str
    community_payload: dict  # Exact community_payload from execute_plan response


async def _run_execution_background(executor_service, plan_id: str) -> None:
    """Run plan execution as background task — never raises."""
    try:
        await executor_service.execute_plan(plan_id)
    except Exception as e:
        logger.error("Background execution error for plan %s: %s", plan_id, e)


async def _run_execution_background_with_community_check(
    executor_service, plan_id: str, db
) -> None:
    """Run plan execution and persist community_payload to DB when upgrade is needed."""
    import json as _j, uuid as _u
    try:
        result = await executor_service.execute_plan(plan_id)
        if result.get("status") == "community_upgrade_needed":
            payload = result.get("community_payload", {})
            await db.execute(
                "UPDATE plans SET community_payload = $2::jsonb WHERE id = $1",
                _u.UUID(plan_id),
                _j.dumps(payload, default=str),
            )
    except Exception as e:
        logger.error("Background execution error for plan %s: %s", plan_id, e)


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
    session_service = services.get("session_service")

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
                "id": str(user["discord_user_id"]),
                "username": user["username"],
                "avatar": user["avatar"],
            },
            "guilds": guilds,
            "token": user["access_token"],  # In production: use JWT
        }

    @router.get("/auth/guilds")
    async def get_guilds(user_id: str, refresh: bool = False):
        """Get guild list for user. Auto-refreshes from Discord if cache empty.
        
        Returns guilds split into:
        - ready: bot_installed = True → can use immediately
        - pending: bot_installed = False → needs bot invite
        Each guild includes invite_url for easy activation.
        """
        uid = int(user_id)
        guilds = [] if refresh else await guild_sync_service.get_user_guilds(uid)

        # If cache is empty or refresh requested, sync from Discord
        if not guilds:
            token = await auth_service.get_user_token(uid)
            if token:
                logger.info("Syncing guilds from Discord for user %d (cache empty or refresh)", uid)
                guilds = await guild_sync_service.sync_user_guilds(uid, token)
            else:
                logger.warning("No stored token for user %d — cannot sync guilds", uid)
            
            if not guilds:
                return {
                    "ready": [],
                    "pending": [],
                    "total": 0,
                    "hint": "no_guilds_found",
                    "message": "Không tìm thấy server nào bạn có quyền quản lý. Hãy đảm bảo bạn có quyền Administrator hoặc Manage Server trên ít nhất 1 server Discord.",
                }
        
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
        
        Flow: check bot → session → request → classify → plan/query → execute (if auto-approve)
        """
        guild_id = int(req.guild_id)
        user_id = int(req.user_id)

        # §5.1 step 3: Check bot is installed in this guild
        bot_row = await guild_sync_service.db.fetchrow(
            "SELECT is_active FROM bot_installs WHERE guild_id = $1 AND is_active = TRUE",
            guild_id,
        )
        if not bot_row:
            invite_url = guild_sync_service.get_bot_invite_url(guild_id)
            return {
                "ok": False,
                "type": "bot_not_installed",
                "error": msg("bot_not_installed", lang="vi", invite_url=invite_url),
                "invite_url": invite_url,
            }

        # ── Session management ──────────────────────────────────────────
        session_id = req.session_id
        if session_service:
            if session_id:
                # Verify session belongs to this user/guild
                sess = await session_service.get_session(session_id)
                if not sess or sess["guild_id"] != guild_id or sess["user_id"] != user_id:
                    session_id = None  # Reset — will create fresh

            if not session_id:
                session_id = await session_service.create_session(
                    guild_id=guild_id,
                    user_id=user_id,
                    origin="web",
                    title=req.message[:60] + ("…" if len(req.message) > 60 else ""),
                )

            # Persist user message
            await session_service.add_message(
                session_id=session_id,
                guild_id=guild_id,
                user_id=user_id,
                role="user",
                content=req.message,
                origin="web",
            )

        # Get conversation history for context
        history = []
        if session_service and session_id:
            history = await session_service.get_history(session_id)

        # Create request
        req_result = await request_service.create_request(
            guild_id=guild_id,
            user_id=user_id,
            message=req.message,
            origin="web",
            session_id=session_id,
        )
        if not req_result["ok"]:
            return {"ok": False, "type": "locked", "error": msg("request_locked", lang="vi"),
                    "session_id": session_id}

        request_id = req_result["request_id"]

        # Classify
        try:
            classification = await classifier_service.classify(req.message)
        except Exception as qe:
            from app.llm.base import LLMQuotaError as _QE
            if isinstance(qe, _QE):
                err_text = msg_for_quota_error(qe.reason, lang="vi")
                await _save_bot_reply(err_text)
                await request_service.update_status(request_id, "failed", error_message=f"quota:{qe.reason}")
                return {"ok": False, "type": "quota_error", "error": err_text, "session_id": session_id}
            raise
        intent = classification["intent"]
        tool_mode = classification["tool_mode"]
        lang = classification.get("lang", "vi")
        await request_service.update_status(request_id, "classified", intent=intent, tool_mode=tool_mode)

        async def _save_bot_reply(content: str):
            if session_service and session_id:
                await session_service.add_message(
                    session_id=session_id, guild_id=guild_id, user_id=user_id,
                    role="bot", content=content, origin="web",
                )

        # Route by intent
        if intent == "query":
            try:
                answer = await query_service.answer(req.message, guild_id, history=history)
            except Exception as qe:
                from app.llm.base import LLMQuotaError as _QE
                if isinstance(qe, _QE):
                    answer = msg_for_quota_error(qe.reason, lang=lang)
                    await request_service.update_status(request_id, "failed", error_message=f"quota:{qe.reason}")
                    await _save_bot_reply(answer)
                    return {"ok": False, "type": "quota_error", "error": answer, "session_id": session_id}
                raise
            await request_service.update_status(request_id, "completed", response=answer)
            await _save_bot_reply(answer)
            return {"ok": True, "type": "answer", "content": answer,
                    "request_id": request_id, "session_id": session_id}

        if intent in ("clarify", "out_of_scope"):
            if intent == "clarify":
                try:
                    reply = await classifier_service.generate_clarify(req.message, lang=lang)
                except Exception as qe:
                    from app.llm.base import LLMQuotaError as _QE
                    if isinstance(qe, _QE):
                        reply = msg_for_quota_error(qe.reason, lang=lang)
                        await request_service.update_status(request_id, "failed", error_message=f"quota:{qe.reason}")
                        await _save_bot_reply(reply)
                        return {"ok": False, "type": "quota_error", "error": reply, "session_id": session_id}
                    raise
            else:
                reply = msg("out_of_scope", lang=lang)
            await request_service.update_status(request_id, "completed", response=reply)
            await _save_bot_reply(reply)
            return {"ok": True, "type": "clarify", "content": reply,
                    "request_id": request_id, "session_id": session_id}

        # Action intents → plan
        try:
            plan_result = await planner_service.generate_plan(
                request_id=request_id,
                guild_id=guild_id,
                user_id=user_id,
                message=req.message,
                intent=intent,
                history=history,
            )
        except Exception as qe:
            from app.llm.base import LLMQuotaError as _QE
            if isinstance(qe, _QE):
                err_text = msg_for_quota_error(qe.reason, lang="vi")
                await _save_bot_reply(err_text)
                return {"ok": False, "type": "quota_error", "error": err_text, "session_id": session_id}
            raise
        if not plan_result.get("ok"):
            return {"ok": False, "error": plan_result.get("error", "Planning failed"),
                    "session_id": session_id}

        plan_id = plan_result["plan_id"]

        if plan_result["risk_level"] in ("HIGH", "CRITICAL"):
            # Needs approval
            plan_summary = f"📋 Kế hoạch (risk: {plan_result['risk_level']}): {plan_result.get('description', '')}"
            await _save_bot_reply(plan_summary)
            return {
                "ok": True,
                "type": "approval_needed",
                "plan_id": plan_id,
                "plan": plan_result,
                "request_id": request_id,
                "session_id": session_id,
            }
        else:
            # Auto-approved → execute in background
            asyncio.create_task(
                _run_execution_background_with_community_check(
                    executor_service, plan_id, approval_service.db
                )
            )
            plan_summary = f"⏳ Đang thực thi kế hoạch: {plan_result.get('description', '')}"
            await _save_bot_reply(plan_summary)
            return {
                "ok": True,
                "type": "executing",
                "status": "executing",
                "plan_id": plan_id,
                "request_id": request_id,
                "session_id": session_id,
            }

    # === Approval endpoints (§5.5) ===

    @router.post("/approval")
    async def handle_approval(req: ApprovalRequest):
        """Approve or reject a plan from web dashboard."""
        if req.action == "approve":
            result = await approval_service.approve_plan(req.plan_id, int(req.user_id))
            if result["ok"]:
                asyncio.create_task(_run_execution_background(executor_service, req.plan_id))
                return {"ok": True, "status": "executing", "plan_id": req.plan_id}
            return result
        elif req.action == "reject":
            return await approval_service.reject_plan(req.plan_id, int(req.user_id), req.reason or "Rejected via web")
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

    @router.get("/guild/{guild_id}/info")
    async def guild_info(guild_id: int):
        """Get server info for sidebar display (channel/role/member counts).
        Requires bot to be installed.
        """
        bot_row = await guild_sync_service.db.fetchrow(
            "SELECT is_active FROM bot_installs WHERE guild_id = $1 AND is_active = TRUE",
            guild_id,
        )
        if not bot_row:
            return {"ok": False, "error": "Bot not installed"}

        # Get context via ContextService (which calls MCP tools)
        context_service = services.get("context_service")
        if not context_service:
            return {"ok": False, "error": "Context service unavailable"}

        try:
            ctx = await context_service.get_server_context(guild_id)
            import json
            channels = json.loads(ctx.get("channels", "[]")) if isinstance(ctx.get("channels"), str) else ctx.get("channels", [])
            roles = json.loads(ctx.get("roles", "[]")) if isinstance(ctx.get("roles"), str) else ctx.get("roles", [])
            server_info = json.loads(ctx.get("server_info", "{}")) if isinstance(ctx.get("server_info"), str) else ctx.get("server_info", {})
            categories = json.loads(ctx.get("categories", "[]")) if isinstance(ctx.get("categories"), str) else ctx.get("categories", [])

            return {
                "ok": True,
                "guild_id": guild_id,
                "channels": len(channels) if isinstance(channels, list) else 0,
                "roles": len(roles) if isinstance(roles, list) else 0,
                "categories": len(categories) if isinstance(categories, list) else 0,
                "member_count": server_info.get("member_count") or server_info.get("approximate_member_count") or "?",
                "server_name": server_info.get("name", ""),
            }
        except Exception as e:
            logger.error("Failed to get guild info: %s", e)
            return {"ok": False, "error": str(e)}

    # === Admin endpoints ===

    class UpdateGeminiKeyRequest(BaseModel):
        api_key: str
        user_id: str  # Discord user ID of the requester

    def _get_bot_owner_ids(request: Request) -> set:
        """Retrieve owner IDs from the live Discord bot instance."""
        bot = getattr(request.app.state, "bot", None)
        if bot is None:
            return set()
        return getattr(bot, "_bot_owner_ids", set())

    @router.post("/admin/update-gemini-key")
    async def update_gemini_key(req: UpdateGeminiKeyRequest, request: Request):
        """Update Gemini API key at runtime.
        
        Only callable by the Discord application owner(s) — the account(s) that
        own the bot token (DISCORD_TOKEN). No extra env variable required.
        """
        from app.config import settings as _settings

        uid = int(req.user_id)
        owner_ids = _get_bot_owner_ids(request)

        # If bot hasn't connected yet, owner_ids will be empty — deny for safety
        if not owner_ids or uid not in owner_ids:
            raise HTTPException(
                status_code=403,
                detail="Không có quyền: chỉ owner của bot application mới được cập nhật API key",
            )

        new_key = req.api_key.strip()
        if not new_key:
            raise HTTPException(status_code=400, detail="API key không được để trống")

        # Update settings singleton
        _settings.GEMINI_API_KEY = new_key

        # Update all live LLM instances that support runtime key updates
        updated_services = []
        svc_map = getattr(request.app.state, "services", {})
        for svc_name, svc in svc_map.items():
            llm = getattr(svc, "llm", None)
            if llm is not None and hasattr(llm, "update_api_key"):
                llm.update_api_key(new_key)
                updated_services.append(svc_name)

        logger.info(
            "Gemini API key updated by user %d — affected services: %s",
            uid, updated_services,
        )
        return {
            "ok": True,
            "message": "Gemini API key đã được cập nhật thành công",
            "updated_services": updated_services,
        }

    class UpdateDiscordTokenRequest(BaseModel):
        token: str
        user_id: str  # Discord user ID of the requester

    @router.post("/admin/update-discord-token")
    async def update_discord_token(req: UpdateDiscordTokenRequest, request: Request):
        """Update Discord Bot Token at runtime.

        Only callable by the Discord application owner(s). The new token is applied
        to the settings singleton; a full bot restart is required to reconnect the
        WebSocket with the new token.
        """
        from app.config import settings as _settings

        uid = int(req.user_id)
        owner_ids = _get_bot_owner_ids(request)

        if not owner_ids or uid not in owner_ids:
            raise HTTPException(
                status_code=403,
                detail="Không có quyền: chỉ owner của bot application mới được cập nhật Discord Token",
            )

        new_token = req.token.strip()
        if not new_token:
            raise HTTPException(status_code=400, detail="Discord Token không được để trống")

        _settings.DISCORD_TOKEN = new_token

        logger.info("Discord Token updated by user %d", uid)
        return {
            "ok": True,
            "message": "Discord Token đã được cập nhật. Khởi động lại bot để áp dụng.",
        }

    @router.get("/admin/status")
    async def admin_status(user_id: str, request: Request):
        """Check if a user is the bot application owner."""
        uid = int(user_id)
        owner_ids = _get_bot_owner_ids(request)
        return {"is_admin": bool(owner_ids) and uid in owner_ids}

    # === Community Upgrade ===

    @router.post("/community-upgrade/confirm")
    async def community_upgrade_confirm(req: CommunityUpgradeRequest):
        """Handle user response to the Community upgrade prompt.

        action="confirm" → enable Community + resume remaining plan steps.
        action="decline" → cancel the paused plan.
        """
        import uuid as _ucu

        payload = req.community_payload
        plan_id = payload.get("plan_id")
        request_id = payload.get("request_id")
        ch_type = payload.get("channel_type", "stage")
        lang = "vi"

        if req.action == "decline":
            if plan_id:
                try:
                    await approval_service.db.execute(
                        "UPDATE plans SET status = 'cancelled' WHERE id = $1",
                        _ucu.UUID(plan_id),
                    )
                    if request_id:
                        await approval_service.db.execute(
                            "UPDATE requests SET status = 'cancelled', completed_at = NOW() WHERE id = $1",
                            _ucu.UUID(request_id),
                        )
                except Exception as e:
                    logger.warning("Failed to cancel paused plan %s: %s", plan_id, e)
            return {
                "ok": True,
                "status": "cancelled",
                "message": msg("community_upgrade_declined", lang=lang, channel_type=ch_type),
            }

        if req.action == "confirm":
            # Fire-and-forget — frontend polls /execution/{plan_id}/status
            asyncio.create_task(executor_service.enable_community_and_resume(payload))
            return {
                "ok": True,
                "status": "executing",
                "plan_id": plan_id,
                "message": msg("community_upgrade_confirmed", lang=lang),
            }

        raise HTTPException(status_code=400, detail="action must be 'confirm' or 'decline'")

    # === Session / Chat Memory endpoints ===

    @router.get("/sessions")
    async def list_sessions(guild_id: int, user_id: int, limit: int = 30):
        """List chat sessions for a user in a guild (newest first)."""
        if not session_service:
            return {"sessions": []}
        sessions = await session_service.list_sessions(guild_id, user_id, limit=limit)
        return {"sessions": sessions}

    @router.get("/sessions/{session_id}/messages")
    async def get_session_messages(session_id: str, limit: int = 100, before_id: Optional[str] = None):
        """Get messages for a specific session."""
        if not session_service:
            raise HTTPException(status_code=503, detail="Session service unavailable")
        sess = await session_service.get_session(session_id)
        if not sess:
            raise HTTPException(status_code=404, detail="Session not found")
        messages = await session_service.get_session_messages(session_id, limit=limit, before_id=before_id)
        return {"session": sess, "messages": messages}

    class RenameSessionRequest(BaseModel):
        title: str

    @router.patch("/sessions/{session_id}")
    async def rename_session(session_id: str, req: RenameSessionRequest):
        """Rename a session."""
        if not session_service:
            raise HTTPException(status_code=503, detail="Session service unavailable")
        await session_service.rename_session(session_id, req.title)
        return {"ok": True}

    @router.delete("/sessions/{session_id}")
    async def delete_session(session_id: str):
        """Soft-close a session (marks as inactive)."""
        if not session_service:
            raise HTTPException(status_code=503, detail="Session service unavailable")
        await session_service.close_session(session_id)
        return {"ok": True}

    # === Health ===

    @router.get("/health")
    async def health():
        return {"status": "ok", "service": "AuraFactory"}

    import uuid as _uuid_mod

    @router.get("/execution/{plan_id}/status")
    async def get_execution_status(plan_id: str):
        """Poll execution status for a background-running plan."""
        try:
            plan_uuid = _uuid_mod.UUID(plan_id)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid plan_id format")

        plan = await approval_service.db.fetchrow(
            "SELECT status, current_step, total_steps, community_payload FROM plans WHERE id = $1",
            plan_uuid,
        )
        if not plan:
            raise HTTPException(status_code=404, detail="Plan not found")

        steps = await approval_service.db.fetch(
            "SELECT step_number, status, result FROM plan_steps WHERE plan_id = $1 ORDER BY step_number",
            plan_uuid,
        )

        response_data: dict = {
            "status": plan["status"],
            "completed_steps": plan["current_step"] or 0,
            "total_steps": plan["total_steps"],
            "results": [dict(s) for s in steps],
            "error": "Execution failed" if plan["status"] in ("failed", "partial") else None,
        }

        # When plan is paused for Community upgrade, attach the prompt
        if plan["status"] == "paused" and plan.get("community_payload"):
            import json as _jep
            raw = plan["community_payload"]
            try:
                payload = _jep.loads(raw) if isinstance(raw, str) else (raw or {})
            except Exception:
                payload = {}

            if payload.get("type") == "community_required":
                ch_type = payload.get("channel_type", "stage")
                ch_name = payload.get("channel_name", "")
                response_data["type"] = "community_upgrade_needed"
                response_data["community_payload"] = payload
                response_data["upgrade_prompt"] = msg(
                    "community_upgrade_needed",
                    lang="vi",
                    channel_type=ch_type,
                    channel_name=ch_name,
                )

        return response_data

    return router

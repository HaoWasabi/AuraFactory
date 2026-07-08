"""FastAPI REST API routes for AuraFactory web dashboard."""
import asyncio
import logging
import secrets
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from app.messages import msg

logger = logging.getLogger(__name__)


# === Request/Response schemas ===
class ChatRequest(BaseModel):
    message: str
    guild_id: str  # String to preserve Discord snowflake precision
    user_id: str  # String to preserve Discord snowflake precision
    session_id: Optional[str] = ""  # Active session ID from frontend

class ApprovalRequest(BaseModel):
    plan_id: str
    action: str  # "approve" or "reject"
    user_id: str  # String to preserve Discord snowflake precision
    reason: Optional[str] = None


async def _run_execution_background(executor_service, plan_id: str) -> None:
    """Run plan execution as background task — never raises."""
    try:
        await executor_service.execute_plan(plan_id)
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

    async def _save_to_session_history(guild_id: int, user_id: int, user_msg: str, bot_msg: str, session_id: str = ""):
        """Append user + bot messages to the active session's history JSONB."""
        import json as _json
        import uuid as _uuid
        db = guild_sync_service.db
        try:
            row = None
            # Use provided session_id if valid
            if session_id:
                try:
                    sid = _uuid.UUID(session_id)
                    row = await db.fetchrow(
                        "SELECT id, history FROM sessions WHERE id = $1", sid
                    )
                except (ValueError, TypeError):
                    pass
            # Fallback: find most recent session
            if not row:
                row = await db.fetchrow(
                    """SELECT id, history FROM sessions 
                       WHERE guild_id = $1 AND user_id = $2 
                       ORDER BY last_active_at DESC LIMIT 1""",
                    guild_id, user_id,
                )
            if not row:
                # Create a new session
                row = await db.fetchrow(
                    """INSERT INTO sessions (id, guild_id, user_id, user_role, history)
                       VALUES (gen_random_uuid(), $1, $2, 'admin', '[]'::jsonb)
                       RETURNING id, history""",
                    guild_id, user_id,
                )
            session_id = row["id"]
            history = row["history"] or []
            # asyncpg may return JSONB as string — ensure it's a list
            if isinstance(history, str):
                history = _json.loads(history) if history.strip() else []
            if not isinstance(history, list):
                history = []
            history.append({"role": "user", "content": user_msg})
            history.append({"role": "assistant", "content": bot_msg})
            await db.execute(
                """UPDATE sessions SET history = $1::jsonb, last_active_at = NOW() WHERE id = $2""",
                _json.dumps(history), session_id,
            )
        except Exception as e:
            logger.warning("Failed to save session history: %s", e)


    @router.post("/chat")
    async def chat(req: ChatRequest):
        """Main chat endpoint — same pipeline as Discord bot.
        
        Flow: check bot → request → classify → plan/query → execute (if auto-approve)
        """
        guild_id = int(req.guild_id)

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

        # Create request
        req_result = await request_service.create_request(
            guild_id=guild_id,
            user_id=int(req.user_id),
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
            answer = await query_service.answer(req.message, guild_id)
            await request_service.update_status(request_id, "completed", response=answer)
            await _save_to_session_history(guild_id, int(req.user_id), req.message, answer, req.session_id)
            return {"ok": True, "type": "answer", "content": answer, "request_id": request_id}

        if intent in ("clarify", "out_of_scope"):
            reply = msg(intent, lang=lang)
            await request_service.update_status(request_id, "completed", response=reply)
            await _save_to_session_history(guild_id, int(req.user_id), req.message, reply, req.session_id)
            return {"ok": True, "type": "clarify", "content": reply, "request_id": request_id}

        # Action intents → plan
        plan_result = await planner_service.generate_plan(
            request_id=request_id,
            guild_id=guild_id,
            user_id=int(req.user_id),
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
            # Auto-approved → execute in background
            asyncio.create_task(_run_execution_background(executor_service, plan_id))
            return {
                "ok": True,
                "type": "executing",
                "status": "executing",
                "plan_id": plan_id,
                "request_id": request_id,
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

            # Build structured categories with nested channels for right-panel tree view
            categories_structured = []
            # Step 1: Build category id→name lookup from categories.list response
            cat_id_to_name = {}
            if isinstance(categories, list):
                for cat in categories:
                    if isinstance(cat, dict):
                        cat_id_to_name[str(cat.get("id", ""))] = cat.get("name", "Unknown")

            # Step 2: Group channels by category_id, skip category-type entries
            grouped = {}  # {cat_name: [channel_info]}
            if isinstance(channels, list):
                for ch in channels:
                    if not isinstance(ch, dict):
                        continue
                    ch_type = str(ch.get("type", "text"))
                    if ch_type == "category":
                        continue  # categories.list already handles these
                    cat_id = str(ch.get("category_id", ""))
                    cat_name = cat_id_to_name.get(cat_id, "Uncategorized")
                    if cat_name not in grouped:
                        grouped[cat_name] = []
                    grouped[cat_name].append({
                        "name": ch.get("name", "unknown"),
                        "type": ch_type,
                    })

            # Step 3: Build ordered list (categorized first, then uncategorized)
            for cat_name in cat_id_to_name.values():
                if cat_name in grouped:
                    categories_structured.append({"name": cat_name, "channels": grouped.pop(cat_name)})
            for cat_name, cat_channels in grouped.items():
                categories_structured.append({"name": cat_name, "channels": cat_channels})

            # Build roles list for right-panel (deduplicated, exclude @everyone)
            seen_roles = set()
            roles_structured = []
            if isinstance(roles, list):
                for r in roles:
                    if isinstance(r, dict):
                        name = r.get("name", "")
                        if name and name != "@everyone" and name not in seen_roles:
                            seen_roles.add(name)
                            roles_structured.append({"name": name})

            return {
                "ok": True,
                "guild_id": guild_id,
                "channels": len(channels) if isinstance(channels, list) else 0,
                "roles": len(roles) if isinstance(roles, list) else 0,
                "categories": len(categories) if isinstance(categories, list) else 0,
                "member_count": server_info.get("member_count") or server_info.get("approximate_member_count") or "?",
                "server_name": server_info.get("name", ""),
                "categories_detail": categories_structured,
                "roles_detail": roles_structured,
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

        # If bot hasn't connected yet, owner_ids will be empty — allow any authenticated user
        # Once bot is connected, only owner(s) can update
        if owner_ids and uid not in owner_ids:
            raise HTTPException(
                status_code=403,
                detail="Không có quyền: chỉ owner của bot application mới được cập nhật API key",
            )

        new_key = req.api_key.strip()
        if not new_key:
            raise HTTPException(status_code=400, detail="API key không được để trống")

        if not new_key.startswith("AIza"):
            raise HTTPException(
                status_code=400,
                detail="API key không hợp lệ (Gemini key phải bắt đầu bằng 'AIza')",
            )

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

    @router.get("/admin/status")
    async def admin_status(user_id: str, request: Request):
        """Check if a user is the bot application owner."""
        uid = int(user_id)
        owner_ids = _get_bot_owner_ids(request)
        return {"is_admin": bool(owner_ids) and uid in owner_ids}

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
            "SELECT status, current_step, total_steps FROM plans WHERE id = $1",
            plan_uuid,
        )
        if not plan:
            raise HTTPException(status_code=404, detail="Plan not found")

        steps = await approval_service.db.fetch(
            "SELECT step_number, status, result FROM plan_steps WHERE plan_id = $1 ORDER BY step_number",
            plan_uuid,
        )
        return {
            "status": plan["status"],
            "completed_steps": plan["current_step"] or 0,
            "total_steps": plan["total_steps"],
            "results": [dict(s) for s in steps],
            "error": "Execution failed" if plan["status"] in ("failed", "partial") else None,
        }

    # === Session History Endpoints (Dashboard v2) ===

    @router.get("/sessions")
    async def list_sessions(guild_id: str, user_id: str):
        """List chat sessions for a user in a guild (sidebar history)."""
        db = guild_sync_service.db
        rows = await db.fetch(
            """
            SELECT id, 
                   history->0->>'content' as first_message,
                   created_at, 
                   last_active_at
            FROM sessions
            WHERE guild_id = $1 AND user_id = $2
            ORDER BY last_active_at DESC
            LIMIT 50
            """,
            int(guild_id),
            int(user_id),
        )
        return {
            "sessions": [
                {
                    "id": str(r["id"]),
                    "first_message": (r["first_message"] or "")[:60],
                    "created_at": r["created_at"].isoformat() if r["created_at"] else None,
                    "last_active_at": r["last_active_at"].isoformat() if r["last_active_at"] else None,
                }
                for r in rows
            ]
        }

    @router.get("/sessions/{session_id}/history")
    async def get_session_history(session_id: str):
        """Get full chat history for a specific session."""
        import uuid as uuid_mod
        db = guild_sync_service.db
        row = await db.fetchrow(
            "SELECT id, guild_id, user_id, history, created_at, last_active_at FROM sessions WHERE id = $1",
            uuid_mod.UUID(session_id),
        )
        if not row:
            raise HTTPException(status_code=404, detail="Session not found")
        import json as _json
        history = row["history"] or []
        if isinstance(history, str):
            history = _json.loads(history) if history.strip() else []
        if not isinstance(history, list):
            history = []
        return {
            "id": str(row["id"]),
            "guild_id": str(row["guild_id"]),
            "history": history,
            "created_at": row["created_at"].isoformat() if row["created_at"] else None,
            "last_active_at": row["last_active_at"].isoformat() if row["last_active_at"] else None,
        }

    @router.post("/sessions/new")
    async def create_session(guild_id: str, user_id: str):
        """Create a new chat session."""
        db = guild_sync_service.db
        row = await db.fetchrow(
            """
            INSERT INTO sessions (id, guild_id, user_id, user_role, history)
            VALUES (gen_random_uuid(), $1, $2, 'admin', '[]'::jsonb)
            RETURNING id, created_at
            """,
            int(guild_id),
            int(user_id),
        )
        return {"id": str(row["id"]), "created_at": row["created_at"].isoformat()}

    @router.get("/audit")
    async def get_audit_log(guild_id: str, limit: int = 20):
        """Get recent audit log entries for a guild."""
        db = guild_sync_service.db
        rows = await db.fetch(
            """
            SELECT tool_name, success, user_id, executed_at, duration_ms, error_message
            FROM audit_log
            WHERE guild_id = $1
            ORDER BY executed_at DESC
            LIMIT $2
            """,
            int(guild_id),
            min(limit, 100),
        )
        return {
            "entries": [
                {
                    "tool_name": r["tool_name"],
                    "success": r["success"],
                    "user_id": str(r["user_id"]),
                    "executed_at": r["executed_at"].isoformat() if r["executed_at"] else None,
                    "duration_ms": r["duration_ms"],
                    "error": r["error_message"],
                }
                for r in rows
            ]
        }

    # === Streaming Chat Endpoint (SSE) ===

    @router.post("/chat/stream")
    async def chat_stream(req: ChatRequest):
        """Stream chat response via Server-Sent Events (SSE).

        Chunk protocol:
        - {"type": "text", "content": "partial text"}
        - {"type": "status", "status": "planning|executing", "message": "..."}
        - {"type": "approval", "plan_id": "...", "summary": "...", "steps": [...], "risk": "..."}
        - {"type": "clarify", "summary": "...", "questions": [...]}
        - {"type": "done", "final_message": "..."}
        - {"type": "error", "message": "..."}
        """
        import json as _json

        guild_id = int(req.guild_id)
        user_id = int(req.user_id)

        async def _stream_generator():
            try:
                # Check bot installed
                bot_row = await guild_sync_service.db.fetchrow(
                    "SELECT is_active FROM bot_installs WHERE guild_id = $1 AND is_active = TRUE",
                    guild_id,
                )
                if not bot_row:
                    yield f"data: {_json.dumps({'type': 'error', 'message': 'Bot not installed in this server.'})}\n\n"
                    yield "data: [DONE]\n\n"
                    return

                # Create request
                req_result = await request_service.create_request(
                    guild_id=guild_id,
                    user_id=user_id,
                    message=req.message,
                    origin="web",
                )
                if not req_result["ok"]:
                    yield f"data: {_json.dumps({'type': 'error', 'message': 'Request locked — another request is active.'})}\n\n"
                    yield "data: [DONE]\n\n"
                    return

                request_id = req_result["request_id"]

                # Classify
                yield f"data: {_json.dumps({'type': 'status', 'status': 'classifying', 'message': 'Analyzing request...'})}\n\n"
                classification = await classifier_service.classify(req.message)
                intent = classification["intent"]
                tool_mode = classification["tool_mode"]
                lang = classification.get("lang", "en")
                await request_service.update_status(request_id, "classified", intent=intent, tool_mode=tool_mode)

                # Route by intent
                if intent == "query":
                    answer = await query_service.answer(req.message, guild_id)
                    await request_service.update_status(request_id, "completed", response=answer)
                    await _save_to_session_history(guild_id, user_id, req.message, answer, req.session_id)
                    # Stream text word-by-word
                    words = answer.split(" ")
                    for i, word in enumerate(words):
                        chunk = word if i == 0 else " " + word
                        yield f"data: {_json.dumps({'type': 'text', 'content': chunk})}\n\n"
                        await asyncio.sleep(0.03)
                    yield f"data: {_json.dumps({'type': 'done', 'final_message': answer})}\n\n"
                    yield "data: [DONE]\n\n"
                    return

                if intent in ("clarify", "out_of_scope"):
                    reply = msg(intent, lang=lang)
                    await request_service.update_status(request_id, "completed", response=reply)
                    await _save_to_session_history(guild_id, user_id, req.message, reply, req.session_id)
                    words = reply.split(" ")
                    for i, word in enumerate(words):
                        chunk = word if i == 0 else " " + word
                        yield f"data: {_json.dumps({'type': 'text', 'content': chunk})}\n\n"
                        await asyncio.sleep(0.03)
                    yield f"data: {_json.dumps({'type': 'done', 'final_message': reply})}\n\n"
                    yield "data: [DONE]\n\n"
                    return

                # Action intents -> plan
                yield f"data: {_json.dumps({'type': 'status', 'status': 'planning', 'message': 'Creating execution plan...'})}\n\n"
                plan_result = await planner_service.generate_plan(
                    request_id=request_id,
                    guild_id=guild_id,
                    user_id=user_id,
                    message=req.message,
                    intent=intent,
                )

                if not plan_result.get("ok"):
                    # Check if clarify
                    if plan_result.get("status") == "clarify":
                        yield f"data: {_json.dumps({'type': 'clarify', 'summary': plan_result.get('summary', ''), 'questions': plan_result.get('questions', [])})}\n\n"
                    else:
                        yield f"data: {_json.dumps({'type': 'error', 'message': plan_result.get('error', 'Planning failed.')})}\n\n"
                    yield "data: [DONE]\n\n"
                    return

                plan_id = plan_result["plan_id"]
                risk_level = plan_result.get("risk_level", "MEDIUM")

                if risk_level in ("HIGH", "CRITICAL"):
                    # Needs approval — send approval chunk
                    yield f"data: {_json.dumps({'type': 'approval', 'plan_id': plan_id, 'summary': plan_result.get('description', ''), 'steps': plan_result.get('steps', []), 'risk': risk_level})}\n\n"
                    yield "data: [DONE]\n\n"
                    return

                # Auto-approved — execute and stream progress
                yield f"data: {_json.dumps({'type': 'status', 'status': 'executing', 'message': 'Executing plan...'})}\n\n"

                exec_result = await executor_service.execute_plan(plan_id)

                completed = exec_result.get("completed_steps", 0)
                total = exec_result.get("total_steps", 0)
                status = exec_result.get("status", "unknown")

                if status == "completed":
                    final_msg = f"Completed all {total} steps successfully."
                    await _save_to_session_history(guild_id, user_id, req.message, final_msg, req.session_id)
                    yield f"data: {_json.dumps({'type': 'done', 'final_message': final_msg})}\n\n"
                elif status == "partial":
                    err_msg = f"Completed {completed}/{total} steps. Error: {exec_result.get('error', 'Unknown')}"
                    await _save_to_session_history(guild_id, user_id, req.message, err_msg, req.session_id)
                    yield f"data: {_json.dumps({'type': 'error', 'message': err_msg})}\n\n"
                else:
                    err_full = exec_result.get('error', 'Execution failed.')
                    await _save_to_session_history(guild_id, user_id, req.message, err_full, req.session_id)
                    yield f"data: {_json.dumps({'type': 'error', 'message': exec_result.get('error', 'Execution failed.')})}\n\n"

                yield "data: [DONE]\n\n"

            except Exception as e:
                logger.error("Streaming chat error: %s", e, exc_info=True)
                yield f"data: {_json.dumps({'type': 'error', 'message': str(e)})}\n\n"
                yield "data: [DONE]\n\n"

        return StreamingResponse(
            _stream_generator(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    return router

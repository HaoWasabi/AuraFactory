"""FastAPI REST API routes for AuraFactory web dashboard."""
import json
import logging
import secrets
import uuid
from typing import Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

logger = logging.getLogger(__name__)


# === Request/Response schemas ===
class ChatRequest(BaseModel):
    message: str
    guild_id: str
    user_id: str
    session_id: Optional[str] = ""


def create_api_router(services: dict) -> APIRouter:
    """Create API router with injected services."""
    router = APIRouter(prefix="/api", tags=["api"])

    auth_service = services["auth_service"]
    guild_sync_service = services["guild_sync_service"]
    context_service = services["context_service"]
    unified_agent = services.get("unified_agent")
    mcp_client = services.get("_mcp_client")
    db = services.get("_db")

    # ══════════════════════════════════════════════════════════════════
    # Auth endpoints
    # ══════════════════════════════════════════════════════════════════

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
            "token": user["access_token"],
        }

    @router.get("/auth/guilds")
    async def get_guilds(user_id: str, refresh: bool = False):
        """Get guild list for user. Returns ready/pending split."""
        uid = int(user_id)
        guilds = [] if refresh else await guild_sync_service.get_user_guilds(uid)

        if not guilds:
            token = await auth_service.get_user_token(uid)
            if token:
                guilds = await guild_sync_service.sync_user_guilds(uid, token)

            if not guilds:
                return {
                    "ready": [], "pending": [], "total": 0,
                    "hint": "no_guilds_found",
                    "message": "Không tìm thấy server nào bạn có quyền quản lý.",
                }

        ready, pending = [], []
        for g in guilds:
            g["invite_url"] = guild_sync_service.get_bot_invite_url(g["guild_id"])
            (ready if g.get("bot_installed") else pending).append(g)

        return {"ready": ready, "pending": pending, "total": len(guilds)}

    @router.get("/auth/bot-invite")
    async def bot_invite(guild_id: int):
        """Get bot invite URL for a specific guild."""
        url = guild_sync_service.get_bot_invite_url(guild_id)
        return {"url": url, "guild_id": guild_id}

    # ══════════════════════════════════════════════════════════════════
    # Chat — Unified Agent
    # ══════════════════════════════════════════════════════════════════

    async def _save_to_session_history(guild_id: int, user_id: int, user_msg: str, bot_msg: str, session_id: str = ""):
        """Append user + bot messages to the session's history JSONB."""
        try:
            row = None
            if session_id:
                try:
                    sid = uuid.UUID(session_id)
                    row = await db.fetchrow("SELECT id, history FROM sessions WHERE id = $1", sid)
                except (ValueError, TypeError):
                    pass
            if not row:
                row = await db.fetchrow(
                    """SELECT id, history FROM sessions 
                       WHERE guild_id = $1 AND user_id = $2 
                       ORDER BY last_active_at DESC LIMIT 1""",
                    guild_id, user_id,
                )
            if not row:
                row = await db.fetchrow(
                    """INSERT INTO sessions (id, guild_id, user_id, user_role, history)
                       VALUES (gen_random_uuid(), $1, $2, 'admin', '[]'::jsonb)
                       RETURNING id, history""",
                    guild_id, user_id,
                )
            history = row["history"] or []
            if isinstance(history, str):
                history = json.loads(history) if history.strip() else []
            if not isinstance(history, list):
                history = []
            history.append({"role": "user", "content": user_msg})
            history.append({"role": "assistant", "content": bot_msg})
            await db.execute(
                "UPDATE sessions SET history = $1::jsonb, last_active_at = NOW() WHERE id = $2",
                json.dumps(history), row["id"],
            )
        except Exception as e:
            logger.warning("Failed to save session history: %s", e)

    @router.post("/chat/v2")
    async def chat_v2(req: ChatRequest):
        """Chat endpoint — Unified Agent with native function calling."""
        if not unified_agent:
            return {"ok": False, "type": "error", "content": "⚠️ AI chưa sẵn sàng (LLM not configured)."}

        guild_id = int(req.guild_id)
        user_id_int = int(req.user_id)

        # Check bot installed
        bot_row = await db.fetchrow(
            "SELECT is_active FROM bot_installs WHERE guild_id = $1 AND is_active = TRUE",
            guild_id,
        )
        if not bot_row:
            invite_url = guild_sync_service.get_bot_invite_url(guild_id)
            return {
                "ok": False,
                "type": "bot_not_installed",
                "content": f"Bot chưa được cài vào server này. [Mời bot]({invite_url})",
                "invite_url": invite_url,
            }

        # Check MCP tools ready (bot connected to Discord)
        if mcp_client and not mcp_client._tool_index:
            return {
                "ok": False,
                "type": "bot_starting",
                "content": "⏳ Bot đang kết nối Discord, vui lòng thử lại sau vài giây...",
            }

        # Get session history for context
        history = []
        if req.session_id:
            try:
                sid = uuid.UUID(req.session_id)
                row = await db.fetchrow("SELECT history FROM sessions WHERE id = $1", sid)
                if row:
                    h = row["history"] or []
                    if isinstance(h, str):
                        h = json.loads(h) if h.strip() else []
                    history = h[-10:]  # Last 10 messages for context
            except (ValueError, TypeError):
                pass

        # Process via Unified Agent
        result = await unified_agent.process(
            message=req.message,
            guild_id=guild_id,
            user_id=user_id_int,
            history=history,
        )

        # Save to session history
        content = result.get("content", "")
        if content:
            await _save_to_session_history(guild_id, user_id_int, req.message, content, req.session_id)

        return {"ok": True, **result}

    # Keep /chat as alias for /chat/v2
    @router.post("/chat")
    async def chat(req: ChatRequest):
        """Alias for /chat/v2."""
        return await chat_v2(req)

    # ══════════════════════════════════════════════════════════════════
    # Sessions
    # ══════════════════════════════════════════════════════════════════

    @router.get("/sessions")
    async def list_sessions(guild_id: str, user_id: str):
        """List chat sessions for a user in a guild."""
        rows = await db.fetch(
            """
            SELECT id,
                   COALESCE(
                       (SELECT elem->>'content' FROM jsonb_array_elements(history) AS elem
                        WHERE elem->>'role' = 'user' LIMIT 1),
                       history->0->>'content'
                   ) as first_message,
                   created_at, last_active_at
            FROM sessions
            WHERE guild_id = $1 AND user_id = $2
            ORDER BY last_active_at DESC
            LIMIT 50
            """,
            int(guild_id), int(user_id),
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
        row = await db.fetchrow(
            "SELECT id, guild_id, user_id, history, created_at, last_active_at FROM sessions WHERE id = $1",
            uuid.UUID(session_id),
        )
        if not row:
            raise HTTPException(status_code=404, detail="Session not found")
        history = row["history"] or []
        if isinstance(history, str):
            history = json.loads(history) if history.strip() else []
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
        row = await db.fetchrow(
            """INSERT INTO sessions (id, guild_id, user_id, user_role, history)
               VALUES (gen_random_uuid(), $1, $2, 'admin', '[]'::jsonb)
               RETURNING id, created_at""",
            int(guild_id), int(user_id),
        )
        return {"id": str(row["id"]), "created_at": row["created_at"].isoformat()}

    @router.delete("/sessions/{session_id}")
    async def delete_session(session_id: str, user_id: str):
        """Delete a chat session (only if owned by user)."""
        try:
            sid = uuid.UUID(session_id)
        except (ValueError, TypeError):
            raise HTTPException(status_code=400, detail="Invalid session ID")
        # Verify ownership
        row = await db.fetchrow(
            "SELECT id FROM sessions WHERE id = $1 AND user_id = $2",
            sid, int(user_id),
        )
        if not row:
            raise HTTPException(status_code=404, detail="Session not found or not owned by user")
        await db.execute("DELETE FROM sessions WHERE id = $1", sid)
        return {"ok": True, "deleted": session_id}

    # ══════════════════════════════════════════════════════════════════
    # Guild Info (right panel)
    # ══════════════════════════════════════════════════════════════════

    @router.get("/guild/{guild_id}/status")
    async def guild_status(guild_id: int):
        """Check if bot is installed and active in a guild."""
        bot_row = await db.fetchrow(
            "SELECT is_active, installed_at FROM bot_installs WHERE guild_id = $1", guild_id,
        )
        if bot_row and bot_row["is_active"]:
            return {
                "bot_installed": True,
                "installed_at": bot_row["installed_at"].isoformat() if bot_row["installed_at"] else None,
            }
        return {
            "bot_installed": False,
            "invite_url": guild_sync_service.get_bot_invite_url(guild_id),
        }

    @router.get("/guild/{guild_id}/info")
    async def guild_info(guild_id: int):
        """Get server structure for sidebar display."""
        bot_row = await db.fetchrow(
            "SELECT is_active FROM bot_installs WHERE guild_id = $1 AND is_active = TRUE", guild_id,
        )
        if not bot_row:
            return {"ok": False, "error": "Bot not installed"}

        # Check MCP tools ready
        if mcp_client and not mcp_client._tool_index:
            return {"ok": False, "error": "Bot is still connecting to Discord..."}

        try:
            ctx = await context_service.get_server_context(guild_id)
            channels = json.loads(ctx.get("channels", "[]")) if isinstance(ctx.get("channels"), str) else ctx.get("channels", [])
            roles = json.loads(ctx.get("roles", "[]")) if isinstance(ctx.get("roles"), str) else ctx.get("roles", [])
            server_info = json.loads(ctx.get("server_info", "{}")) if isinstance(ctx.get("server_info"), str) else ctx.get("server_info", {})
            categories = json.loads(ctx.get("categories", "[]")) if isinstance(ctx.get("categories"), str) else ctx.get("categories", [])

            # Build categories → channels tree
            cat_id_to_name = {}
            if isinstance(categories, list):
                for cat in categories:
                    if isinstance(cat, dict):
                        cat_id_to_name[str(cat.get("id", ""))] = cat.get("name", "Unknown")

            grouped = {}
            if isinstance(channels, list):
                for ch in channels:
                    if not isinstance(ch, dict):
                        continue
                    ch_type = str(ch.get("type", "text"))
                    if ch_type == "category":
                        continue
                    cat_id = str(ch.get("category_id", ""))
                    cat_name = cat_id_to_name.get(cat_id, "Uncategorized")
                    if cat_name not in grouped:
                        grouped[cat_name] = []
                    grouped[cat_name].append({"name": ch.get("name", "unknown"), "type": ch_type})

            categories_structured = []
            for cat_name in cat_id_to_name.values():
                if cat_name in grouped:
                    categories_structured.append({"name": cat_name, "channels": grouped.pop(cat_name)})
            for cat_name, cat_channels in grouped.items():
                categories_structured.append({"name": cat_name, "channels": cat_channels})

            # Deduplicated roles
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

    # ══════════════════════════════════════════════════════════════════
    # Audit Log
    # ══════════════════════════════════════════════════════════════════

    @router.get("/audit")
    async def get_audit_log(guild_id: str, limit: int = 20):
        """Get recent audit log entries for a guild."""
        rows = await db.fetch(
            """SELECT tool_name, success, user_id, executed_at, duration_ms, error_message
               FROM audit_log WHERE guild_id = $1
               ORDER BY executed_at DESC LIMIT $2""",
            int(guild_id), min(limit, 100),
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

    # ══════════════════════════════════════════════════════════════════
    # Admin
    # ══════════════════════════════════════════════════════════════════

    class UpdateGeminiKeyRequest(BaseModel):
        api_key: str
        user_id: str

    @router.post("/admin/update-gemini-key")
    async def update_gemini_key(req: UpdateGeminiKeyRequest, request: Request):
        """Update Gemini API key at runtime."""
        from app.config import settings as _settings

        new_key = req.api_key.strip()
        if not new_key or not new_key.startswith("AIza"):
            raise HTTPException(status_code=400, detail="Invalid Gemini API key")

        _settings.GEMINI_API_KEY = new_key

        # Update live LLM instance
        if unified_agent and hasattr(unified_agent, "_llm"):
            llm = unified_agent._llm
            if hasattr(llm, "update_api_key"):
                llm.update_api_key(new_key)

        logger.info("Gemini API key updated by user %s", req.user_id)
        return {"ok": True, "message": "API key updated successfully"}

    # ══════════════════════════════════════════════════════════════════
    # Health
    # ══════════════════════════════════════════════════════════════════

    @router.get("/health")
    async def health():
        return {"status": "ok", "service": "AuraFactory"}

    return router

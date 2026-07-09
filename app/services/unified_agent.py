"""UnifiedAgent v2 — Production-grade with 3 resilience patterns.

Patterns:
  1. LLMResponseNormalizer — guaranteed output shape from any LLM response
  2. RequestStore + RequestLifecycle — stateful FSM per (guild_id, user_id)
  3. ExecutionPipeline + Middleware — composable chain for tool execution

Flow:
    Request → GuildLock → RequestLifecycle.create()
           → LLM call → Normalizer.normalize()
           → Approval Gate (if high risk) → RequestLifecycle.AWAITING_APPROVAL
           → Pipeline.execute() [ErrorBoundary → Audit → RateLimit → Retry → Memory]
           → Format Response → RequestLifecycle.COMPLETED
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any, Dict, List, Optional

from app.config import settings
from app.llm.base import BaseLLM, LLMResponse
from app.mcp import MCPClient
from app.services.context_service import ContextService

# Pattern 1: Normalizer
from app.core.normalizer import LLMResponseNormalizer, NormalizedLLMOutput, NormalizedToolCall

# Pattern 2: Request Lifecycle
from app.core.request_lifecycle import RequestStore, RequestLifecycle, RequestState

# Pattern 3: Middleware Pipeline
from app.core.middleware import (
    ExecutionPipeline, ExecutionContext, ExecutionResult,
    ErrorBoundaryMiddleware, RateLimitMiddleware,
    RetryMiddleware, AuditMiddleware, MemoryMiddleware,
)

# Safety (supporting)
from app.core.safety import AuditLogger, GuildLock, ConversationMemory

logger = logging.getLogger(__name__)

# ═══════════════════════════════════════════════════════════════════════════
# Prompt & Tool Definitions (separated for maintainability)
# ═══════════════════════════════════════════════════════════════════════════

from app.prompts.system_prompt import UNIFIED_SYSTEM_PROMPT, ASSEMBLE_PROMPT
from app.core.tool_definitions import TOOL_DEFINITIONS, TOOL_NAME_MAP, HIGH_RISK_TOOLS

# Backward-compatible alias
_HIGH_RISK_TOOLS = HIGH_RISK_TOOLS

# ═══════════════════════════════════════════════════════════════════════════
# Context Builder
# ═══════════════════════════════════════════════════════════════════════════

def build_server_context_block(server_context: dict) -> str:
    """Build compact server context string for LLM prompt."""
    if not server_context:
        return "No server data available yet."

    parts = []
    categories = server_context.get("categories", [])
    channels = server_context.get("channels", [])
    roles = server_context.get("roles", [])
    server_info = server_context.get("server_info", {})

    if isinstance(categories, str):
        categories = json.loads(categories) if categories.strip() else []
    if isinstance(channels, str):
        channels = json.loads(channels) if channels.strip() else []
    if isinstance(roles, str):
        roles = json.loads(roles) if roles.strip() else []
    if isinstance(server_info, str):
        server_info = json.loads(server_info) if server_info.strip() else {}

    if server_info:
        name = server_info.get("name", "?")
        members = server_info.get("member_count", server_info.get("approximate_member_count", "?"))
        parts.append(f"Server: {name} ({members} members)")

    if categories:
        cat_lines = [f"  {c.get('id', '?')}: {c.get('name', '?')}" for c in categories[:20]]
        parts.append("Categories:\n" + "\n".join(cat_lines))

    if channels:
        ch_lines = []
        for ch in channels[:40]:
            ch_type = ch.get("type", "text")
            cat_id = ch.get("category_id", "none")
            ch_lines.append(f"  {ch.get('id', '?')}: #{ch.get('name', '?')} ({ch_type}) [cat:{cat_id}]")
        parts.append("Channels:\n" + "\n".join(ch_lines))

    if roles:
        role_lines = [f"  {r.get('id', '?')}: @{r.get('name', '?')} (pos:{r.get('position', 0)})"
                      for r in roles[:20] if r.get("name") != "@everyone"]
        parts.append("Roles:\n" + "\n".join(role_lines))

    return "\n\n".join(parts) if parts else "Server is empty or bot has no cached data."


# ═══════════════════════════════════════════════════════════════════════════
# Unified Agent
# ═══════════════════════════════════════════════════════════════════════════

class UnifiedAgent:
    """Production-grade agent with 3 resilience patterns.

    Pattern 1 (Normalizer): LLM output → NormalizedLLMOutput (guaranteed shape)
    Pattern 2 (Request FSM): Tracks state per (guild_id, user_id) with TTL
    Pattern 3 (Pipeline): Tool execution via composable middleware chain
    """

    def __init__(
        self,
        llm: BaseLLM,
        mcp_client: MCPClient,
        context_service: ContextService,
        db=None,
        registry=None,
    ) -> None:
        self._llm = llm
        self._mcp_client = mcp_client
        self._context_service = context_service

        # Pattern 1: Normalizer
        self._normalizer = LLMResponseNormalizer(tool_name_map=TOOL_NAME_MAP)

        # Pattern 2: Request Store
        self._requests = RequestStore(default_ttl=300.0)

        # Pattern 3: Middleware Pipeline
        self._memory = ConversationMemory()
        self._audit = AuditLogger(db=db)
        self._pipeline = ExecutionPipeline(
            middlewares=[
                ErrorBoundaryMiddleware(),
                AuditMiddleware(self._audit),
                RateLimitMiddleware(min_delay=0.5, burst_limit=5),
                RetryMiddleware(max_retries=3, base_delay=1.0),
                MemoryMiddleware(self._memory),
            ],
            executor=self._mcp_execute,
        )

        # Guild Lock
        self._guild_lock = GuildLock(
            mode=getattr(settings, "GUILD_LOCK_MODE", "open"),
            allowed_ids=set(int(x) for x in getattr(settings, "ALLOWED_GUILD_IDS", []) if x),
        )

        logger.info(
            "UnifiedAgent v2 initialized: normalizer=%s, pipeline=%d middlewares, guild_lock=%s",
            type(self._normalizer).__name__,
            self._pipeline.middleware_count,
            self._guild_lock.mode,
        )

    # ─────────────────────────────────────────────────────────────────────
    # Main Entry Point
    # ─────────────────────────────────────────────────────────────────────

    async def process(
        self,
        message: str,
        guild_id: int,
        user_id: int,
        history: Optional[List[Dict[str, str]]] = None,
    ) -> Dict[str, Any]:
        """Process a user message end-to-end.

        Returns:
            {"type": "answer"|"action"|"confirm_needed"|"error", "content": str, "tool_results": [...]}
        """
        # === Guild Lock ===
        if not self._guild_lock.is_allowed(guild_id):
            return self._response("error", "⛔ Server này chưa được cấp quyền sử dụng bot.")

        # === Check pending approval ===
        pending_req = self._requests.get_awaiting_approval(guild_id, user_id)
        if pending_req:
            return await self._handle_confirmation(message, pending_req)

        # === Create new request lifecycle ===
        req = self._requests.create(guild_id, user_id, message)
        req.set_payload("original_message", message)
        req.transition(RequestState.PLANNING)

        # === Build context ===
        server_context = await self._context_service.get_server_context(guild_id)
        context_block = build_server_context_block(server_context)
        memory_block = self._memory.build_context_block(guild_id)

        # === LLM Call ===
        messages = self._build_messages(context_block, memory_block, message, history)

        try:
            raw_response: LLMResponse = await self._llm.generate(
                messages=messages,
                system_prompt=UNIFIED_SYSTEM_PROMPT,
                tools=TOOL_DEFINITIONS,
                temperature=0.2,
                max_tokens=2048,
            )
        except Exception as e:
            logger.error("LLM call failed: %s", e, exc_info=True)
            req.transition(RequestState.FAILED)
            req.set_payload("failure_reason", str(e))
            return self._response("error", "⚠️ Đã xảy ra lỗi khi xử lý yêu cầu. Vui lòng thử lại.")

        # === Pattern 1: Normalize ===
        normalized = self._normalizer.normalize(raw_response)

        if not normalized.usable:
            req.transition(RequestState.FAILED)
            req.set_payload("failure_reason", normalized.failure_reason)
            logger.warning("LLM response not usable: %s", normalized.failure_reason)
            return self._response("error", "⚠️ AI không thể xử lý yêu cầu lúc này. Vui lòng thử lại.")

        # === Branch: text-only response ===
        if normalized.is_text_only:
            req.transition(RequestState.COMPLETED)
            return self._response("answer", normalized.text)

        # === Branch: tool calls ===
        if normalized.has_tool_calls:
            return await self._execute_tools(normalized, req, guild_id, user_id)

        # Fallback: has content but no tools (shouldn't happen if normalized correctly)
        req.transition(RequestState.COMPLETED)
        return self._response("answer", normalized.text or "Không có phản hồi.")

    # ─────────────────────────────────────────────────────────────────────
    # Tool Execution (Pattern 3: Pipeline)
    # ─────────────────────────────────────────────────────────────────────

    async def _execute_tools(
        self,
        normalized: NormalizedLLMOutput,
        req: RequestLifecycle,
        guild_id: int,
        user_id: int,
    ) -> Dict[str, Any]:
        """Execute normalized tool calls via middleware pipeline."""
        results: List[Dict[str, Any]] = []

        for tool_call in normalized.tool_calls:
            params = dict(tool_call.arguments)
            params["guild_id"] = guild_id
            mcp_name = tool_call.mcp_name

            # === Approval Gate (risk check) ===
            if mcp_name in _HIGH_RISK_TOOLS:
                # Store state and ask user
                req.transition(RequestState.AWAITING_APPROVAL)
                req.set_payload("pending_tool", {
                    "mcp_name": mcp_name,
                    "display_name": tool_call.name,
                    "params": params,
                    "remaining_tools": normalized.tool_calls[normalized.tool_calls.index(tool_call) + 1:],
                    "llm_text": normalized.text,
                    "results_so_far": results,
                })

                desc = self._describe_action(tool_call.name, params)
                return self._response(
                    "confirm_needed",
                    f"{desc}\n\n❓ **Xác nhận thực hiện?** (reply `có` / `yes` để tiếp tục, `không` / `no` để hủy)",
                    results,
                )

            # === Execute via Pipeline ===
            req.transition(RequestState.EXECUTING)
            ctx = ExecutionContext(
                tool_name=mcp_name,
                params=params,
                guild_id=guild_id,
                user_id=user_id,
                risk_level="high" if mcp_name in _HIGH_RISK_TOOLS else "medium",
                request_id=req.id,
            )

            result = await self._pipeline.execute(ctx)
            results.append(self._result_to_dict(result, mcp_name))

        # === Done executing all tools ===
        req.transition(RequestState.COMPLETED)

        # Invalidate context cache (best-effort)
        try:
            if any(r["success"] for r in results):
                await self._context_service.invalidate(guild_id)
        except Exception as e:
            logger.warning("Context invalidation failed (non-fatal): %s", e)

        # Assemble natural language response via second LLM call
        content = await self._assemble_response(
            user_message=req.get_payload("original_message", ""),
            results=results,
            llm_text=normalized.text,
        )
        return self._response("action", content, results)

    # ─────────────────────────────────────────────────────────────────────
    # Confirmation Handler
    # ─────────────────────────────────────────────────────────────────────

    async def _handle_confirmation(
        self,
        message: str,
        req: RequestLifecycle,
    ) -> Dict[str, Any]:
        """Handle user's yes/no reply to approval prompt."""
        msg_lower = message.lower().strip()
        affirmative = msg_lower in ("có", "yes", "y", "ok", "đồng ý", "xác nhận", "confirm", "1")

        pending = req.get_payload("pending_tool", {})
        guild_id = req.guild_id
        user_id = req.user_id

        if not affirmative:
            req.transition(RequestState.CANCELLED)
            await self._audit.log_approval(guild_id, user_id, pending.get("mcp_name", ""), "rejected")
            return self._response("answer", "✋ Đã hủy. Không có thay đổi nào được thực hiện.")

        # User confirmed → execute
        await self._audit.log_approval(guild_id, user_id, pending.get("mcp_name", ""), "approved")
        req.transition(RequestState.EXECUTING)

        mcp_name = pending.get("mcp_name", "")
        params = pending.get("params", {})

        ctx = ExecutionContext(
            tool_name=mcp_name,
            params=params,
            guild_id=guild_id,
            user_id=user_id,
            risk_level="high",
            request_id=req.id,
        )

        result = await self._pipeline.execute(ctx)
        results = pending.get("results_so_far", []) + [self._result_to_dict(result, mcp_name)]

        req.transition(RequestState.COMPLETED)

        # Invalidate cache
        try:
            if result.success:
                await self._context_service.invalidate(guild_id)
        except Exception:
            pass

        content = await self._assemble_response(
            user_message=req.get_payload("original_message", ""),
            results=results,
            llm_text=pending.get("llm_text", ""),
        )
        return self._response("action", content, results)

    # ─────────────────────────────────────────────────────────────────────
    # Assemble Response (2nd LLM call — natural language formatting)
    # ─────────────────────────────────────────────────────────────────────

    async def _assemble_response(
        self,
        user_message: str,
        results: List[Dict[str, Any]],
        llm_text: str,
    ) -> str:
        """Call LLM a second time to assemble a friendly, natural response.

        Falls back to _format_results() if the second LLM call fails.
        """
        # Build a compact summary of results for the assembler
        result_lines = []
        for r in results:
            if r["success"]:
                data = r.get("result") or {}
                name = data.get("name") or data.get("channel_name") or data.get("role_name") or ""
                result_lines.append(f"✓ {r.get('tool','action')}: {name} (success)")
            else:
                result_lines.append(f"✗ {r.get('tool','action')}: FAILED — {r.get('error','unknown')}")

        assemble_input = (
            f"User request: {user_message}\n"
            f"Tool results:\n" + "\n".join(result_lines)
        )
        if llm_text:
            assemble_input += f"\nLLM planning text: {llm_text}"

        try:
            response = await self._llm.generate(
                messages=[{"role": "user", "content": assemble_input}],
                system_prompt=ASSEMBLE_PROMPT,
                tools=None,
                temperature=0.7,
                max_tokens=512,
            )
            if response and response.text:
                return response.text
        except Exception as e:
            logger.warning("Assemble LLM call failed, falling back: %s", e)

        # Fallback to mechanical formatting
        return self._format_results(results, llm_text)

    # ─────────────────────────────────────────────────────────────────────
    # Pipeline Executor (innermost — actual MCP call)
    # ─────────────────────────────────────────────────────────────────────

    async def _mcp_execute(self, ctx: ExecutionContext) -> ExecutionResult:
        """The actual MCP call — sits at the center of the middleware chain."""
        resp = await self._mcp_client.call_tool(ctx.tool_name, ctx.params)

        if resp.success:
            return ExecutionResult(success=True, data=resp.result)
        else:
            # Classify retry-ability from error message
            error = resp.error or "Unknown error"
            should_retry = any(s in error.lower() for s in ("429", "rate", "timeout", "5"))
            return ExecutionResult(success=False, error=error, should_retry=should_retry)

    # ─────────────────────────────────────────────────────────────────────
    # Helpers
    # ─────────────────────────────────────────────────────────────────────

    def _build_messages(
        self,
        context_block: str,
        memory_block: str,
        user_message: str,
        history: Optional[List[Dict[str, str]]],
    ) -> List[Dict[str, str]]:
        """Build LLM message array."""
        messages = [
            {"role": "user", "content": f"[CURRENT SERVER STATE]\n{context_block}"},
        ]
        if memory_block:
            messages.append({"role": "user", "content": memory_block})
        messages.append({"role": "assistant", "content": "I have the server state. How can I help?"})

        if history:
            for turn in history[-6:]:
                role = turn.get("role", "user")
                content = turn.get("content", "")
                if role in ("user", "assistant") and content:
                    messages.append({"role": role, "content": content})

        messages.append({"role": "user", "content": user_message})
        return messages

    @staticmethod
    def _result_to_dict(result: ExecutionResult, mcp_name: str) -> Dict[str, Any]:
        """Convert ExecutionResult to legacy dict format for response formatting."""
        return {
            "tool": mcp_name.split(".")[-1] if "." in mcp_name else mcp_name,
            "mcp_name": mcp_name,
            "success": result.success,
            "result": result.data,
            "error": result.error,
            "duration_ms": result.duration_ms,
        }

    def _format_results(self, results: List[Dict], llm_text: str) -> str:
        """Format results with real data — names, IDs, actionable info."""
        if not results:
            return llm_text or "Done."

        lines = []
        for r in results:
            if r["success"]:
                data = r.get("result") or {}
                name = data.get("name") or data.get("channel_name") or data.get("role_name") or ""
                res_id = data.get("id") or data.get("channel_id") or data.get("role_id") or ""
                action = r.get("tool", "action")

                if name and res_id:
                    lines.append(f"✅ **{action}**: `{name}` (ID: {res_id})")
                elif name:
                    lines.append(f"✅ **{action}**: `{name}`")
                elif data.get("deleted"):
                    lines.append(f"✅ **{action}**: Đã xóa `{data.get('name', res_id)}`")
                elif data.get("assigned") or data.get("kicked") or data.get("banned") or data.get("timed_out"):
                    member_name = data.get("member_name") or data.get("name") or ""
                    lines.append(f"✅ **{action}**: {member_name}")
                else:
                    lines.append(f"✅ **{action}**: Thành công")

                if data.get("url"):
                    lines.append(f"   🔗 {data['url']}")
                if data.get("updated_fields"):
                    lines.append(f"   📝 Đã sửa: {', '.join(data['updated_fields'])}")
            else:
                error = r.get("error", "Unknown error")
                action = r.get("tool", "action")
                error_map = {
                    "manage_channels": "Bot thiếu quyền 'Manage Channels'",
                    "manage_roles": "Bot thiếu quyền 'Manage Roles'",
                    "kick_members": "Bot thiếu quyền 'Kick Members'",
                    "ban_members": "Bot thiếu quyền 'Ban Members'",
                    "manage_guild": "Bot thiếu quyền 'Manage Server'",
                }
                friendly = error_map.get(error, error)
                lines.append(f"❌ **{action}**: {friendly}")

        summary = "\n".join(lines)
        return f"{llm_text}\n\n{summary}" if llm_text else summary

    def _describe_action(self, tool_name: str, params: Dict[str, Any]) -> str:
        """Human-readable confirmation prompt."""
        descriptions = {
            "delete_channel": "🗑️ **Xóa kênh** — Hành động không thể hoàn tác!",
            "delete_category": "🗑️ **Xóa danh mục** — Kênh bên trong sẽ mất category!",
            "delete_role": "🗑️ **Xóa role** — Members sẽ mất role này!",
            "kick_member": "👢 **Kick thành viên** — Họ có thể tham gia lại bằng invite.",
            "ban_member": "🔨 **Ban thành viên** — Không thể tham gia lại trừ khi unban.",
            "timeout_member": "🔇 **Timeout thành viên** — Tạm khóa giao tiếp.",
        }
        desc = descriptions.get(tool_name, f"⚠️ **{tool_name}** — Hành động cần xác nhận.")

        target = params.get("channel_id") or params.get("role_id") or params.get("member_id") or params.get("category_id") or ""
        if target:
            desc += f"\n📍 Target: `{target}`"
        reason = params.get("reason")
        if reason:
            desc += f"\n📝 Lý do: {reason}"
        return desc

    @staticmethod
    def _response(type_: str, content: str, tool_results: Optional[List] = None) -> Dict[str, Any]:
        """Build standardized response dict."""
        return {"type": type_, "content": content, "tool_results": tool_results or []}

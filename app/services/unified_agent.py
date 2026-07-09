"""UnifiedAgent v3 — Agentic Architecture (Plan → Execute → Reflect → Adapt).

Agentic Loop:
    Request → LLM Planning → [Approval Gate] → Execute All Tools
           → Observe Results → Reflect (goal achieved?)
           → If not: Replan → Execute → Reflect (max 5 iterations)
           → Assemble friendly response

Key design decisions:
  - Approval is PRE-FLIGHT: check ALL tools before executing ANY
  - Batch approval: one confirm for all high-risk ops (not per-tool)
  - remaining_tools stored as serializable dicts (not objects)
  - Reflect uses fast-path for simple requests (≤2 tools, all success)
  - Recursive _execute_tools avoided — single loop with clean state
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

from app.prompts.system_prompt import UNIFIED_SYSTEM_PROMPT, ASSEMBLE_PROMPT, REFLECT_PROMPT, PLANNER_PROMPT
from app.core.tool_definitions import TOOL_DEFINITIONS, TOOL_NAME_MAP, HIGH_RISK_TOOLS

# Backward-compatible alias
_HIGH_RISK_TOOLS = HIGH_RISK_TOOLS

# Agentic Loop config
MAX_AGENTIC_ITERATIONS = 5


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
# Helper: serialize/deserialize tool calls for payload storage
# ═══════════════════════════════════════════════════════════════════════════

def _serialize_tool_calls(tool_calls: List[NormalizedToolCall]) -> List[Dict[str, Any]]:
    """Convert NormalizedToolCall objects to JSON-safe dicts."""
    return [
        {"name": tc.name, "mcp_name": tc.mcp_name, "arguments": tc.arguments}
        for tc in tool_calls
    ]


def _deserialize_tool_calls(data: List[Dict[str, Any]]) -> List[NormalizedToolCall]:
    """Convert stored dicts back to NormalizedToolCall objects."""
    return [
        NormalizedToolCall(name=d["name"], mcp_name=d["mcp_name"], arguments=d.get("arguments", {}))
        for d in data
    ]


# ═══════════════════════════════════════════════════════════════════════════
# Unified Agent
# ═══════════════════════════════════════════════════════════════════════════

class UnifiedAgent:
    """Agentic AI assistant with Plan → Execute → Reflect loop."""

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
            "UnifiedAgent v3 (Agentic) initialized: pipeline=%d middlewares, guild_lock=%s",
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
        """Process a user message end-to-end."""
        # === Guild Lock ===
        if not self._guild_lock.is_allowed(guild_id):
            return self._response("error", "⛔ Server này chưa được cấp quyền sử dụng bot.")

        # === Check pending approval ===
        pending_req = self._requests.get_awaiting_approval(guild_id, user_id)
        if pending_req:
            return await self._handle_confirmation(message, pending_req)

        # === Create request lifecycle ===
        req = self._requests.create(guild_id, user_id, message)
        req.set_payload("original_message", message)
        req.transition(RequestState.PLANNING)

        # === Build context ===
        server_context = await self._context_service.get_server_context(guild_id)
        context_block = build_server_context_block(server_context)
        memory_block = self._memory.build_context_block(guild_id)

        # === LLM Planning Call ===
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
            return self._response("error", "⚠️ Đã xảy ra lỗi khi xử lý yêu cầu. Vui lòng thử lại.")

        # === Normalize ===
        normalized = self._normalizer.normalize(raw_response)

        if not normalized.usable:
            req.transition(RequestState.FAILED)
            logger.warning("LLM response not usable: %s", normalized.failure_reason)
            return self._response("error", "⚠️ AI không thể xử lý yêu cầu lúc này. Vui lòng thử lại.")

        # === Branch: text-only response ===
        if normalized.is_text_only:
            req.transition(RequestState.COMPLETED)
            return self._response("answer", normalized.text)

        # === Branch: tool calls → Agentic Loop ===
        if normalized.has_tool_calls:
            return await self._agentic_execute(normalized.tool_calls, req, guild_id, user_id)

        # Fallback
        req.transition(RequestState.COMPLETED)
        return self._response("answer", normalized.text or "Không có phản hồi.")

    # ─────────────────────────────────────────────────────────────────────
    # Agentic Execution Loop
    # ─────────────────────────────────────────────────────────────────────

    async def _agentic_execute(
        self,
        tool_calls: List[NormalizedToolCall],
        req: RequestLifecycle,
        guild_id: int,
        user_id: int,
    ) -> Dict[str, Any]:
        """Core agentic loop: Pre-flight → Execute → Observe → Reflect → Adapt.

        This method handles the ENTIRE lifecycle from tool calls to final response.
        It NEVER calls itself recursively. Instead it loops cleanly.
        """
        all_results: List[Dict[str, Any]] = []
        current_tool_calls = tool_calls
        original_message = req.get_payload("original_message", "")

        for iteration in range(1, MAX_AGENTIC_ITERATIONS + 1):
            logger.info("Agentic iteration %d/%d (guild=%d, tools=%d)",
                        iteration, MAX_AGENTIC_ITERATIONS, guild_id, len(current_tool_calls))

            # ┌─────────────────────────────────────────────────────┐
            # │ PHASE 1: PRE-FLIGHT APPROVAL CHECK                  │
            # │ Scan all tools BEFORE executing any.                │
            # │ If high-risk found → batch confirm, pause here.     │
            # └─────────────────────────────────────────────────────┘
            has_high_risk = any(tc.mcp_name in _HIGH_RISK_TOOLS for tc in current_tool_calls)

            if has_high_risk:
                req.transition(RequestState.AWAITING_APPROVAL)
                req.set_payload("pending_batch", {
                    "tool_calls": _serialize_tool_calls(current_tool_calls),
                    "results_so_far": all_results,
                    "iteration": iteration,
                })

                # Build description of ALL high-risk actions
                desc_lines = []
                for tc in current_tool_calls:
                    if tc.mcp_name in _HIGH_RISK_TOOLS:
                        desc_lines.append(f"• {self._describe_action(tc.name, tc.arguments)}")
                desc = "\n".join(desc_lines)
                count = len(desc_lines)

                return self._response(
                    "confirm_needed",
                    f"🔒 **Cần xác nhận {count} hành động nguy hiểm:**\n{desc}\n\n"
                    f"❓ **Xác nhận thực hiện TẤT CẢ?** (reply `có` / `yes` để tiếp tục, `không` / `no` để hủy)",
                    all_results,
                )

            # ┌─────────────────────────────────────────────────────┐
            # │ PHASE 2: EXECUTE ALL TOOLS                          │
            # └─────────────────────────────────────────────────────┘
            req.transition(RequestState.EXECUTING)
            iteration_results = await self._run_tool_batch(current_tool_calls, guild_id, user_id, req)
            all_results.extend(iteration_results)

            # ┌─────────────────────────────────────────────────────┐
            # │ PHASE 3: OBSERVE — Invalidate cache                 │
            # └─────────────────────────────────────────────────────┘
            try:
                if any(r["success"] for r in iteration_results):
                    await self._context_service.invalidate(guild_id)
            except Exception as e:
                logger.warning("Cache invalidation failed: %s", e)

            # ┌─────────────────────────────────────────────────────┐
            # │ PHASE 4: REFLECT — Goal achieved?                   │
            # └─────────────────────────────────────────────────────┘
            reflection = await self._reflect(original_message, all_results)

            if reflection["status"] != "continue":
                break  # Done or failed → exit loop

            # ┌─────────────────────────────────────────────────────┐
            # │ PHASE 5: ADAPT — Replan with fresh context          │
            # └─────────────────────────────────────────────────────┘
            next_steps = reflection.get("next_steps", [])
            logger.info("Agentic loop continuing (iteration %d): %s", iteration, next_steps)

            next_tool_calls = await self._replan(original_message, all_results, next_steps, guild_id)
            if not next_tool_calls:
                break  # Cannot plan more → exit

            current_tool_calls = next_tool_calls

        # ┌─────────────────────────────────────────────────────────────┐
        # │ FINAL: ASSEMBLE — Friendly natural language response        │
        # └─────────────────────────────────────────────────────────────┘
        req.transition(RequestState.COMPLETED)
        content = await self._assemble_response(original_message, all_results)
        return self._response("action", content, all_results)

    # ─────────────────────────────────────────────────────────────────────
    # Confirmation Handler (resumes agentic loop after approval)
    # ─────────────────────────────────────────────────────────────────────

    async def _handle_confirmation(
        self,
        message: str,
        req: RequestLifecycle,
    ) -> Dict[str, Any]:
        """Handle user's yes/no reply. On approval, resumes execution of ALL pending tools."""
        msg_lower = message.lower().strip()
        affirmative = msg_lower in ("có", "yes", "y", "ok", "đồng ý", "xác nhận", "confirm", "1")

        pending = req.get_payload("pending_batch", {})
        guild_id = req.guild_id
        user_id = req.user_id

        if not affirmative:
            req.transition(RequestState.CANCELLED)
            return self._response("answer", "✋ Đã hủy. Không có thay đổi nào được thực hiện.")

        # === User approved → Execute ALL pending tools ===
        await self._audit.log_approval(guild_id, user_id, "batch", "approved")
        req.transition(RequestState.EXECUTING)

        tool_calls_data = pending.get("tool_calls", [])
        all_results: List[Dict[str, Any]] = pending.get("results_so_far", [])
        original_message = req.get_payload("original_message", "")
        iteration = pending.get("iteration", 1)

        # Deserialize and execute all tools (including high-risk — already approved)
        tool_calls = _deserialize_tool_calls(tool_calls_data)
        batch_results = await self._run_tool_batch(tool_calls, guild_id, user_id, req)
        all_results.extend(batch_results)

        # Invalidate cache
        try:
            if any(r["success"] for r in batch_results):
                await self._context_service.invalidate(guild_id)
        except Exception:
            pass

        # === Continue agentic loop (reflect → adapt) ===
        for loop_iter in range(iteration + 1, MAX_AGENTIC_ITERATIONS + 1):
            reflection = await self._reflect(original_message, all_results)

            if reflection["status"] != "continue":
                break

            next_steps = reflection.get("next_steps", [])
            logger.info("Post-approval agentic continue (iter %d): %s", loop_iter, next_steps)

            next_tool_calls = await self._replan(original_message, all_results, next_steps, guild_id)
            if not next_tool_calls:
                break

            # Check if new batch has high-risk (need another approval)
            has_high_risk = any(tc.mcp_name in _HIGH_RISK_TOOLS for tc in next_tool_calls)
            if has_high_risk:
                req.transition(RequestState.AWAITING_APPROVAL)
                req.set_payload("pending_batch", {
                    "tool_calls": _serialize_tool_calls(next_tool_calls),
                    "results_so_far": all_results,
                    "iteration": loop_iter,
                })
                desc_lines = [f"• {self._describe_action(tc.name, tc.arguments)}"
                              for tc in next_tool_calls if tc.mcp_name in _HIGH_RISK_TOOLS]
                return self._response(
                    "confirm_needed",
                    f"🔒 **Tiếp tục cần xác nhận {len(desc_lines)} hành động:**\n"
                    + "\n".join(desc_lines) + "\n\n❓ **Xác nhận?**",
                    all_results,
                )

            # Execute safe batch
            req.transition(RequestState.EXECUTING)
            batch_results = await self._run_tool_batch(next_tool_calls, guild_id, user_id, req)
            all_results.extend(batch_results)

            try:
                if any(r["success"] for r in batch_results):
                    await self._context_service.invalidate(guild_id)
            except Exception:
                pass

        # === Assemble final response ===
        req.transition(RequestState.COMPLETED)
        content = await self._assemble_response(original_message, all_results)
        return self._response("action", content, all_results)

    # ─────────────────────────────────────────────────────────────────────
    # Tool Batch Executor (no approval logic — just runs tools)
    # ─────────────────────────────────────────────────────────────────────

    async def _run_tool_batch(
        self,
        tool_calls: List[NormalizedToolCall],
        guild_id: int,
        user_id: int,
        req: RequestLifecycle,
    ) -> List[Dict[str, Any]]:
        """Execute a batch of tool calls sequentially. No approval checks here."""
        results = []
        for tc in tool_calls:
            params = dict(tc.arguments)
            params["guild_id"] = guild_id

            ctx = ExecutionContext(
                tool_name=tc.mcp_name,
                params=params,
                guild_id=guild_id,
                user_id=user_id,
                risk_level="high" if tc.mcp_name in _HIGH_RISK_TOOLS else "medium",
                request_id=req.id,
            )
            result = await self._pipeline.execute(ctx)
            results.append(self._result_to_dict(result, tc.mcp_name))

        return results

    # ─────────────────────────────────────────────────────────────────────
    # Reflect (is goal achieved?)
    # ─────────────────────────────────────────────────────────────────────

    async def _reflect(
        self,
        original_message: str,
        results: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """Determine if the user's goal has been fully achieved."""
        # Fast path: simple request + all success → skip LLM call
        all_success = all(r["success"] for r in results)
        if all_success and len(results) <= 2:
            return {"status": "done"}

        # Any failure → don't loop (report to user)
        if not all_success:
            return {"status": "done"}  # Let assemble explain the failures

        # Complex success (3+ tools) → ask LLM
        result_summary = "\n".join(
            f"{'✓' if r['success'] else '✗'} {r.get('tool','?')}: success"
            for r in results
        )
        reflect_input = f"Original goal: {original_message}\nExecution results:\n{result_summary}"

        try:
            response = await self._llm.generate(
                messages=[{"role": "user", "content": reflect_input}],
                system_prompt=REFLECT_PROMPT,
                tools=None,
                temperature=0.1,
                max_tokens=256,
            )
            if response and response.content:
                text = response.content.strip()
                # Handle markdown code blocks
                if text.startswith("```"):
                    text = text.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
                return json.loads(text)
        except (json.JSONDecodeError, Exception) as e:
            logger.warning("Reflection failed: %s", e)

        # Fallback: assume done
        return {"status": "done"}

    # ─────────────────────────────────────────────────────────────────────
    # Replan (get next tool calls for remaining steps)
    # ─────────────────────────────────────────────────────────────────────

    async def _replan(
        self,
        original_message: str,
        results_so_far: List[Dict[str, Any]],
        next_steps: List[str],
        guild_id: int,
    ) -> Optional[List[NormalizedToolCall]]:
        """Ask LLM for next tool calls based on what's done and what's needed."""
        server_context = await self._context_service.get_server_context(guild_id, force_refresh=True)
        context_block = build_server_context_block(server_context)

        result_summary = "\n".join(
            f"{'✓' if r['success'] else '✗'} {r.get('tool','?')}: "
            f"{r.get('result', {}).get('name', '') if r['success'] else r.get('error','')}"
            for r in results_so_far
        )

        replan_input = (
            f"Original request: {original_message}\n\n"
            f"Already completed:\n{result_summary}\n\n"
            f"Still needed:\n" + "\n".join(f"- {s}" for s in next_steps) + "\n\n"
            f"Current server state:\n{context_block}\n\n"
            f"Call the appropriate tools for the remaining steps."
        )

        try:
            response = await self._llm.generate(
                messages=[{"role": "user", "content": replan_input}],
                system_prompt=UNIFIED_SYSTEM_PROMPT,
                tools=TOOL_DEFINITIONS,
                temperature=0.2,
                max_tokens=2048,
            )
            if response:
                normalized = self._normalizer.normalize(response)
                if normalized.usable and normalized.has_tool_calls:
                    return normalized.tool_calls
        except Exception as e:
            logger.warning("Replan failed: %s", e)

        return None

    # ─────────────────────────────────────────────────────────────────────
    # Assemble (natural language response)
    # ─────────────────────────────────────────────────────────────────────

    async def _assemble_response(
        self,
        user_message: str,
        results: List[Dict[str, Any]],
    ) -> str:
        """LLM call to produce a friendly, natural response."""
        result_lines = []
        for r in results:
            if r["success"]:
                data = r.get("result") or {}
                name = data.get("name") or data.get("channel_name") or data.get("role_name") or ""
                result_lines.append(f"✓ {r.get('tool','action')}: {name} (success)")
            else:
                result_lines.append(f"✗ {r.get('tool','action')}: FAILED — {r.get('error','unknown')}")

        assemble_input = f"User request: {user_message}\nTool results:\n" + "\n".join(result_lines)

        try:
            response = await self._llm.generate(
                messages=[{"role": "user", "content": assemble_input}],
                system_prompt=ASSEMBLE_PROMPT,
                tools=None,
                temperature=0.7,
                max_tokens=512,
            )
            if response and response.content:
                return response.content.strip()
        except Exception as e:
            logger.warning("Assemble failed, using fallback: %s", e)

        # Fallback
        return self._format_results_fallback(results)

    # ─────────────────────────────────────────────────────────────────────
    # Pipeline Executor (innermost MCP call)
    # ─────────────────────────────────────────────────────────────────────

    async def _mcp_execute(self, ctx: ExecutionContext) -> ExecutionResult:
        """Actual MCP tool call — center of middleware chain."""
        resp = await self._mcp_client.call_tool(ctx.tool_name, ctx.params)
        if resp.success:
            return ExecutionResult(success=True, data=resp.result)
        else:
            error = resp.error or "Unknown error"
            should_retry = any(s in error.lower() for s in ("429", "rate", "timeout"))
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
        """Build LLM message array with server context + history."""
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
        """Convert ExecutionResult to dict for storage/response."""
        return {
            "tool": mcp_name.split(".")[-1] if "." in mcp_name else mcp_name,
            "mcp_name": mcp_name,
            "success": result.success,
            "result": result.data,
            "error": result.error,
            "duration_ms": result.duration_ms,
        }

    def _format_results_fallback(self, results: List[Dict]) -> str:
        """Mechanical formatting fallback when LLM assemble fails."""
        lines = []
        for r in results:
            if r["success"]:
                data = r.get("result") or {}
                name = data.get("name") or ""
                action = r.get("tool", "action")
                lines.append(f"✅ {action}: {name}" if name else f"✅ {action}")
            else:
                lines.append(f"❌ {r.get('tool','action')}: {r.get('error','failed')}")
        return "\n".join(lines) or "Done."

    def _describe_action(self, tool_name: str, params: Dict[str, Any]) -> str:
        """Human-readable description for confirmation prompts."""
        descriptions = {
            "delete_channel": "🗑️ **Xóa kênh**",
            "delete_category": "🗑️ **Xóa danh mục**",
            "delete_role": "🗑️ **Xóa role**",
            "kick_member": "👢 **Kick thành viên**",
            "ban_member": "🔨 **Ban thành viên**",
            "timeout_member": "🔇 **Timeout thành viên**",
        }
        desc = descriptions.get(tool_name, f"⚠️ **{tool_name}**")
        target = (params.get("channel_id") or params.get("role_id") or
                  params.get("member_id") or params.get("category_id") or
                  params.get("name") or "")
        if target:
            desc += f" `{target}`"
        return desc

    @staticmethod
    def _response(type_: str, content: str, tool_results: Optional[List] = None) -> Dict[str, Any]:
        """Build standardized response dict."""
        return {"type": type_, "content": content, "tool_results": tool_results or []}

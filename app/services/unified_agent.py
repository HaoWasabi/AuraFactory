"""UnifiedAgent v4 — Perceive-Plan-Act Loop Architecture.

Architecture:
    Input → Perceive → Plan (sub-goals) → Loop:
        ├─ Decide next action (tool call / ask user / answer)
        ├─ If side-effect → approval gate
        ├─ Execute
        ├─ Reflect: goal met? error? re-plan?
        └─ Stop when goals satisfied OR max iterations
    → Self-check → Assemble & respond

Design principles:
  - GOAL-ORIENTED: Plan produces sub-goals, not fixed tool lists
  - ADAPTIVE: Each loop iteration decides 1 action based on current state
  - PROACTIVE ERROR PREVENTION: Check conditions before execute
  - SINGLE RESPONSIBILITY: Each phase has a clear, testable method
  - SPEC-DRIVEN: Tools from SpecRegistry, knowledge from SkillLoader
  - KWARGS PATTERN: All tool params via **kwargs, validated by KwargsFilter
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any, Dict, FrozenSet, List, Optional, Set

from app.config import settings
from app.llm.base import BaseLLM, LLMResponse
from app.mcp import MCPClient
from app.services.context_service import ContextService

# Token tracking
from app.services._token_tracker import record_token_usage

# Normalizer
from app.core.normalizer import LLMResponseNormalizer, NormalizedLLMOutput, NormalizedToolCall

# Request Lifecycle
from app.core.request_lifecycle import RequestStore, RequestLifecycle, RequestState

# Middleware Pipeline
from app.core.middleware import (
    ExecutionPipeline, ExecutionContext, ExecutionResult,
    ErrorBoundaryMiddleware, RateLimitMiddleware,
    RetryMiddleware, AuditMiddleware, MemoryMiddleware,
)

# Safety
from app.core.safety import AuditLogger, GuildLock, ConversationMemory

# Prompts
from app.prompts.system_prompt import UNIFIED_SYSTEM_PROMPT, ASSEMBLE_PROMPT, REFLECT_PROMPT

# Registry + Skills
from app.core.spec_loader import SpecRegistry
from app.core.skill_loader import SkillLoader

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════════════
# Config (unchanged from v3.1)
# ═══════════════════════════════════════════════════════════════════════════════

class AgentConfig:
    """Resolves configuration: env var → YAML default → hardcoded fallback."""

    def __init__(self, registry: Optional[SpecRegistry] = None) -> None:
        self._registry = registry

    def _resolve(self, env_value: Any, yaml_key: str, fallback: Any) -> Any:
        if env_value:
            return env_value
        if self._registry:
            yaml_val = self._registry.get_default(yaml_key)
            if yaml_val is not None:
                return type(fallback)(yaml_val) if yaml_val != fallback else fallback
        return fallback

    @property
    def max_iterations(self) -> int:
        return self._resolve(settings.AGENTIC_MAX_ITERATIONS, "max_iterations", 5)

    @property
    def temp_planning(self) -> float:
        return self._resolve(settings.LLM_TEMP_PLANNING, "temperature_planning", 0.2)

    @property
    def temp_reflect(self) -> float:
        return self._resolve(settings.LLM_TEMP_REFLECT, "temperature_reflect", 0.1)

    @property
    def temp_assemble(self) -> float:
        return self._resolve(settings.LLM_TEMP_ASSEMBLE, "temperature_assemble", 0.7)

    @property
    def max_tokens_planning(self) -> int:
        return self._resolve(settings.LLM_MAX_TOKENS_PLANNING, "max_tokens_planning", 2048)

    @property
    def max_tokens_reflect(self) -> int:
        return self._resolve(0, "max_tokens_reflect", 256)

    @property
    def max_tokens_assemble(self) -> int:
        return self._resolve(0, "max_tokens_assemble", 512)

    @property
    def context_max_categories(self) -> int:
        return self._resolve(settings.CONTEXT_MAX_CATEGORIES, "context_max_categories", 20)

    @property
    def context_max_channels(self) -> int:
        return self._resolve(settings.CONTEXT_MAX_CHANNELS, "context_max_channels", 40)

    @property
    def context_max_roles(self) -> int:
        return self._resolve(settings.CONTEXT_MAX_ROLES, "context_max_roles", 20)

    @property
    def context_history_turns(self) -> int:
        return self._resolve(settings.CONTEXT_HISTORY_TURNS, "context_history_turns", 6)

    @property
    def approval_ttl(self) -> float:
        return float(self._resolve(settings.APPROVAL_TTL, "approval_ttl_seconds", 300))

    @property
    def rate_limit_burst(self) -> int:
        return self._resolve(settings.RATE_LIMIT_BURST, "rate_limit_burst", 5)

    @property
    def rate_limit_delay(self) -> float:
        return float(self._resolve(0, "rate_limit_min_delay", 0.5))

    @property
    def retry_max(self) -> int:
        return self._resolve(settings.RETRY_MAX, "retry_max_attempts", 3)

    @property
    def retry_base_delay(self) -> float:
        return float(self._resolve(0, "retry_base_delay", 1.0))

    @property
    def confirmation_words(self) -> List[str]:
        env_val = settings.CONFIRMATION_WORDS
        if env_val:
            return [w.strip() for w in env_val.split(",") if w.strip()]
        if self._registry:
            yaml_val = self._registry.get_default("confirmation_words", "")
            if yaml_val:
                return [w.strip() for w in str(yaml_val).split(",") if w.strip()]
        return ["yes", "y", "ok", "confirm", "có", "đồng ý", "xác nhận", "1"]


# ═══════════════════════════════════════════════════════════════════════════════
# Context Builder
# ═══════════════════════════════════════════════════════════════════════════════

def build_server_context_block(server_context: dict, cfg: AgentConfig) -> str:
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
        features = server_info.get("features", [])
        parts.append(f"Server: {name} ({members} members, features: {features})")

    if categories:
        cat_lines = [f"  {c.get('id', '?')}: {c.get('name', '?')}"
                     for c in categories[:cfg.context_max_categories]]
        parts.append("Categories:\n" + "\n".join(cat_lines))

    if channels:
        ch_lines = []
        for ch in channels[:cfg.context_max_channels]:
            ch_type = ch.get("type", "text")
            cat_id = ch.get("category_id", "none")
            ch_lines.append(f"  {ch.get('id', '?')}: #{ch.get('name', '?')} ({ch_type}) [cat:{cat_id}]")
        parts.append("Channels:\n" + "\n".join(ch_lines))

    if roles:
        role_lines = [f"  {r.get('id', '?')}: @{r.get('name', '?')} (pos:{r.get('position', 0)})"
                      for r in roles[:cfg.context_max_roles] if r.get("name") != "@everyone"]
        parts.append("Roles:\n" + "\n".join(role_lines))

    return "\n\n".join(parts) if parts else "Server is empty or bot has no cached data."


# ═══════════════════════════════════════════════════════════════════════════════
# Serialization helpers
# ═══════════════════════════════════════════════════════════════════════════════

def _serialize_tool_calls(tool_calls: List[NormalizedToolCall]) -> List[Dict[str, Any]]:
    return [{"name": tc.name, "mcp_name": tc.mcp_name, "arguments": tc.arguments} for tc in tool_calls]


def _deserialize_tool_calls(data: List[Dict[str, Any]]) -> List[NormalizedToolCall]:
    return [NormalizedToolCall(name=d["name"], mcp_name=d["mcp_name"], arguments=d.get("arguments", {})) for d in data]


# ═══════════════════════════════════════════════════════════════════════════════
# UnifiedAgent v4 — Perceive-Plan-Act Loop
# ═══════════════════════════════════════════════════════════════════════════════

class UnifiedAgent:
    """Agentic AI with Perceive → Plan → Act Loop → Self-check → Assemble."""

    def __init__(
        self,
        llm: BaseLLM,
        mcp_client: MCPClient,
        context_service: ContextService,
        db=None,
        registry: Optional[SpecRegistry] = None,
    ) -> None:
        self._llm = llm
        self._mcp_client = mcp_client
        self._context_service = context_service
        self._db = db
        self._registry = registry

        # Config
        self._cfg = AgentConfig(registry)

        # Tool definitions from SpecRegistry
        if registry:
            self._tool_definitions = registry.get_llm_definitions()
            self._tool_name_map = registry.get_tool_name_map()
            self._high_risk_tools = registry.get_high_risk_tools()
        else:
            from app.core.tool_definitions import TOOL_DEFINITIONS, TOOL_NAME_MAP, HIGH_RISK_TOOLS
            self._tool_definitions = TOOL_DEFINITIONS
            self._tool_name_map = TOOL_NAME_MAP
            self._high_risk_tools = HIGH_RISK_TOOLS
            logger.warning("SpecRegistry not available — using legacy tool_definitions.py")

        # Normalizer
        self._normalizer = LLMResponseNormalizer(tool_name_map=self._tool_name_map)

        # Request Store (in-memory state for approval flow)
        self._requests = RequestStore(default_ttl=self._cfg.approval_ttl)

        # Skills (knowledge docs)
        self._skills = SkillLoader()

        # Middleware Pipeline
        self._memory = ConversationMemory()
        self._audit = AuditLogger(db=db)
        self._pipeline = ExecutionPipeline(
            middlewares=[
                ErrorBoundaryMiddleware(),
                AuditMiddleware(self._audit),
                RateLimitMiddleware(
                    min_delay=self._cfg.rate_limit_delay,
                    burst_limit=self._cfg.rate_limit_burst,
                ),
                RetryMiddleware(
                    max_retries=self._cfg.retry_max,
                    base_delay=self._cfg.retry_base_delay,
                ),
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
            "UnifiedAgent v4 (Perceive-Plan-Act) initialized: %d tools, %d high-risk, "
            "%d skills, max_iter=%d",
            len(self._tool_definitions), len(self._high_risk_tools),
            self._skills.skill_count, self._cfg.max_iterations,
        )

    # ─────────────────────────────────────────────────────────────────────────
    # MAIN ENTRY POINT
    # ─────────────────────────────────────────────────────────────────────────

    async def process(
        self,
        message: str,
        guild_id: int,
        user_id: int,
        history: Optional[List[Dict[str, str]]] = None,
    ) -> Dict[str, Any]:
        """Process a user message end-to-end with the Perceive-Plan-Act loop."""

        # === Guild Lock ===
        if not self._guild_lock.is_allowed(guild_id):
            return self._response("error", "⛔ This server is not authorized to use the bot.")

        # === Check pending approval ===
        pending_req = self._requests.get_awaiting_approval(guild_id, user_id)
        if pending_req:
            return await self._handle_confirmation(message, pending_req)

        # === Create request lifecycle ===
        req = self._requests.create(guild_id, user_id, message)
        req.set_payload("original_message", message)

        # ══════════════════════════════════════════════════════════════════
        # PHASE 1: PERCEIVE — Gather context, understand situation
        # ══════════════════════════════════════════════════════════════════
        req.transition(RequestState.PLANNING)

        server_context = await self._context_service.get_server_context(guild_id)
        context_block = build_server_context_block(server_context, self._cfg)
        memory_block = self._memory.build_context_block(guild_id)
        skills_block = self._skills.get_relevant_skills()

        # ══════════════════════════════════════════════════════════════════
        # PHASE 2: PLAN — LLM decides what to do (tools or text response)
        # ══════════════════════════════════════════════════════════════════
        messages = self._build_messages(context_block, skills_block, memory_block, message, history)

        try:
            raw_response: LLMResponse = await self._llm.generate(
                messages=messages,
                system_prompt=UNIFIED_SYSTEM_PROMPT,
                tools=self._tool_definitions,
                temperature=self._cfg.temp_planning,
                max_tokens=self._cfg.max_tokens_planning,
            )
        except Exception as e:
            logger.error("LLM call failed: %s", e, exc_info=True)
            req.transition(RequestState.FAILED)
            return self._response("error", "⚠️ An error occurred while processing your request. Please try again.")

        # Track tokens
        if hasattr(raw_response, 'usage') and raw_response.usage:
            await record_token_usage(self._db, guild_id, user_id, raw_response.usage,
                                     provider=settings.LLM_PROVIDER, phase="planning")

        # === Normalize LLM output ===
        normalized = self._normalizer.normalize(raw_response)

        if not normalized.usable:
            req.transition(RequestState.FAILED)
            logger.warning("LLM response not usable: %s", normalized.failure_reason)
            return self._response("error", "⚠️ AI cannot process this request right now. Please try again.")

        # === Branch: text-only (query/clarify/out_of_scope) ===
        if normalized.is_text_only:
            req.transition(RequestState.COMPLETED)
            return self._response("answer", normalized.text)

        # === Branch: tool calls → Enter Act Loop ===
        if normalized.has_tool_calls:
            return await self._act_loop(normalized.tool_calls, req, guild_id, user_id, message)

        # Fallback
        req.transition(RequestState.COMPLETED)
        return self._response("answer", normalized.text or "No response.")

    # ─────────────────────────────────────────────────────────────────────────
    # PHASE 3: ACT LOOP — Execute → Reflect → Adapt (per-action)
    # ─────────────────────────────────────────────────────────────────────────

    async def _act_loop(
        self,
        tool_calls: List[NormalizedToolCall],
        req: RequestLifecycle,
        guild_id: int,
        user_id: int,
        original_message: str = "",
    ) -> Dict[str, Any]:
        """Core act loop: for each iteration, execute tools → reflect → decide next."""
        all_results: List[Dict[str, Any]] = []
        current_tool_calls = tool_calls

        for iteration in range(1, self._cfg.max_iterations + 1):
            logger.info("Act loop iter %d/%d (guild=%d, pending_tools=%d)",
                        iteration, self._cfg.max_iterations, guild_id, len(current_tool_calls))

            # ┌──────────────────────────────────────────────────────┐
            # │ STEP A: APPROVAL GATE — side-effect check            │
            # └──────────────────────────────────────────────────────┘
            high_risk_in_batch = [
                tc for tc in current_tool_calls
                if tc.mcp_name in self._high_risk_tools
            ]

            if high_risk_in_batch:
                req.transition(RequestState.AWAITING_APPROVAL)
                req.set_payload("pending_batch", {
                    "tool_calls": _serialize_tool_calls(current_tool_calls),
                    "results_so_far": all_results,
                    "iteration": iteration,
                    "original_message": original_message,
                })

                desc_lines = [
                    f"• {self._get_action_label(tc.mcp_name, tc.arguments)}"
                    for tc in high_risk_in_batch
                ]
                return self._response(
                    "confirm_needed",
                    f"🔒 **{len(desc_lines)} high-risk action(s) require confirmation:**\n"
                    + "\n".join(desc_lines) + "\n\n❓ **Confirm?** (yes/no)",
                    all_results,
                )

            # ┌──────────────────────────────────────────────────────┐
            # │ STEP B: EXECUTE — run tools sequentially             │
            # └──────────────────────────────────────────────────────┘
            req.transition(RequestState.EXECUTING)
            iteration_results = await self._run_tool_batch(current_tool_calls, guild_id, user_id, req)
            all_results.extend(iteration_results)

            # ┌──────────────────────────────────────────────────────┐
            # │ STEP C: OBSERVE — invalidate cache on success        │
            # └──────────────────────────────────────────────────────┘
            try:
                if any(r["success"] for r in iteration_results):
                    await self._context_service.invalidate(guild_id)
            except Exception as e:
                logger.warning("Cache invalidation failed: %s", e)

            # ┌──────────────────────────────────────────────────────┐
            # │ STEP D: REFLECT — goal achieved? errors? re-plan?    │
            # └──────────────────────────────────────────────────────┘
            reflection = await self._reflect(original_message, all_results)

            if reflection["status"] != "continue":
                break

            # ┌──────────────────────────────────────────────────────┐
            # │ STEP E: ADAPT — re-plan with fresh context           │
            # └──────────────────────────────────────────────────────┘
            next_steps = reflection.get("next_steps", [])
            logger.info("Act loop continuing: %s", next_steps)

            next_tool_calls = await self._replan(original_message, all_results, next_steps, guild_id)
            if not next_tool_calls:
                break

            current_tool_calls = next_tool_calls

        # ┌─────────────────────────────────────────────────────────────┐
        # │ PHASE 4: SELF-CHECK — verify results match original goal    │
        # └─────────────────────────────────────────────────────────────┘
        # (Simple version: check all success. Future: LLM verification)
        failures = [r for r in all_results if not r["success"]]
        if failures:
            logger.warning("Self-check: %d/%d actions failed", len(failures), len(all_results))

        # ┌─────────────────────────────────────────────────────────────┐
        # │ PHASE 5: ASSEMBLE — natural language response               │
        # └─────────────────────────────────────────────────────────────┘
        req.transition(RequestState.COMPLETED)
        content = await self._assemble_response(original_message, all_results)
        return self._response("action", content, all_results)

    # ─────────────────────────────────────────────────────────────────────────
    # Confirmation Handler
    # ─────────────────────────────────────────────────────────────────────────

    async def _handle_confirmation(
        self,
        message: str,
        req: RequestLifecycle,
    ) -> Dict[str, Any]:
        """Handle user's yes/no reply to approval request."""
        msg_lower = message.lower().strip()
        affirmative = msg_lower in self._cfg.confirmation_words

        pending = req.get_payload("pending_batch", {})
        guild_id = req.guild_id
        user_id = req.user_id
        original_message = pending.get("original_message", "")

        if not affirmative:
            req.transition(RequestState.CANCELLED)
            return self._response("answer", "✋ Cancelled. No changes were made.")

        # === User approved → resume act loop ===
        await self._audit.log_approval(guild_id, user_id, "batch", "approved")
        req.transition(RequestState.EXECUTING)

        tool_calls_data = pending.get("tool_calls", [])
        all_results: List[Dict[str, Any]] = pending.get("results_so_far", [])
        iteration = pending.get("iteration", 1)

        # Execute approved tools
        tool_calls = _deserialize_tool_calls(tool_calls_data)
        batch_results = await self._run_tool_batch(tool_calls, guild_id, user_id, req)
        all_results.extend(batch_results)

        # Invalidate cache
        try:
            if any(r["success"] for r in batch_results):
                await self._context_service.invalidate(guild_id)
        except Exception:
            pass

        # Continue act loop for remaining iterations
        for loop_iter in range(iteration + 1, self._cfg.max_iterations + 1):
            reflection = await self._reflect(original_message, all_results)
            if reflection["status"] != "continue":
                break

            next_steps = reflection.get("next_steps", [])
            next_tool_calls = await self._replan(original_message, all_results, next_steps, guild_id)
            if not next_tool_calls:
                break

            # Check for new high-risk tools
            high_risk = [tc for tc in next_tool_calls if tc.mcp_name in self._high_risk_tools]
            if high_risk:
                req.transition(RequestState.AWAITING_APPROVAL)
                req.set_payload("pending_batch", {
                    "tool_calls": _serialize_tool_calls(next_tool_calls),
                    "results_so_far": all_results,
                    "iteration": loop_iter,
                    "original_message": original_message,
                })
                desc_lines = [f"• {self._get_action_label(tc.mcp_name, tc.arguments)}" for tc in high_risk]
                return self._response(
                    "confirm_needed",
                    f"🔒 **{len(desc_lines)} more action(s) need confirmation:**\n"
                    + "\n".join(desc_lines) + "\n\n❓ **Confirm?**",
                    all_results,
                )

            req.transition(RequestState.EXECUTING)
            batch_results = await self._run_tool_batch(next_tool_calls, guild_id, user_id, req)
            all_results.extend(batch_results)
            try:
                if any(r["success"] for r in batch_results):
                    await self._context_service.invalidate(guild_id)
            except Exception:
                pass

        # Assemble
        req.transition(RequestState.COMPLETED)
        content = await self._assemble_response(original_message, all_results)
        return self._response("action", content, all_results)

    # ─────────────────────────────────────────────────────────────────────────
    # Tool Batch Executor
    # ─────────────────────────────────────────────────────────────────────────

    async def _run_tool_batch(
        self,
        tool_calls: List[NormalizedToolCall],
        guild_id: int,
        user_id: int,
        req: RequestLifecycle,
    ) -> List[Dict[str, Any]]:
        """Execute tools sequentially. Each tool gets output of previous (for dependencies)."""
        results = []
        for tc in tool_calls:
            params = dict(tc.arguments)
            params["guild_id"] = guild_id

            ctx = ExecutionContext(
                tool_name=tc.mcp_name,
                params=params,
                guild_id=guild_id,
                user_id=user_id,
                risk_level="high" if tc.mcp_name in self._high_risk_tools else "medium",
                request_id=req.id,
            )
            result = await self._pipeline.execute(ctx)
            results.append(self._result_to_dict(result, tc.mcp_name))

        return results

    # ─────────────────────────────────────────────────────────────────────────
    # Reflect
    # ─────────────────────────────────────────────────────────────────────────

    async def _reflect(
        self,
        original_message: str,
        results: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """Determine if the user's goal has been fully achieved."""
        all_success = all(r["success"] for r in results)

        # Fast path: simple + all success → done
        if all_success and len(results) <= 2:
            return {"status": "done"}

        # Failures present → ask LLM to diagnose
        if not all_success:
            failed_summary = "\n".join(
                f"✗ {r.get('tool', '?')}: {r.get('error', 'unknown')}"
                for r in results if not r["success"]
            )
            success_summary = "\n".join(
                f"✓ {r.get('tool', '?')}: success"
                for r in results if r["success"]
            )
            reflect_input = (
                f"Original goal: {original_message}\n\n"
                f"Successes:\n{success_summary or '(none)'}\n\n"
                f"Failures:\n{failed_summary}\n\n"
                f"Should the agent: (a) retry with different params, "
                f"(b) skip failed steps and continue, or (c) stop and report to user?"
            )
            try:
                response = await self._llm.generate(
                    messages=[{"role": "user", "content": reflect_input}],
                    system_prompt=REFLECT_PROMPT,
                    tools=None,
                    temperature=self._cfg.temp_reflect,
                    max_tokens=self._cfg.max_tokens_reflect,
                )
                if response and hasattr(response, 'usage') and response.usage:
                    await record_token_usage(self._db, 0, 0, response.usage,
                                             provider=settings.LLM_PROVIDER, phase="reflect")
                if response and response.content:
                    text = response.content.strip()
                    if text.startswith("```"):
                        text = text.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
                    return json.loads(text)
            except (json.JSONDecodeError, Exception) as e:
                logger.warning("Reflect on failure failed: %s", e)
            # Fallback: if ALL failed, stop. If some succeeded, done.
            if all(not r["success"] for r in results):
                return {"status": "failed", "reason": "All actions failed"}
            return {"status": "done"}

        # Complex success → ask LLM if more steps needed
        result_summary = "\n".join(
            f"{'✓' if r['success'] else '✗'} {r.get('tool', '?')}: success"
            for r in results
        )
        reflect_input = f"Original goal: {original_message}\nExecution results:\n{result_summary}"

        try:
            response = await self._llm.generate(
                messages=[{"role": "user", "content": reflect_input}],
                system_prompt=REFLECT_PROMPT,
                tools=None,
                temperature=self._cfg.temp_reflect,
                max_tokens=self._cfg.max_tokens_reflect,
            )
            if response and hasattr(response, 'usage') and response.usage:
                await record_token_usage(self._db, 0, 0, response.usage,
                                         provider=settings.LLM_PROVIDER, phase="reflect")
            if response and response.content:
                text = response.content.strip()
                if text.startswith("```"):
                    text = text.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
                return json.loads(text)
        except (json.JSONDecodeError, Exception) as e:
            logger.warning("Reflection failed: %s", e)

        return {"status": "done"}

    # ─────────────────────────────────────────────────────────────────────────
    # Replan
    # ─────────────────────────────────────────────────────────────────────────

    async def _replan(
        self,
        original_message: str,
        results_so_far: List[Dict[str, Any]],
        next_steps: List[str],
        guild_id: int,
    ) -> Optional[List[NormalizedToolCall]]:
        """Re-plan with fresh context based on what's done and what's needed."""
        server_context = await self._context_service.get_server_context(guild_id, force_refresh=True)
        context_block = build_server_context_block(server_context, self._cfg)

        # Targeted skills based on used tools
        used_tools = [r.get("mcp_name", r.get("tool", "")) for r in results_so_far]
        skills_block = self._skills.get_relevant_skills(tool_names=used_tools)
        skills_section = f"\n\nTool knowledge:\n{skills_block}" if skills_block else ""

        result_summary = "\n".join(
            f"{'✓' if r['success'] else '✗'} {r.get('tool', '?')}: "
            f"{r.get('result', {}).get('name', '') if r['success'] else r.get('error', '')}"
            for r in results_so_far
        )

        replan_input = (
            f"Original request: {original_message}\n\n"
            f"Already completed:\n{result_summary}\n\n"
            f"Still needed:\n" + "\n".join(f"- {s}" for s in next_steps) + "\n\n"
            f"Current server state:\n{context_block}"
            f"{skills_section}\n\n"
            f"Call the appropriate tools for the remaining steps."
        )

        try:
            response = await self._llm.generate(
                messages=[{"role": "user", "content": replan_input}],
                system_prompt=UNIFIED_SYSTEM_PROMPT,
                tools=self._tool_definitions,
                temperature=self._cfg.temp_planning,
                max_tokens=self._cfg.max_tokens_planning,
            )
            if response and hasattr(response, 'usage') and response.usage:
                await record_token_usage(self._db, 0, 0, response.usage,
                                         provider=settings.LLM_PROVIDER, phase="replan")
            if response:
                normalized = self._normalizer.normalize(response)
                if normalized.usable and normalized.has_tool_calls:
                    return normalized.tool_calls
        except Exception as e:
            logger.warning("Replan failed: %s", e)

        return None

    # ─────────────────────────────────────────────────────────────────────────
    # Assemble
    # ─────────────────────────────────────────────────────────────────────────

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
                name = (data.get("name") or data.get("channel_name") or
                        data.get("role_name") or data.get("id") or "")
                result_lines.append(f"✓ {r.get('tool', 'action')}: {name} (success)")
            else:
                result_lines.append(f"✗ {r.get('tool', 'action')}: FAILED — {r.get('error', 'unknown')}")

        assemble_input = f"User request: {user_message}\nTool results:\n" + "\n".join(result_lines)

        try:
            response = await self._llm.generate(
                messages=[{"role": "user", "content": assemble_input}],
                system_prompt=ASSEMBLE_PROMPT,
                tools=None,
                temperature=self._cfg.temp_assemble,
                max_tokens=self._cfg.max_tokens_assemble,
            )
            if response and hasattr(response, 'usage') and response.usage:
                await record_token_usage(self._db, 0, 0, response.usage,
                                         provider=settings.LLM_PROVIDER, phase="assemble")
            if response and response.content:
                return response.content.strip()
        except Exception as e:
            logger.warning("Assemble failed, using fallback: %s", e)

        return self._format_results_fallback(results)

    # ─────────────────────────────────────────────────────────────────────────
    # MCP Executor (innermost)
    # ─────────────────────────────────────────────────────────────────────────

    async def _mcp_execute(self, ctx: ExecutionContext) -> ExecutionResult:
        """Actual MCP tool call — center of middleware chain."""
        resp = await self._mcp_client.call_tool(ctx.tool_name, ctx.params)
        if resp.success:
            return ExecutionResult(success=True, data=resp.result)
        else:
            error = resp.error or "Unknown error"
            should_retry = any(s in error.lower() for s in ("429", "rate", "timeout"))
            return ExecutionResult(success=False, error=error, should_retry=should_retry)

    # ─────────────────────────────────────────────────────────────────────────
    # Message Builder
    # ─────────────────────────────────────────────────────────────────────────

    def _build_messages(
        self,
        context_block: str,
        skills_block: str,
        memory_block: str,
        user_message: str,
        history: Optional[List[Dict[str, str]]],
    ) -> List[Dict[str, str]]:
        """Build LLM message array with server context + skills + history."""
        messages = [
            {"role": "user", "content": f"[CURRENT SERVER STATE]\n{context_block}"},
        ]

        # Inject skill knowledge
        if skills_block:
            messages.append({"role": "user", "content": f"[TOOL KNOWLEDGE]\n{skills_block}"})

        if memory_block:
            messages.append({"role": "user", "content": memory_block})

        messages.append({"role": "assistant", "content": "I have the server state and tool knowledge. How can I help?"})

        # Conversation history
        if history:
            for turn in history[-self._cfg.context_history_turns:]:
                role = turn.get("role", "user")
                content = turn.get("content", "")
                if role in ("user", "assistant") and content:
                    messages.append({"role": role, "content": content})

        messages.append({"role": "user", "content": user_message})
        return messages

    # ─────────────────────────────────────────────────────────────────────────
    # Helpers
    # ─────────────────────────────────────────────────────────────────────────

    def _get_action_label(self, mcp_name: str, params: Dict[str, Any]) -> str:
        """Human-readable label for confirmation prompts."""
        if self._registry:
            label = self._registry.get_human_label(mcp_name)
        else:
            label = f"⚠️ **{mcp_name}**"
        target = (params.get("channel_id") or params.get("role_id") or
                  params.get("member_id") or params.get("category_id") or
                  params.get("name") or "")
        if target:
            label += f" `{target}`"
        return label

    @staticmethod
    def _result_to_dict(result: ExecutionResult, mcp_name: str) -> Dict[str, Any]:
        return {
            "tool": mcp_name.split(".")[-1] if "." in mcp_name else mcp_name,
            "mcp_name": mcp_name,
            "success": result.success,
            "result": result.data,
            "error": result.error,
            "duration_ms": result.duration_ms,
        }

    @staticmethod
    def _format_results_fallback(results: List[Dict]) -> str:
        lines = []
        for r in results:
            if r["success"]:
                data = r.get("result") or {}
                name = data.get("name") or ""
                action = r.get("tool", "action")
                lines.append(f"✅ {action}: {name}" if name else f"✅ {action}")
            else:
                lines.append(f"❌ {r.get('tool', 'action')}: {r.get('error', 'failed')}")
        return "\n".join(lines) or "Done."

    @staticmethod
    def _response(type_: str, content: str, tool_results: Optional[List] = None) -> Dict[str, Any]:
        return {"type": type_, "content": content, "tool_results": tool_results or []}

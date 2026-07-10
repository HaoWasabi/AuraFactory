"""UnifiedAgent v6 — Closed-Loop Agentic Architecture.

State Machine: IDLE → UNDERSTAND → ACT (loop) → EVALUATE → RESPOND
                                   ↕ AWAITING_CLARIFY (resume → UNDERSTAND)
                                   ↕ AWAITING_APPROVAL (resume → ACT at paused step)

Design principles (from AGENTIC_ARCHITECTURE_V6.md):
  1. Zero dead-end: every branch leads to a result
  2. Goal-aware: effective_goal persists across turns
  3. Dependency-resolved: $stepN.field forward injection, explicit fail on unresolved
  4. Single LLM contract: 1 unified system prompt, structured JSON output
  5. Bounded: MAX_ITERATIONS, MAX_TOOL_CALLS, MAX_LLM_CALLS
  6. Resumable: pending state with TTL (DB-backed)
  7. Fail-safe: parse-retry on malformed LLM output

Infrastructure unchanged: MCP pipeline, connectors, spec_loader, skills, middleware.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import time
from typing import Any, Dict, List, Optional, Tuple

from app.config import settings
from app.llm.base import BaseLLM, LLMResponse
from app.mcp import MCPClient
from app.services.context_service import ContextService
from app.services._token_tracker import record_token_usage
from app.core.normalizer import LLMResponseNormalizer, NormalizedToolCall
from app.core.request_lifecycle import RequestStore, RequestLifecycle, RequestState
from app.core.middleware import (
    ExecutionPipeline, ExecutionContext, ExecutionResult,
    ErrorBoundaryMiddleware, RateLimitMiddleware,
    RetryMiddleware, AuditMiddleware, MemoryMiddleware,
)
from app.core.safety import AuditLogger, GuildLock, ConversationMemory, InputGuardrail, TokenBudget
from app.core.spec_loader import SpecRegistry
from app.core.skill_loader import SkillLoader

logger = logging.getLogger(__name__)

# ═══════════════════════════════════════════════════════════════════════════════
# Constants
# ═══════════════════════════════════════════════════════════════════════════════

MAX_ITERATIONS = 5
MAX_TOOL_CALLS = 20
MAX_LLM_CALLS = 8
PARSE_RETRY_BUDGET = 2
PENDING_STATE_TTL = 900  # seconds (15 min)

CONFIRMATION_WORDS = {"yes", "y", "ok", "confirm", "có", "đồng ý", "xác nhận", "1", "ừ", "được", "oke"}
SHORT_CONFIRMS = {"ok", "yes", "y", "đồng ý", "có", "confirm", "được", "oke", "ừ", "1", "đi", "ok đi"}

# ═══════════════════════════════════════════════════════════════════════════════
# System Prompt (unified — handles both UNDERSTAND and EVALUATE phases)
# ═══════════════════════════════════════════════════════════════════════════════

SYSTEM_PROMPT = """You are AuraFactory, an AI assistant that manages Discord servers.
You are an enthusiastic, proactive server architect who helps admins build and optimize their Discord servers.

## CRITICAL OUTPUT FORMAT
Every response MUST be valid JSON (no markdown fences, no extra text). Choose ONE format:

### When understanding a new request (UNDERSTAND phase):
A) Direct answer (no tools needed):
   {"action": "respond", "message": "your response here"}

B) Need to execute tools:
   {"action": "execute", "plan_summary": "what you will do", "tool_calls": [{"name": "tool_name", "arguments": {...}}]}

C) Need clarification from user:
   {"action": "clarify", "question": "your question here"}

### When evaluating results (EVALUATE phase):
A) Goal achieved:
   {"action": "done", "response": "friendly summary of what was done"}

B) More steps needed:
   {"action": "continue", "tool_calls": [{"name": "tool_name", "arguments": {...}}], "reason": "why more steps"}

C) Need info from user:
   {"action": "ask_user", "question": "your question"}

D) Cannot proceed:
   {"action": "failed", "response": "explanation of what failed and why"}

## RULES
1. ALL IDs (channel_id, role_id, member_id, category_id, guild_id) MUST be strings — Discord snowflakes lose precision as numbers.
2. Use IDs from the server context. Never guess or fabricate IDs.
3. If user says "ok"/"yes"/"đồng ý" and you have a plan in context, EXECUTE it. Do NOT ask what they want.
4. If a tool returns "not found" error — the ID is likely stale. In EVALUATE, use "continue" to re-fetch and retry.
5. Execute dependencies in order: create parent (category) before child (channel inside it).
6. After creating something, reference its returned ID in subsequent steps using $stepN.field syntax:
   Example: step 0 creates category → step 1 uses category_id: "$step0.id"
7. For complex requests ("setup server"), create ALL resources in one plan: categories first, then channels, then roles.
8. Respond in the SAME language as the user (Vietnamese or English).
9. For HIGH-RISK operations (delete, ban, bulk ops), include them in your plan — the system will auto-pause for confirmation.
10. Be concise in responses. Use emojis sparingly (1-2 max).
11. If server context shows existing structure and user wants to "set up" or "restructure", include DELETE operations for old items before creating new ones.
12. When retrying the exact same tool with same params that already failed → choose "failed", do NOT "continue" infinitely.

## CAPABILITIES
19 modules: channels, categories, roles, members, guild settings, webhooks, threads, invites, automod, backup, features, audit, safety, templates, events, emojis, stickers, soundboard, onboarding, permissions.

## SERVER TEMPLATES (for "setup server" requests)
- Gaming: THÔNG BÁO (rules, announcements) | CHAT (general, memes) | GAMING (game-specific) | VOICE (gaming, chill)
- Education: THÔNG BÁO | TÀI LIỆU (resources, papers) | THẢO LUẬN (general, Q&A) | PHÒNG HỌC (voice rooms)
- Business: ANNOUNCEMENTS | DEPARTMENTS | PROJECTS | MEETINGS (voice)
- Community: WELCOME | GENERAL | TOPICS | EVENTS | VOICE
"""


# ═══════════════════════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════════════════════

def build_server_context_block(server_context: dict) -> str:
    """Build compact server context string for LLM prompt."""
    if not server_context:
        return "Server data not available."
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
        members = server_info.get("member_count", "?")
        features = server_info.get("features", [])
        parts.append(f"Server: {name} ({members} members, features: {features})")
    if categories:
        lines = [f"  {c.get('id','?')}: {c.get('name','?')}" for c in categories[:20]]
        parts.append("Categories:\n" + "\n".join(lines))
    if channels:
        lines = [f"  {ch.get('id','?')}: #{ch.get('name','?')} ({ch.get('type','text')}) [cat:{ch.get('category_id','none')}]" for ch in channels[:40]]
        parts.append("Channels:\n" + "\n".join(lines))
    if roles:
        lines = [f"  {r.get('id','?')}: @{r.get('name','?')} (pos:{r.get('position',0)})" for r in roles[:20] if r.get("name") != "@everyone"]
        parts.append("Roles:\n" + "\n".join(lines))
    return "\n\n".join(parts) if parts else "Server is empty."


def resolve_effective_goal(message: str, history: Optional[List[Dict]], pending_state: Optional[Dict]) -> str:
    """Resolve the real user goal from context."""
    # Priority 1: pending state has the original goal
    if pending_state and pending_state.get("goal"):
        return pending_state["goal"]
    # Priority 2: if message is substantive, use it
    if message.strip().lower() not in SHORT_CONFIRMS and len(message.strip()) > 15:
        return message
    # Priority 3: find last substantive user message from history
    if history:
        for turn in reversed(history):
            if turn.get("role") == "user":
                content = turn.get("content", "").strip()
                if content.lower() not in SHORT_CONFIRMS and len(content) > 15:
                    return content
    return message


def resolve_dependencies(params: Dict[str, Any], previous_results: List[Dict]) -> Tuple[Dict[str, Any], bool]:
    """Resolve $stepN.field references in params using previous results.

    Returns: (resolved_params, all_resolved: bool)
    If any reference cannot be resolved, returns (partial_params, False).
    """
    resolved = {}
    all_ok = True
    for key, value in params.items():
        if isinstance(value, str) and value.startswith("$step"):
            # Pattern: $step0.id, $step1.name, $step2.result.channel_id
            match = re.match(r'\$step(\d+)\.(.+)', value)
            if match:
                step_idx = int(match.group(1))
                field_path = match.group(2)
                if step_idx < len(previous_results):
                    result = previous_results[step_idx]
                    if result.get("success") and result.get("result"):
                        # Navigate field path
                        data = result["result"]
                        for part in field_path.split("."):
                            if isinstance(data, dict):
                                data = data.get(part)
                            else:
                                data = None
                                break
                        if data is not None:
                            resolved[key] = str(data)
                            continue
                # Could not resolve
                all_ok = False
                resolved[key] = value  # Keep placeholder for debugging
            else:
                resolved[key] = value
        else:
            resolved[key] = value
    return resolved, all_ok


def parse_llm_json(raw_text: str) -> Tuple[Optional[Dict], Optional[str]]:
    """Extract and parse JSON from LLM output. Handles markdown fences.

    Returns: (parsed_dict, error_message)
    """
    if not raw_text or not raw_text.strip():
        return None, "Empty LLM response"
    text = raw_text.strip()
    # Strip markdown code fences
    if text.startswith("```"):
        text = re.sub(r'^```(?:json)?\s*\n?', '', text)
        text = re.sub(r'\n?```\s*$', '', text)
    # Try direct parse
    try:
        return json.loads(text), None
    except json.JSONDecodeError:
        pass
    # Try extracting first JSON object
    match = re.search(r'\{[\s\S]*\}', text)
    if match:
        try:
            return json.loads(match.group(0)), None
        except json.JSONDecodeError as e:
            return None, f"JSON parse error: {e}"
    return None, f"No JSON found in: {text[:200]}"


# ═══════════════════════════════════════════════════════════════════════════════
# UnifiedAgent v6
# ═══════════════════════════════════════════════════════════════════════════════

class UnifiedAgent:
    """Agentic AI with closed-loop state machine (v6 architecture)."""

    def __init__(
        self,
        llm: BaseLLM,
        mcp_client: MCPClient,
        context_service: ContextService,
        db=None,
        registry: Optional[SpecRegistry] = None,
    ) -> None:
        self._llm = llm
        self._mcp = mcp_client
        self._context = context_service
        self._db = db
        self._registry = registry

        # Tool definitions
        if registry:
            self._tool_definitions = registry.get_llm_definitions()
            self._tool_name_map = registry.get_tool_name_map()
            self._high_risk_tools = registry.get_high_risk_tools()
        else:
            from app.core.tool_definitions import TOOL_DEFINITIONS, TOOL_NAME_MAP, HIGH_RISK_TOOLS
            self._tool_definitions = TOOL_DEFINITIONS
            self._tool_name_map = TOOL_NAME_MAP
            self._high_risk_tools = HIGH_RISK_TOOLS

        # Normalizer (for function-calling mode fallback)
        self._normalizer = LLMResponseNormalizer(tool_name_map=self._tool_name_map)

        # Request state (in-memory, with TTL)
        self._requests = RequestStore(default_ttl=PENDING_STATE_TTL)

        # Skills
        self._skills = SkillLoader()

        # Memory
        self._memory = ConversationMemory()

        # Middleware pipeline
        self._audit = AuditLogger(db=db)

        from app.core.middleware import (
            ExecutionPipeline, ExecutionContext, ExecutionResult,
            ErrorBoundaryMiddleware, RateLimitMiddleware,
            RetryMiddleware, AuditMiddleware, MemoryMiddleware,
            CircuitBreakerMiddleware, MetricsMiddleware,
        )

        self._pipeline = ExecutionPipeline(
            middlewares=[
                ErrorBoundaryMiddleware(),
                MetricsMiddleware(),
                CircuitBreakerMiddleware(failure_threshold=5, cooldown_seconds=30.0),
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

        # Input guardrail
        self._input_guard = InputGuardrail()

        # Token budget
        self._token_budget = TokenBudget(
            db=db,
            daily_limit=getattr(settings, 'DAILY_TOKEN_BUDGET', 800000),
            per_request_limit=getattr(settings, 'PER_REQUEST_TOKEN_LIMIT', 10000),
        )

        logger.info("UnifiedAgent v6 initialized: %d tools, %d skills", len(self._tool_definitions), self._skills.skill_count)

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
        """Process user message through the v6 state machine."""

        # Gate: guild lock
        if not self._guild_lock.is_allowed(guild_id):
            return self._respond("error", "This server is not authorized.")

        # Gate 2: Input length
        max_len = getattr(settings, 'MAX_MESSAGE_LENGTH', 2000)
        if len(message) > max_len:
            return self._respond("error", f"Message too long ({len(message)} chars, max {max_len}).")

        # Gate 3: Prompt injection detection
        is_safe, reason = self._input_guard.check(message)
        if not is_safe:
            logger.warning("Input blocked (guild=%d, user=%d): %s", guild_id, user_id, reason)
            return self._respond("error", "Your message was blocked by the safety filter.")

        # Gate 4: Token budget
        has_budget, remaining = await self._token_budget.check_budget(guild_id)
        if not has_budget:
            return self._respond("error", "Daily token budget exhausted for this server. Try again tomorrow.")

        # Check pending state (AWAITING_CLARIFY or AWAITING_APPROVAL)
        pending = self._requests.get_awaiting_approval(guild_id, user_id)
        if pending:
            return await self._handle_resume(message, pending, guild_id, user_id, history)

        # Resolve effective goal
        effective_goal = resolve_effective_goal(message, history, None)

        # ═══════ UNDERSTAND ═══════
        return await self._understand(effective_goal, guild_id, user_id, history)

    # ─────────────────────────────────────────────────────────────────────────
    # UNDERSTAND — LLM decides: respond / execute / clarify
    # ─────────────────────────────────────────────────────────────────────────

    async def _understand(
        self,
        goal: str,
        guild_id: int,
        user_id: int,
        history: Optional[List[Dict[str, str]]],
        llm_call_count: int = 0,
    ) -> Dict[str, Any]:
        """UNDERSTAND phase: LLM analyzes goal and decides action."""

        if llm_call_count >= MAX_LLM_CALLS:
            return self._respond("error", "⚠️ Too many processing steps. Please try a simpler request.")

        # Gather context
        server_context = await self._context.get_server_context(guild_id)
        context_block = build_server_context_block(server_context)
        skills_block = self._skills.get_relevant_skills()
        memory_block = self._memory.build_context_block(guild_id)

        # Build messages
        messages = []
        messages.append({"role": "user", "content": f"[SERVER STATE]\n{context_block}"})
        if skills_block:
            messages.append({"role": "user", "content": f"[TOOL KNOWLEDGE]\n{skills_block}"})
        if memory_block:
            messages.append({"role": "user", "content": f"[RECENT ACTIONS]\n{memory_block}"})
        messages.append({"role": "assistant", "content": "Ready. Send your request and I will respond with a JSON action."})
        # Add history
        if history:
            for turn in history[-6:]:
                role = turn.get("role", "user")
                content = turn.get("content", "")
                if role in ("user", "assistant") and content:
                    messages.append({"role": role, "content": content})
        messages.append({"role": "user", "content": goal})

        # LLM call
        try:
            response = await self._llm.generate(
                messages=messages,
                system_prompt=SYSTEM_PROMPT,
                tools=self._tool_definitions,
                temperature=0.2,
                max_tokens=2048,
            )
        except Exception as e:
            logger.error("UNDERSTAND LLM failed: %s", e, exc_info=True)
            return self._respond("error", "⚠️ AI processing error. Please try again.")

        # Track tokens
        if hasattr(response, 'usage') and response.usage:
            await record_token_usage(self._db, guild_id, user_id, response.usage, provider=settings.LLM_PROVIDER, phase="understand")

        llm_call_count += 1

        # ── Parse output ──
        # Try structured JSON first (from content)
        if response.content:
            parsed, err = parse_llm_json(response.content)
            if parsed and "action" in parsed:
                return await self._dispatch_action(parsed, goal, guild_id, user_id, history, llm_call_count)
            # Parse retry
            if err and llm_call_count < MAX_LLM_CALLS:
                logger.warning("UNDERSTAND parse fail (retry %d): %s", llm_call_count, err)
                correction = f"Your previous output was not valid JSON. Error: {err}. Please output ONLY valid JSON with an 'action' field."
                messages.append({"role": "assistant", "content": response.content})
                messages.append({"role": "user", "content": correction})
                try:
                    retry_resp = await self._llm.generate(messages=messages, system_prompt=SYSTEM_PROMPT, tools=self._tool_definitions, temperature=0.1, max_tokens=2048)
                    llm_call_count += 1
                    if retry_resp.content:
                        parsed2, _ = parse_llm_json(retry_resp.content)
                        if parsed2 and "action" in parsed2:
                            return await self._dispatch_action(parsed2, goal, guild_id, user_id, history, llm_call_count)
                except Exception:
                    pass

        # Fallback: check if LLM used function calling (tool_calls)
        if response.has_tool_calls:
            normalized = self._normalizer.normalize(response)
            if normalized.usable and normalized.has_tool_calls:
                tool_calls_data = [{"name": tc.name, "arguments": tc.arguments} for tc in normalized.tool_calls]
                action_data = {"action": "execute", "plan_summary": "Executing requested tools", "tool_calls": tool_calls_data}
                return await self._dispatch_action(action_data, goal, guild_id, user_id, history, llm_call_count)
            elif normalized.usable and normalized.is_text_only:
                return self._respond("answer", normalized.text)

        # Final fallback: if content looks like a direct answer
        if response.content and len(response.content.strip()) > 10:
            return self._respond("answer", response.content.strip())

        return self._respond("error", "⚠️ Could not process your request. Please try again.")

    # ─────────────────────────────────────────────────────────────────────────
    # ACTION DISPATCHER
    # ─────────────────────────────────────────────────────────────────────────

    async def _dispatch_action(
        self,
        data: Dict[str, Any],
        goal: str,
        guild_id: int,
        user_id: int,
        history: Optional[List[Dict[str, str]]],
        llm_call_count: int,
    ) -> Dict[str, Any]:
        """Route parsed LLM action to appropriate handler."""
        action = data.get("action", "")

        if action == "respond":
            return self._respond("answer", data.get("message", ""))

        elif action == "clarify":
            # AWAITING_CLARIFY — persist state, return question
            req = self._requests.create(guild_id, user_id, goal)
            req.transition(RequestState.AWAITING_APPROVAL)  # reuse state
            req.set_payload("pending_type", "AWAITING_CLARIFY")
            req.set_payload("goal", goal)
            return self._respond("clarify", data.get("question", "Could you provide more details?"))

        elif action == "execute":
            tool_calls = data.get("tool_calls", [])
            if not tool_calls:
                return self._respond("answer", data.get("plan_summary", "Nothing to execute."))
            return await self._execute_loop(tool_calls, goal, guild_id, user_id, history, llm_call_count)

        elif action == "done":
            return self._respond("action", data.get("response", "✅ Done."))

        elif action == "continue":
            tool_calls = data.get("tool_calls", [])
            if not tool_calls:
                return self._respond("answer", data.get("reason", "No further actions needed."))
            return await self._execute_loop(tool_calls, goal, guild_id, user_id, history, llm_call_count)

        elif action == "ask_user":
            req = self._requests.create(guild_id, user_id, goal)
            req.transition(RequestState.AWAITING_APPROVAL)
            req.set_payload("pending_type", "AWAITING_CLARIFY")
            req.set_payload("goal", goal)
            return self._respond("clarify", data.get("question", ""))

        elif action == "failed":
            return self._respond("error", data.get("response", "❌ Could not complete the request."))

        else:
            logger.warning("Unknown action '%s' from LLM", action)
            return self._respond("error", "⚠️ Unexpected response from AI. Please try again.")

    # ─────────────────────────────────────────────────────────────────────────
    # EXECUTE LOOP — sequential execution with dependency resolution
    # ─────────────────────────────────────────────────────────────────────────

    async def _execute_loop(
        self,
        tool_calls: List[Dict[str, Any]],
        goal: str,
        guild_id: int,
        user_id: int,
        history: Optional[List[Dict[str, str]]],
        llm_call_count: int,
        results_so_far: Optional[List[Dict]] = None,
        iteration: int = 1,
    ) -> Dict[str, Any]:
        """Execute tools sequentially with forward dependency injection."""
        results = results_so_far or []
        total_tools_called = sum(1 for r in results if r.get("status") != "skipped_dependency_failed")

        for i, tc in enumerate(tool_calls):
            # Budget check
            if total_tools_called >= MAX_TOOL_CALLS:
                logger.warning("MAX_TOOL_CALLS reached (%d)", MAX_TOOL_CALLS)
                break

            tool_name = tc.get("name", "")
            raw_args = tc.get("arguments", {})

            # Strip known LLM prefixes (Gemini adds "default_api.")
            if tool_name.startswith("default_api."):
                tool_name = tool_name[len("default_api."):]

            # Map short name to MCP name
            mcp_name = self._tool_name_map.get(tool_name, tool_name)

            # ── Resolve dependencies ──
            params, resolved = resolve_dependencies(raw_args, results)
            if not resolved:
                results.append({
                    "tool": mcp_name, "mcp_name": mcp_name, "success": False,
                    "status": "skipped_dependency_failed",
                    "error": f"Could not resolve dependency reference in params",
                    "result": None, "duration_ms": 0,
                })
                continue

            # ── Approval gate: HIGH RISK → pause ──
            if mcp_name in self._high_risk_tools:
                # Store state and pause
                req = self._requests.create(guild_id, user_id, goal)
                req.transition(RequestState.AWAITING_APPROVAL)
                req.set_payload("pending_type", "AWAITING_APPROVAL")
                req.set_payload("goal", goal)
                req.set_payload("pending_tools", tool_calls[i:])
                req.set_payload("results_so_far", results)
                req.set_payload("iteration", iteration)
                req.set_payload("llm_call_count", llm_call_count)

                # Describe what needs approval
                desc_lines = []
                for t in tool_calls[i:]:
                    t_mcp = self._tool_name_map.get(t.get("name", ""), t.get("name", ""))
                    if t_mcp in self._high_risk_tools:
                        label = self._get_action_label(t_mcp, t.get("arguments", {}))
                        desc_lines.append(f"• {label}")
                desc = "\n".join(desc_lines) if desc_lines else "• High-risk operation"

                return self._respond(
                    "confirm_needed",
                    f"🔒 **High-risk action(s) require confirmation:**\n{desc}\n\n❓ **Proceed?** (yes/no)",
                    results,
                )

            # ── Execute tool ──
            params["guild_id"] = guild_id
            ctx = ExecutionContext(
                tool_name=mcp_name, params=params,
                guild_id=guild_id, user_id=user_id,
                risk_level="high" if mcp_name in self._high_risk_tools else "medium",
                request_id="",
            )
            result = await self._pipeline.execute(ctx)
            results.append({
                "tool": mcp_name.split(".")[-1] if "." in mcp_name else mcp_name,
                "mcp_name": mcp_name,
                "success": result.success,
                "result": result.data,
                "error": result.error,
                "duration_ms": result.duration_ms,
            })
            total_tools_called += 1

        # ═══════ EVALUATE ═══════
        return await self._evaluate(goal, results, guild_id, user_id, history, llm_call_count, iteration)

    # ─────────────────────────────────────────────────────────────────────────
    # EVALUATE — LLM decides: done / continue / ask_user / failed
    # ─────────────────────────────────────────────────────────────────────────

    async def _evaluate(
        self,
        goal: str,
        results: List[Dict[str, Any]],
        guild_id: int,
        user_id: int,
        history: Optional[List[Dict[str, str]]],
        llm_call_count: int,
        iteration: int,
    ) -> Dict[str, Any]:
        """EVALUATE phase: check if goal is met, decide next steps."""

        # Budget checks
        if llm_call_count >= MAX_LLM_CALLS:
            return self._respond("action", self._format_results_summary(results))
        if iteration >= MAX_ITERATIONS:
            return self._respond("action", self._format_results_summary(results))

        # Fast path: all simple + all success → done without LLM call
        all_success = all(r.get("success", False) for r in results if r.get("status") != "skipped_dependency_failed")
        real_results = [r for r in results if r.get("status") != "skipped_dependency_failed"]
        if all_success and len(real_results) <= 3 and not any(r.get("status") == "skipped_dependency_failed" for r in results):
            # Simple success — assemble response with LLM
            response_text = await self._assemble(goal, results, guild_id, user_id, llm_call_count)
            return self._respond("action", response_text, results)

        # Complex case: ask LLM to evaluate
        # Refresh server state
        try:
            await self._context.invalidate(guild_id)
        except Exception:
            pass
        server_context = await self._context.get_server_context(guild_id)
        context_block = build_server_context_block(server_context)

        # Build results summary for LLM
        result_lines = []
        for idx, r in enumerate(results):
            if r.get("status") == "skipped_dependency_failed":
                result_lines.append(f"Step {idx}: SKIPPED (dependency not resolved)")
            elif r["success"]:
                data = r.get("result") or {}
                name = data.get("name") or data.get("id") or ""
                result_lines.append(f"Step {idx}: ✓ {r.get('tool','?')} → {name}")
            else:
                result_lines.append(f"Step {idx}: ✗ {r.get('tool','?')} → ERROR: {r.get('error','unknown')}")

        eval_input = (
            f"[GOAL]\n{goal}\n\n"
            f"[EXECUTION RESULTS]\n" + "\n".join(result_lines) + "\n\n"
            f"[CURRENT SERVER STATE]\n{context_block}\n\n"
            f"Evaluate: is the goal fully achieved? Respond with JSON (action: done/continue/ask_user/failed)."
        )

        try:
            response = await self._llm.generate(
                messages=[{"role": "user", "content": eval_input}],
                system_prompt=SYSTEM_PROMPT,
                tools=self._tool_definitions,
                temperature=0.1,
                max_tokens=1024,
            )
        except Exception as e:
            logger.error("EVALUATE LLM failed: %s", e)
            return self._respond("action", self._format_results_summary(results))

        if hasattr(response, 'usage') and response.usage:
            await record_token_usage(self._db, guild_id, user_id, response.usage, provider=settings.LLM_PROVIDER, phase="evaluate")
        llm_call_count += 1

        # Parse evaluate response
        parsed = None
        if response.content:
            parsed, err = parse_llm_json(response.content)
        # Fallback: function calling
        if not parsed and response.has_tool_calls:
            normalized = self._normalizer.normalize(response)
            if normalized.has_tool_calls:
                tool_calls_data = [{"name": tc.name, "arguments": tc.arguments} for tc in normalized.tool_calls]
                parsed = {"action": "continue", "tool_calls": tool_calls_data, "reason": "More steps from evaluate"}

        if not parsed:
            # Can't parse evaluate → return what we have
            return self._respond("action", self._format_results_summary(results))

        # Dispatch evaluate action
        action = parsed.get("action", "done")
        if action == "done":
            return self._respond("action", parsed.get("response", self._format_results_summary(results)), results)
        elif action == "continue":
            next_tools = parsed.get("tool_calls", [])
            if not next_tools:
                return self._respond("action", self._format_results_summary(results))
            return await self._execute_loop(next_tools, goal, guild_id, user_id, history, llm_call_count, results, iteration + 1)
        elif action == "ask_user":
            req = self._requests.create(guild_id, user_id, goal)
            req.transition(RequestState.AWAITING_APPROVAL)
            req.set_payload("pending_type", "AWAITING_CLARIFY")
            req.set_payload("goal", goal)
            req.set_payload("results_so_far", results)
            return self._respond("clarify", parsed.get("question", ""))
        elif action == "failed":
            return self._respond("error", parsed.get("response", "❌ Could not complete."), results)
        else:
            return self._respond("action", self._format_results_summary(results))

    # ─────────────────────────────────────────────────────────────────────────
    # ASSEMBLE — friendly response for simple success cases
    # ─────────────────────────────────────────────────────────────────────────

    async def _assemble(
        self, goal: str, results: List[Dict], guild_id: int, user_id: int, llm_call_count: int,
    ) -> str:
        """Quick assemble for simple successful cases."""
        if llm_call_count >= MAX_LLM_CALLS:
            return self._format_results_summary(results)

        result_lines = []
        for r in results:
            if r["success"]:
                data = r.get("result") or {}
                name = data.get("name") or data.get("id") or ""
                result_lines.append(f"✓ {r.get('tool','action')}: {name}")
            else:
                result_lines.append(f"✗ {r.get('tool','action')}: {r.get('error','')}")

        try:
            response = await self._llm.generate(
                messages=[{"role": "user", "content": f"User request: {goal}\nResults:\n" + "\n".join(result_lines)}],
                system_prompt="You are a response composer. Write a brief, friendly summary (2-4 sentences) in the user's language. Use 1-2 emojis. Suggest 1 next step. Do NOT output JSON.",
                tools=None,
                temperature=0.7,
                max_tokens=512,
            )
            if hasattr(response, 'usage') and response.usage:
                await record_token_usage(self._db, guild_id, user_id, response.usage, provider=settings.LLM_PROVIDER, phase="assemble")
            if response.content:
                return response.content.strip()
        except Exception as e:
            logger.warning("Assemble failed: %s", e)

        return self._format_results_summary(results)

    # ─────────────────────────────────────────────────────────────────────────
    # HANDLE RESUME — from AWAITING_CLARIFY or AWAITING_APPROVAL
    # ─────────────────────────────────────────────────────────────────────────

    async def _handle_resume(
        self,
        message: str,
        req: RequestLifecycle,
        guild_id: int,
        user_id: int,
        history: Optional[List[Dict[str, str]]],
    ) -> Dict[str, Any]:
        """Resume from a pending state based on user's reply."""
        pending_type = req.get_payload("pending_type", "AWAITING_APPROVAL")
        goal = req.get_payload("goal", message)

        # ── AWAITING_CLARIFY → back to UNDERSTAND ──
        if pending_type == "AWAITING_CLARIFY":
            req.transition(RequestState.COMPLETED)
            # User's answer becomes new context; goal stays the same
            updated_goal = f"{goal}\n\nUser's additional info: {message}"
            return await self._understand(updated_goal, guild_id, user_id, history)

        # ── AWAITING_APPROVAL → resume EXECUTE or cancel ──
        msg_lower = message.strip().lower()
        if msg_lower not in CONFIRMATION_WORDS:
            req.transition(RequestState.CANCELLED)
            return self._respond("answer", "✋ Cancelled. No changes were made.")

        # User approved → resume execute loop
        req.transition(RequestState.EXECUTING)
        pending_tools = req.get_payload("pending_tools", [])
        results_so_far = req.get_payload("results_so_far", [])
        iteration = req.get_payload("iteration", 1)
        llm_call_count = req.get_payload("llm_call_count", 1)

        if not pending_tools:
            req.transition(RequestState.COMPLETED)
            return self._respond("answer", "No pending actions to execute.")

        return await self._execute_loop(
            pending_tools, goal, guild_id, user_id, history,
            llm_call_count, results_so_far, iteration,
        )

    # ─────────────────────────────────────────────────────────────────────────
    # MCP EXECUTOR (innermost tool call)
    # ─────────────────────────────────────────────────────────────────────────

    async def _mcp_execute(self, ctx: ExecutionContext) -> ExecutionResult:
        """Actual MCP tool call through the middleware chain."""
        resp = await self._mcp.call_tool(ctx.tool_name, ctx.params)
        if resp.success:
            return ExecutionResult(success=True, data=resp.result)
        else:
            error = resp.error or "Unknown error"
            should_retry = any(s in error.lower() for s in ("429", "rate", "timeout", "503"))
            return ExecutionResult(success=False, error=error, should_retry=should_retry)

    # ─────────────────────────────────────────────────────────────────────────
    # HELPERS
    # ─────────────────────────────────────────────────────────────────────────

    def _get_action_label(self, mcp_name: str, params: Dict[str, Any]) -> str:
        """Human-readable label for approval prompt."""
        if self._registry:
            label = self._registry.get_human_label(mcp_name)
        else:
            label = f"⚠️ {mcp_name}"
        target = params.get("name") or params.get("channel_id") or params.get("role_id") or params.get("member_id") or ""
        if target:
            label += f" `{target}`"
        return label

    @staticmethod
    def _format_results_summary(results: List[Dict]) -> str:
        """Mechanical fallback summary."""
        if not results:
            return "No actions were performed."
        lines = []
        for r in results:
            if r.get("status") == "skipped_dependency_failed":
                lines.append(f"⏭️ {r.get('tool', '?')}: skipped (dependency failed)")
            elif r.get("success"):
                data = r.get("result") or {}
                name = data.get("name") or ""
                lines.append(f"✅ {r.get('tool', 'action')}: {name}" if name else f"✅ {r.get('tool', 'action')}")
            else:
                lines.append(f"❌ {r.get('tool', 'action')}: {r.get('error', 'failed')}")
        return "\n".join(lines)

    @staticmethod
    def _respond(type_: str, content: str, tool_results: Optional[List] = None) -> Dict[str, Any]:
        """Standardized response dict."""
        return {"type": type_, "content": content, "tool_results": tool_results or []}

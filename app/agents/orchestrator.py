# app/agents/orchestrator.py
"""
Orchestrator — Thin Router.

Classify → Permission Gate → Route to correct track:
- Fast Track: simple commands (1 LLM call → execute)
- ReAct Track: complex commands (multi-step reasoning)
- Assistant: Q&A, conversation (1 LLM call, no tools)
"""
import time
import logging
from typing import Dict, Any, Optional

from app.agents.classifier import IntentClassifier, ClassifyResult
from app.agents.admin_agent import AdminAgent
from app.agents.assistant_agent import AssistantAgent
from app.agents.fast_track import FastTrackExecutor
from app.infra.llm.base import LLMProvider
from app.infra.observability.tracer import Tracer
from app.infra.observability.metrics import metrics
from app.knowledge.store import ServerKnowledgeStore
from app.gateway.pipeline import GatewayContext

logger = logging.getLogger(__name__)

PERMISSION_DENIED = "⛔ Bạn không có quyền thực hiện thao tác này. Chỉ admin mới có thể quản lý server."


class OrchestratorAgent:
    """
    Thin Router — classify + route. No business logic.

    Routes:
    - simple command + admin → FastTrackExecutor (1 LLM call)
    - complex command + admin → AdminAgent ReAct (max 3 loops)
    - command + non-admin → reject
    - server_query / conversation → AssistantAgent (1 LLM call)
    - setup not complete + admin → AdminAgent setup mode
    """

    def __init__(
        self,
        llm: LLMProvider,
        tracer: Tracer,
        knowledge_store: ServerKnowledgeStore,
        memory=None,
    ):
        self._tracer = tracer
        self._knowledge = knowledge_store
        self._memory = memory
        self._classifier = IntentClassifier(llm)

        # Sub-agents (injected after construction)
        self._admin_agent: Optional[AdminAgent] = None
        self._assistant_agent: Optional[AssistantAgent] = None
        self._fast_track: Optional[FastTrackExecutor] = None

    def set_admin_agent(self, agent: AdminAgent) -> None:
        self._admin_agent = agent

    def set_assistant_agent(self, agent: AssistantAgent) -> None:
        self._assistant_agent = agent

    def set_fast_track(self, executor: FastTrackExecutor) -> None:
        self._fast_track = executor

    # ============================================================
    # MAIN ENTRY POINT
    # ============================================================

    async def handle(
        self,
        prompt: str,
        user_id: str,
        guild_id: int = None,
        trace_id: str = "",
        session_id: str = "",
        context: GatewayContext = None,
    ) -> Dict[str, Any]:
        """Main entry — called by message handler after Gateway."""
        start_time = time.time()

        if context is None:
            context = GatewayContext(session_id=session_id, trace_id=trace_id)

        # Store user message in memory
        if self._memory:
            await self._memory.add_message(
                session_id=context.session_id,
                user_id=user_id,
                role="user",
                content=prompt,
                guild_id=guild_id,
            )

        # ─── Route ───
        result = await self._route(prompt, guild_id, context)

        # Store agent response in memory
        if self._memory and result.get("content"):
            try:
                await self._memory.add_message(
                    session_id=context.session_id,
                    user_id="assistant",
                    role="assistant",
                    content=result["content"][:500],
                )
            except Exception:
                pass

        # Track total time
        total_ms = (time.time() - start_time) * 1000
        metrics.observe("request_total_ms", total_ms)
        logger.info(
            f"[{context.trace_id}] Orchestrator completed in {total_ms:.0f}ms "
            f"→ mode={result.get('mode')}"
        )

        return result

    async def _route(
        self, prompt: str, guild_id: int, context: GatewayContext
    ) -> Dict[str, Any]:
        """Core routing logic."""

        # ─── Step 1: Bot State Check ───
        setup_complete = True
        if guild_id:
            setup_complete = await self._knowledge.is_setup_complete(guild_id)

        if not setup_complete:
            if context.user_role == "admin":
                return await self._admin_agent.handle_setup(
                    prompt=prompt, guild_id=guild_id, context=context
                )
            else:
                return await self._assistant_agent.handle(
                    prompt=prompt, guild_id=guild_id, context=context
                )

        # ─── Step 2: Classify (1 LLM call → intent + complexity) ───
        classify_result = await self._classifier.classify(prompt)
        self._tracer.log_reasoning(
            context.trace_id, "orchestrator",
            f"Intent: {classify_result.intent}, Complexity: {classify_result.complexity}"
        )
        metrics.increment("intent_classified", labels={
            "intent": classify_result.intent,
            "complexity": classify_result.complexity,
        })

        # ─── Step 3: Permission Gate + Route ───

        if classify_result.intent == "command":
            # Permission check
            if context.user_role != "admin":
                return {
                    "status": "response",
                    "content": PERMISSION_DENIED,
                    "trace_id": context.trace_id,
                    "mode": "rejected",
                }

            # Route by complexity
            if classify_result.is_fast_track and self._fast_track:
                # Fast Track: 1 LLM call → extract → execute
                server_context = await self._knowledge.get_summary_string(guild_id)
                return await self._fast_track.handle(
                    prompt=prompt,
                    guild_id=guild_id,
                    server_context=server_context,
                    context=context,
                )
            else:
                # ReAct Track: multi-step reasoning
                return await self._admin_agent.handle_admin(
                    prompt=prompt, guild_id=guild_id, context=context
                )

        else:
            # conversation / server_query → Assistant (1 LLM call, no tools)
            return await self._assistant_agent.handle(
                prompt=prompt, guild_id=guild_id, context=context
            )

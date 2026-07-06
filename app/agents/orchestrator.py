# app/agents/orchestrator.py
"""
Orchestrator — Thin Router.

Sole responsibility: Classify → Permission Gate → Route to correct agent.
No business logic. No prompts. No loops.

Routing:
1. Bot state check: setup complete? → if no + admin → AdminAgent.setup
2. Classify intent (conversation/server_query/command)
3. Permission gate: command + not admin → reject
4. Route: command → AdminAgent.admin | else → AssistantAgent
"""
import time
import logging
from typing import Dict, Any, Optional

from app.agents.classifier import IntentClassifier
from app.agents.admin_agent import AdminAgent
from app.agents.assistant_agent import AssistantAgent
from app.infra.llm.base import LLMProvider
from app.infra.observability.tracer import Tracer
from app.infra.observability.metrics import metrics
from app.knowledge.store import ServerKnowledgeStore
from app.gateway.pipeline import GatewayContext

logger = logging.getLogger(__name__)

PERMISSION_DENIED_VI = "⛔ Bạn không có quyền thực hiện thao tác này. Chỉ admin mới có thể quản lý server."
PERMISSION_DENIED_EN = "⛔ You don't have permission. Only admins can manage the server."


class OrchestratorAgent:
    """
    Thin Router — ~50 lines of routing logic.

    Does NOT:
    - Hold prompts
    - Run loops
    - Call LLM directly (except via classifier)
    - Have business logic

    Does:
    - Check bot state (setup complete?)
    - Classify intent
    - Check permissions
    - Route to AdminAgent or AssistantAgent
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

    def set_admin_agent(self, agent: AdminAgent) -> None:
        self._admin_agent = agent

    def set_assistant_agent(self, agent: AssistantAgent) -> None:
        self._assistant_agent = agent

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
        """
        Main entry — called by message handler after Gateway.
        Pure routing. No LLM calls except classifier.
        """
        start_time = time.time()

        # Default context (backward compat)
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

        # Recall memory context before routing
        memory_context = None
        if self._memory and guild_id:
            try:
                memory_context = await self._memory.recall(
                    query=prompt,
                    guild_id=guild_id,
                    session_id=context.session_id,
                    top_k=3,
                )
            except Exception as e:
                logger.debug(f"[{context.trace_id}] Memory recall failed (non-critical): {e}")

        # Attach memory context to gateway context for sub-agents
        if memory_context:
            context.memory_context = memory_context

        # ─── Route ───
        result = await self._route(prompt, guild_id, context)

        # Store agent response in memory for continuity
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
        logger.info(f"[{context.trace_id}] Orchestrator completed in {total_ms:.0f}ms → mode={result.get('mode')}")

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
                # First time + admin → Setup Wizard
                return await self._admin_agent.handle_setup(
                    prompt=prompt, guild_id=guild_id, context=context
                )
            else:
                # First time + non-admin → Basic assistant (limited knowledge)
                return await self._assistant_agent.handle(
                    prompt=prompt, guild_id=guild_id, context=context
                )

        # ─── Step 2: Classify Intent ───
        intent = await self._classifier.classify(prompt)
        self._tracer.log_reasoning(context.trace_id, "orchestrator", f"Intent: {intent}")
        metrics.increment("intent_classified", labels={"intent": intent})

        # ─── Step 3: Permission Gate + Route ───
        if intent == "command":
            if context.user_role == "admin":
                return await self._admin_agent.handle_admin(
                    prompt=prompt, guild_id=guild_id, context=context
                )
            else:
                # Permission denied
                return {
                    "status": "response",
                    "content": PERMISSION_DENIED_VI,
                    "trace_id": context.trace_id,
                    "mode": "rejected",
                }
        else:
            # conversation or server_query → Assistant
            return await self._assistant_agent.handle(
                prompt=prompt, guild_id=guild_id, context=context
            )

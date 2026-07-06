# app/agents/orchestrator.py
"""
OrchestratorAgent — Pure Thin Router (ENTRY POINT after gateway).

Flow: classify intent → permission check → route to correct agent → return result.

Routes:
- FAST_TRACK → FastTrackExecutor
- ADMIN_COMPLEX → AdminAgent
- ASSISTANT → AssistantAgent

Does NOT do any reasoning itself — pure routing logic only.
Permission denied at gateway → never reaches agents.
"""
import logging
from typing import Any, Dict, Optional
from app.agents.base import BaseAgent
from app.agents.contracts import (
    AgentRole,
    IntentType,
    TaskAssignment,
    TaskResult,
)
from app.agents.classifier import IntentClassifier
from app.infra.llm.base import LLMProvider
logger = logging.getLogger(__name__)

# Permission error messages
PERMISSION_DENIED_MSG: str = (
    "⛔ Bạn không có quyền thực hiện thao tác này. "
    "Chỉ admin/moderator mới có thể quản lý server."
)


class OrchestratorAgent(BaseAgent):
    """
    Thin Router — classify intent + permission gate + route.

    This is the ENTRY POINT called immediately after the Gateway pipeline.
    It does NO reasoning, NO tool calling, NO LLM generation.
    Pure routing based on classification result + user role.

    Routes:
    - FAST_TRACK (admin/mod only) → FastTrackExecutor
    - ADMIN_COMPLEX (admin/mod only) → AdminAgent
    - ASSISTANT (anyone) → AssistantAgent
    - Permission mismatch → deny immediately
    """

    def __init__(
        self,
        llm: LLMProvider,
        mcp_client: Any = None,
        memory: Any = None,
        knowledge_store: Any = None,
        settings: Optional[Dict[str, Any]] = None,
        skill_registry: Any = None,
    ) -> None:
        super().__init__(
            llm=llm,
            mcp_client=mcp_client,
            memory=memory,
            knowledge_store=knowledge_store,
            settings=settings,
            skill_registry=skill_registry,
        )
        self._classifier = IntentClassifier(llm)

        # Sub-agents (injected after construction)
        self._fast_track: Optional[Any] = None  # FastTrackExecutor
        self._admin_agent: Optional[Any] = None  # AdminAgent
        self._assistant_agent: Optional[Any] = None  # AssistantAgent

    # ============================================================
    # AGENT INJECTION
    # ============================================================

    def set_fast_track(self, agent: Any) -> None:
        """Inject FastTrackExecutor sub-agent."""
        self._fast_track = agent

    def set_admin_agent(self, agent: Any) -> None:
        """Inject AdminAgent sub-agent."""
        self._admin_agent = agent

    def set_assistant_agent(self, agent: Any) -> None:
        """Inject AssistantAgent sub-agent."""
        self._assistant_agent = agent

    # ============================================================
    # MAIN ENTRY POINT
    # ============================================================

    async def execute(self, task: TaskAssignment) -> TaskResult:
        """
        Main entry point — called after Gateway passes the message.

        Flow:
        1. Classify intent (LLM + heuristic fallback)
        2. Permission check (admin-only routes need admin/moderator/owner)
        3. Route to correct sub-agent
        4. Return result from sub-agent

        Args:
            task: TaskAssignment containing message, user_role, context.

        Returns:
            TaskResult from the routed sub-agent.
        """
        trace_id = task.trace_id
        user_role = task.user_role
        prompt = task.prompt

        logger.info(
            f"[{trace_id}] Orchestrator received: "
            f"role={user_role}, prompt='{prompt[:50]}...'"
        )

        # ─── Step 1: Classify Intent ───
        intent = await self._classifier.classify(prompt, user_role)
        logger.info(f"[{trace_id}] Classified intent: {intent.value}")

        # ─── Step 2: Permission Check ───
        if intent in (IntentType.FAST_TRACK, IntentType.ADMIN_COMPLEX):
            if user_role not in ("owner", "admin", "moderator"):
                logger.warning(
                    f"[{trace_id}] Permission denied: "
                    f"user_role={user_role}, intent={intent.value}"
                )
                return TaskResult(
                    trace_id=trace_id,
                    content=PERMISSION_DENIED_MSG,
                    status="denied",
                )

        # ─── Step 3: Route to Correct Agent ───
        # Update task with classified intent
        task.intent = intent

        if intent == IntentType.FAST_TRACK:
            return await self._route_fast_track(task)
        elif intent == IntentType.ADMIN_COMPLEX:
            return await self._route_admin(task)
        else:
            return await self._route_assistant(task)

    # ============================================================
    # ROUTING METHODS
    # ============================================================

    async def _route_fast_track(self, task: TaskAssignment) -> TaskResult:
        """Route to FastTrackExecutor for single-action commands."""
        if not self._fast_track:
            logger.error(f"[{task.trace_id}] FastTrackExecutor not configured")
            return self._error_result(task.trace_id, "System error: FastTrack agent unavailable.")

        logger.info(f"[{task.trace_id}] Routing → FastTrackExecutor")
        task.agent_role = AgentRole.FAST_TRACK
        return await self._fast_track.execute(task)

    async def _route_admin(self, task: TaskAssignment) -> TaskResult:
        """Route to AdminAgent for complex multi-step operations."""
        if not self._admin_agent:
            logger.error(f"[{task.trace_id}] AdminAgent not configured")
            return self._error_result(task.trace_id, "System error: Admin agent unavailable.")

        logger.info(f"[{task.trace_id}] Routing → AdminAgent")
        task.agent_role = AgentRole.ADMIN
        return await self._admin_agent.execute(task)

    async def _route_assistant(self, task: TaskAssignment) -> TaskResult:
        """Route to AssistantAgent for Q&A and conversation."""
        if not self._assistant_agent:
            logger.error(f"[{task.trace_id}] AssistantAgent not configured")
            return self._error_result(task.trace_id, "System error: Assistant agent unavailable.")

        logger.info(f"[{task.trace_id}] Routing → AssistantAgent")
        task.agent_role = AgentRole.ASSISTANT
        return await self._assistant_agent.execute(task)

    # ============================================================
    # BASE AGENT INTERFACE
    # ============================================================

    def get_agent_role(self) -> AgentRole:
        return AgentRole.ORCHESTRATOR

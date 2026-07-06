# app/agents/base.py
"""
BaseAgent — Abstract Base Class for all specialist agents.
Provides: LLM calling with retry, cost tracking, prompt loading, tool access.
All agents (Orchestrator, Admin, FastTrack, Architect, Assistant) inherit from this.
"""
import asyncio
import logging
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, Dict, List, Optional
from app.agents.contracts import AgentRole, TaskAssignment, TaskResult
from app.infra.llm.base import LLMProvider, LLMResponse
logger = logging.getLogger(__name__)
# Retry configuration
MAX_RETRIES: int = 1
RETRY_BACKOFF_SECONDS: float = 2.0
# Error message when LLM fails after retries
LLM_OVERLOAD_MESSAGE: str = "Hệ thống đang quá tải, thử lại sau"
# Prompts directory
PROMPTS_DIR: Path = Path(__file__).parent.parent.parent / "prompts"


class BaseAgent(ABC):
    """
    Abstract base class for all AuraFactory agents.

    Provides:
    - LLM calling with 1 retry + 2s backoff on timeout/error.
    - Cost tracking for every LLM call.
    - System prompt loading from prompts/ directory.
    - Access to MCP client, memory, knowledge store, skill registry.

    Subclasses MUST implement:
    - execute(task: TaskAssignment) -> TaskResult
    - get_agent_role() -> AgentRole
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
        self._llm = llm
        self._mcp_client = mcp_client
        self._memory = memory
        self._knowledge_store = knowledge_store
        self._settings = settings or {}
        self._skill_registry = skill_registry

    # ============================================================
    # ABSTRACT METHODS
    # ============================================================

    @abstractmethod
    async def execute(self, task: TaskAssignment) -> TaskResult:
        """
        Execute a task assignment. Must be implemented by all agents.

        Args:
            task: The TaskAssignment containing message, context, user role, etc.

        Returns:
            TaskResult with content, status, tools called, and cost info.
        """
        ...

    @abstractmethod
    def get_agent_role(self) -> AgentRole:
        """Return the role enum for this agent."""
        ...

    # ============================================================
    # LLM CALLING (with retry + cost tracking)
    # ============================================================

    async def _call_llm(
        self,
        prompt: str,
        tools: Optional[List[Dict]] = None,
        system_prompt: Optional[str] = None,
        messages: Optional[List[Dict[str, str]]] = None,
        temperature: float = 0.3,
        max_tokens: int = 1500,
    ) -> Optional[LLMResponse]:
        """
        Call LLM with retry logic (1 retry, 2s backoff).

        If both prompt and messages are provided, prompt is appended as
        the last user message.

        Args:
            prompt: User prompt (used if messages is None).
            tools: Optional list of tool definitions for function calling.
            system_prompt: Optional system prompt override.
            messages: Optional pre-built message list.
            temperature: LLM temperature.
            max_tokens: Maximum tokens to generate.

        Returns:
            LLMResponse on success, None if all retries fail.
        """
        # Build messages list
        if messages is None:
            messages = [{"role": "user", "content": prompt}]
        elif prompt:
            messages = messages + [{"role": "user", "content": prompt}]

        # System prompt: use provided or build from file
        sys_prompt = system_prompt or self._build_system_prompt()

        last_error: Optional[Exception] = None

        for attempt in range(MAX_RETRIES + 1):
            try:
                response = await self._llm.generate(
                    messages=messages,
                    system_prompt=sys_prompt,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    tools=tools,
                )

                # Validate response has content
                if not response or not response.content:
                    raise ValueError("LLM returned empty response")

                return response

            except Exception as e:
                last_error = e
                if attempt < MAX_RETRIES:
                    logger.warning(
                        f"[{self.get_agent_role().value}] LLM call failed "
                        f"(attempt {attempt + 1}/{MAX_RETRIES + 1}): {e}. "
                        f"Retrying in {RETRY_BACKOFF_SECONDS}s..."
                    )
                    await asyncio.sleep(RETRY_BACKOFF_SECONDS)
                else:
                    logger.error(
                        f"[{self.get_agent_role().value}] LLM call failed "
                        f"after {MAX_RETRIES + 1} attempts: {last_error}"
                    )

        return None

    # ============================================================
    # COST TRACKING
    # ============================================================

    def _log_cost(
        self,
        trace_id: str,
        tokens_in: int,
        tokens_out: int,
        provider: str,
    ) -> Dict[str, Any]:
        """
        Record cost for a single LLM call.
        Returns cost dict for inclusion in TaskResult.

        Note: Actual persistence to cost_log is done via CostTracker
        at the gateway/orchestrator level. This method builds the metadata.
        """
        cost_info = {
            "trace_id": trace_id,
            "agent": self.get_agent_role().value,
            "provider": provider,
            "input_tokens": tokens_in,
            "output_tokens": tokens_out,
        }
        logger.debug(
            f"[{trace_id}] Cost: {provider} "
            f"in={tokens_in} out={tokens_out}"
        )
        return cost_info

    # ============================================================
    # SYSTEM PROMPT
    # ============================================================

    def _build_system_prompt(self) -> str:
        """
        Load system prompt from prompts/ file based on agent role.
        Injects available tools list if skill_registry is configured.

        File naming convention: prompts/{role}.md
        """
        role = self.get_agent_role().value
        prompt_file = PROMPTS_DIR / f"{role}.md"

        base_prompt = ""
        if prompt_file.exists():
            try:
                base_prompt = prompt_file.read_text(encoding="utf-8")
            except Exception as e:
                logger.warning(f"Failed to load prompt file {prompt_file}: {e}")
                base_prompt = f"You are AuraFactory {role} agent."
        else:
            base_prompt = f"You are AuraFactory {role} agent."

        # Inject available tools if registry is configured
        if self._skill_registry and hasattr(self._skill_registry, "get_all_tools"):
            tools = self._skill_registry.get_all_tools()
            if tools:
                tools_section = "\n\n## Available Tools:\n"
                for tool in tools:
                    name = getattr(tool, "name", str(tool))
                    desc = getattr(tool, "description", "")
                    risk = getattr(tool, "risk_level", "low")
                    tools_section += f"- {name} [{risk}]: {desc}\n"
                base_prompt += tools_section

        return base_prompt

    # ============================================================
    # HELPER: Build error result
    # ============================================================

    def _error_result(self, trace_id: str, message: str = "") -> TaskResult:
        """Build a standardized error TaskResult."""
        return TaskResult(
            trace_id=trace_id,
            content=message or LLM_OVERLOAD_MESSAGE,
            status="failed",
        )

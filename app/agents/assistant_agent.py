# app/agents/assistant_agent.py
"""
AssistantAgent — Q&A from knowledge store (read-only).
NO write tools available.
Flow: search knowledge_store → format answer → return.
If knowledge_store empty/no match → say "Tôi chưa có thông tin về server này"
Fallback gracefully if vector store disabled (keyword search only).
"""
import logging
from typing import Any, Dict, Optional
from app.agents.base import BaseAgent, LLM_OVERLOAD_MESSAGE
from app.agents.contracts import AgentRole, TaskAssignment, TaskResult
logger = logging.getLogger(__name__)


# ============================================================
# SYSTEM PROMPT
# ============================================================

ASSISTANT_SYSTEM_PROMPT: str = """You are AuraFactory — an AI assistant living inside this Discord server.
Your job: help members find information, answer questions, and be friendly.

## Server Knowledge:
{server_context}

## Behavior:
- Answer questions about the server using the knowledge above.
- If you don't have the answer, say so honestly: "Tôi chưa có thông tin về server này. Bạn có thể hỏi admin."
- Be concise, friendly, and helpful.
- When recommending channels, explain briefly why each one fits.
- For new members: welcome warmly, suggest relevant channels.
- You CANNOT modify the server. You have NO tools. Read-only.

## Language Rule:
- Respond in the same language the user used.
- If user writes Vietnamese → respond in Vietnamese.
- If user writes English → respond in English.
"""

NO_KNOWLEDGE_RESPONSE: str = "Tôi chưa có thông tin về server này. Bạn có thể hỏi admin để biết thêm chi tiết."


class AssistantAgent(BaseAgent):
    """
    AssistantAgent — handles Q&A, conversation, and read-only queries.

    Key constraints:
    - NO write tools available (never modifies server state).
    - Read-only access to knowledge store.
    - Graceful fallback when knowledge store is empty or unavailable.

    Flow:
    1. Search knowledge store for relevant context.
    2. Build system prompt with server knowledge.
    3. Single LLM call to generate response.
    4. Return formatted answer.
    """

    def __init__(
        self,
        llm: Any,
        mcp_client: Any = None,
        memory: Any = None,
        knowledge_store: Any = None,
        settings: Optional[Dict[str, Any]] = None,
        skill_registry: Any = None,
    ) -> None:
        super().__init__(
            llm=llm,
            mcp_client=mcp_client,  # Not used — read-only agent
            memory=memory,
            knowledge_store=knowledge_store,
            settings=settings,
            skill_registry=skill_registry,  # Not used — no tools
        )

    # ============================================================
    # MAIN EXECUTE
    # ============================================================

    async def execute(self, task: TaskAssignment) -> TaskResult:
        """
        Execute a Q&A/conversation task.

        Args:
            task: TaskAssignment with message and context.

        Returns:
            TaskResult with generated response.
        """
        trace_id = task.trace_id
        prompt = task.prompt
        guild_id = task.guild_id

        logger.info(f"[{trace_id}] AssistantAgent handling: '{prompt[:60]}...'")

        # ─── Step 1: Get knowledge context ───
        server_context = await self._search_knowledge(guild_id, prompt)

        # ─── Step 2: Build system prompt ───
        system_prompt = ASSISTANT_SYSTEM_PROMPT.format(
            server_context=server_context or "No server knowledge available.",
        )

        # ─── Step 3: Add conversation history if available ───
        messages = await self._build_messages_with_history(prompt, task.session_id)

        # ─── Step 4: Generate response (single LLM call) ───
        response = await self._call_llm(
            prompt="",
            messages=messages,
            system_prompt=system_prompt,
            temperature=0.7,
            max_tokens=1000,
        )

        if not response:
            return self._error_result(trace_id, LLM_OVERLOAD_MESSAGE)

        content = response.content.strip()

        # Log cost
        cost_info = self._log_cost(
            trace_id,
            response.input_tokens,
            response.output_tokens,
            response.model,
        )

        logger.info(f"[{trace_id}] AssistantAgent responded ({len(content)} chars)")

        return TaskResult(
            trace_id=trace_id,
            content=content,
            status="success",
            cost=cost_info,
        )

    # ============================================================
    # KNOWLEDGE SEARCH
    # ============================================================

    async def _search_knowledge(
        self, guild_id: Optional[int], query: str
    ) -> str:
        """
        Search knowledge store for relevant server information.

        Strategy:
        1. Try knowledge_store.get_summary_string() for guild context.
        2. If vector store is available, do semantic search (Phase 2).
        3. Fallback: keyword search if vector store disabled.
        4. If nothing found, return empty string.

        Returns:
            Server context string, or empty string if unavailable.
        """
        if not guild_id or not self._knowledge_store:
            return ""

        try:
            # Primary: get cached summary
            context = await self._knowledge_store.get_summary_string(guild_id)
            if context and context.strip():
                return context
        except Exception as e:
            logger.warning(f"Knowledge store query failed: {e}")

        # Fallback: try keyword-based search if available
        try:
            if hasattr(self._knowledge_store, "search"):
                results = await self._knowledge_store.search(guild_id, query)
                if results:
                    return self._format_search_results(results)
        except Exception as e:
            logger.debug(f"Knowledge store search fallback failed: {e}")

        return ""

    def _format_search_results(self, results: Any) -> str:
        """Format search results into context string."""
        if isinstance(results, list):
            formatted = []
            for r in results[:5]:  # Max 5 results
                if isinstance(r, dict):
                    formatted.append(f"- {r.get('content', str(r))[:200]}")
                else:
                    formatted.append(f"- {str(r)[:200]}")
            return "\n".join(formatted)
        return str(results)[:500]

    # ============================================================
    # CONVERSATION HISTORY
    # ============================================================

    async def _build_messages_with_history(
        self, prompt: str, session_id: str
    ) -> list:
        """Build message list with recent conversation history."""
        messages = []

        # Load history from memory
        if self._memory and session_id:
            try:
                if hasattr(self._memory, "get_conversation_history"):
                    history = await self._memory.get_conversation_history(session_id, limit=5)
                    if history:
                        for msg in history[-5:]:
                            messages.append({
                                "role": msg.get("role", "user"),
                                "content": msg.get("content", "")[:300],
                            })
            except Exception as e:
                logger.debug(f"Failed to load conversation history: {e}")

        # Add current message
        messages.append({"role": "user", "content": prompt})
        return messages

    # ============================================================
    # BASE AGENT INTERFACE
    # ============================================================

    def get_agent_role(self) -> AgentRole:
        return AgentRole.ASSISTANT

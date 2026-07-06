# app/agents/assistant_agent.py
"""
AssistantAgent — 24/7 Q&A + Onboarding.

Responsibilities:
- Answer member questions using Server Knowledge (RAG)
- Generate personalized onboarding DMs for new members
- Handle server_query intents (read-only info)
- Conversational (greeting, chitchat, help)

Does NOT modify the server. No tools. Pure LLM + knowledge context.
"""
import logging
from typing import Dict, Any, Optional

from app.agents.contracts import AgentRole
from app.infra.llm.base import LLMProvider
from app.infra.observability.tracer import Tracer
from app.infra.observability.metrics import metrics
from app.knowledge.store import ServerKnowledgeStore
from app.gateway.pipeline import GatewayContext

logger = logging.getLogger(__name__)


ASSISTANT_SYSTEM_PROMPT = """You are AuraFactory — an AI assistant living inside this Discord server.
Your job: help members find information, answer questions about the server, and make new members feel welcome.

## Server Knowledge:
{server_context}

## Behavior:
- Answer questions about the server using the knowledge above.
- If you don't have the answer, say so honestly and suggest asking an admin.
- Be concise, friendly, and helpful.
- When recommending channels, explain briefly why each one fits.
- For new members: welcome warmly, ask what they're interested in, then recommend relevant channels.
- For server queries: provide accurate info from server knowledge (channels, roles, members, rules).

## Language Rule:
- Respond in the same language the user used.
- If user writes Vietnamese → respond in Vietnamese.
- If user writes English → respond in English.
"""

ONBOARDING_SYSTEM_PROMPT = """You are AuraFactory — the friendly AI assistant for this Discord server.
Write a welcome DM for a new member.

## Server Knowledge:
{server_context}

## Rules:
- Keep it under 250 words.
- Be warm but not overwhelming.
- Use the same language as the server's primary language (Vietnamese default).
"""


class AssistantAgent:
    """
    AssistantAgent — handles all non-admin interactions.

    - Q&A about server (channels, roles, rules, events)
    - Conversational (greeting, help, chitchat)
    - Onboarding DM generation for new members
    - Read-only. Zero side effects on server state.
    """

    def __init__(
        self,
        llm: LLMProvider,
        tracer: Tracer,
        knowledge_store: ServerKnowledgeStore,
        memory=None,
    ):
        self._llm = llm
        self._tracer = tracer
        self._knowledge = knowledge_store
        self._memory = memory

    async def handle(
        self,
        prompt: str,
        guild_id: int,
        guild=None,
        context: GatewayContext = None,
    ) -> Dict[str, Any]:
        """
        Handle a user message in Assistant Mode.
        Uses Server Knowledge as context for LLM generation.
        """
        trace_id = context.trace_id if context else "no-trace"
        session_id = context.session_id if context else ""

        logger.info(f"[{trace_id}] AssistantAgent handling message for guild {guild_id}")

        # Build server context from knowledge store
        server_context = "No server knowledge available."
        if guild_id:
            server_context = await self._knowledge.get_summary_string(guild_id)

        system_prompt = ASSISTANT_SYSTEM_PROMPT.format(server_context=server_context)

        # Add conversation history for continuity
        if self._memory and session_id:
            try:
                history = await self._memory.get_conversation_history(session_id, limit=5)
                if history:
                    system_prompt += "\n\n## Recent conversation:\n"
                    for msg in history[-5:]:
                        role = msg.get("role", "?")
                        content = msg.get("content", "")[:150]
                        system_prompt += f"- {role}: {content}\n"
            except Exception:
                pass

        # Generate response
        response = await self._llm.generate(
            messages=[{"role": "user", "content": prompt}],
            system_prompt=system_prompt,
            temperature=0.7,
            max_tokens=1000,
        )

        metrics.count_request(response.model, "assistant", "success")
        metrics.count_tokens(response.model, response.input_tokens, response.output_tokens)

        # Store in memory
        if self._memory and session_id:
            await self._memory.add_message(
                session_id=session_id, user_id="assistant", role="assistant", content=response.content
            )

        return {
            "status": "response",
            "content": response.content,
            "trace_id": trace_id,
            "mode": "assistant",
        }

    async def generate_onboarding(self, guild_id: int, member_name: str) -> str:
        """
        Generate a personalized onboarding DM for a new member.
        Called by lifecycle event handler when member joins.
        """
        server_context = await self._knowledge.get_summary_string(guild_id)

        prompt = f"""A new member named "{member_name}" just joined the server.
Generate a short, warm welcome DM that:
1. Welcomes them by name
2. Briefly explains what the server is about (1-2 sentences from server knowledge)
3. Asks ONE question about their interests (give 3-4 emoji reaction options)
4. Mentions where to find rules (#rules or similar channel)
5. Says they can ask you anything anytime

Keep it concise. Not overwhelming. Friendly tone.
"""

        system = ONBOARDING_SYSTEM_PROMPT.format(server_context=server_context)

        response = await self._llm.generate(
            messages=[{"role": "user", "content": prompt}],
            system_prompt=system,
            temperature=0.8,
            max_tokens=500,
        )

        metrics.count_request(response.model, "assistant_onboarding", "success")
        return response.content

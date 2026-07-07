# app/services/query_service.py
"""
QueryService — Handles read-only queries about server state (§5.4, intent=query).

This service answers user questions about the current state of their Discord
server without executing any tools, creating plans, or requiring approval.
It uses server context + LLM to generate natural language answers.
"""

from __future__ import annotations

import logging
from typing import Dict, List, Optional

from app.llm.base import BaseLLM, LLMResponse
from app.mcp.client import MCPClient
from app.services.context_service import ContextService

logger = logging.getLogger(__name__)

# System prompt for query answering
QUERY_SYSTEM_PROMPT = """You are AuraFactory, a Discord server management assistant.
You are answering a READ-ONLY question about the server's current state.
You have access to the server context below — use it to provide accurate, helpful answers.

Guidelines:
- Be concise and direct.
- If the information is available in the context, cite specifics (names, counts, settings).
- If the information is NOT in the context, say so honestly — do not invent data.
- Format lists and structured data clearly.
- Use Discord-friendly formatting (bold, bullet points) when appropriate.
- Do NOT suggest making changes — this is a read-only query.
- Respond in the same language the user used."""


class QueryService:
    """Handles read-only queries about server state.

    §5.4: When intent=query, the system answers directly from cached
    server context without executing tools, creating plans, or
    requiring approval. This is the fastest path through the system.
    """

    def __init__(
        self,
        llm: BaseLLM,
        mcp_client: MCPClient,
        context_service: ContextService,
    ) -> None:
        self._llm = llm
        self._mcp_client = mcp_client
        self._context_service = context_service

    async def answer(
        self,
        message: str,
        guild_id: int,
        history: Optional[List[Dict[str, str]]] = None,
    ) -> str:
        """Answer a read-only question about the server.

        Uses server context + LLM to generate natural language answer.
        No tools executed, no plan needed, no approval needed.

        Args:
            message: The user's question/query text.
            guild_id: Discord guild (server) ID for context lookup.
            history: Optional conversation history [{role, content}, ...].

        Returns:
            Natural language answer string.
        """
        # 1. Get server context
        server_context = await self._context_service.get_server_context(guild_id)

        # 2. Build messages with context + user question
        messages = self._build_messages(
            message=message,
            server_context=server_context,
            history=history,
        )

        # 3. LLM generate response
        try:
            response: LLMResponse = await self._llm.generate(
                messages=messages,
                system_prompt=QUERY_SYSTEM_PROMPT,
                temperature=0.3,  # Low temperature for factual accuracy
                max_tokens=2048,
            )
        except Exception as e:
            logger.error(
                "[QueryService] LLM generation failed for guild %d: %s",
                guild_id,
                str(e),
            )
            return (
                "⚠️ Xin lỗi, tôi không thể trả lời câu hỏi này lúc này. "
                "Vui lòng thử lại sau."
            )

        # 4. Return answer text
        if not response.content:
            return (
                "Tôi không tìm thấy thông tin phù hợp để trả lời câu hỏi của bạn. "
                "Bạn có thể hỏi cụ thể hơn được không?"
            )

        return response.content

    # ------------------------------------------------------------------
    # Internal Helpers
    # ------------------------------------------------------------------

    def _build_messages(
        self,
        message: str,
        server_context: dict,
        history: Optional[List[Dict[str, str]]] = None,
    ) -> List[Dict[str, str]]:
        """Build the message list for the LLM call.

        Includes server context as a system-like user message,
        optional conversation history, and the current question.

        Args:
            message: The user's current question.
            server_context: Dict with server state information.
            history: Optional prior conversation turns.

        Returns:
            List of message dicts ready for LLM.generate().
        """
        messages: List[Dict[str, str]] = []

        # Inject server context as the first message
        context_text = self._format_server_context(server_context)
        messages.append({
            "role": "user",
            "content": f"[SERVER CONTEXT]\n{context_text}",
        })
        messages.append({
            "role": "assistant",
            "content": "Understood. I have the current server state. What would you like to know?",
        })

        # Add conversation history if provided
        if history:
            # Limit history to last 10 turns to avoid token overflow
            for turn in history[-10:]:
                role = turn.get("role", "user")
                content = turn.get("content", "")
                if role in ("user", "assistant") and content:
                    messages.append({"role": role, "content": content})

        # Add the current question
        messages.append({"role": "user", "content": message})

        return messages

    def _format_server_context(self, server_context: dict) -> str:
        """Format server context dict into a readable string for the LLM.

        Args:
            server_context: Dict from ContextService.get_server_context().

        Returns:
            Formatted string representation of the server state.
        """
        if not server_context:
            return "No server context available."

        lines: List[str] = []

        # Server info
        if "server" in server_context:
            server = server_context["server"]
            lines.append(f"**Server**: {server.get('name', 'Unknown')}")
            if "member_count" in server:
                lines.append(f"**Members**: {server['member_count']}")
            if "owner_id" in server:
                lines.append(f"**Owner ID**: {server['owner_id']}")

        # Channels
        if "channels" in server_context:
            channels = server_context["channels"]
            lines.append(f"\n**Channels** ({len(channels)} total):")
            for ch in channels[:50]:  # Cap display to 50
                ch_type = ch.get("type", "text")
                category = ch.get("category", "")
                cat_str = f" [{category}]" if category else ""
                lines.append(f"  - #{ch.get('name', '?')} ({ch_type}){cat_str}")

        # Roles
        if "roles" in server_context:
            roles = server_context["roles"]
            lines.append(f"\n**Roles** ({len(roles)} total):")
            for role in roles[:50]:  # Cap display to 50
                member_count = role.get("member_count", "?")
                lines.append(
                    f"  - @{role.get('name', '?')} "
                    f"(members: {member_count}, color: {role.get('color', 'default')})"
                )

        # Categories
        if "categories" in server_context:
            categories = server_context["categories"]
            lines.append(f"\n**Categories** ({len(categories)} total):")
            for cat in categories:
                lines.append(f"  - {cat.get('name', '?')}")

        # Additional info (permissions, features, etc.)
        if "features" in server_context:
            features = server_context["features"]
            if features:
                lines.append(f"\n**Server Features**: {', '.join(features)}")

        if "boost_level" in server_context:
            lines.append(f"**Boost Level**: {server_context['boost_level']}")

        return "\n".join(lines) if lines else str(server_context)

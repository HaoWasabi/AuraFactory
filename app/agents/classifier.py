# app/agents/classifier.py
"""
Intent Classifier — fast, cheap LLM call to route messages.
Routes: conversation → AssistantAgent, command → AdminAgent, server_query → AssistantAgent w/ guild.
"""
import logging
from typing import Literal
from app.infra.llm.base import LLMProvider
logger = logging.getLogger(__name__)
IntentType = Literal["conversation", "command", "server_query"]

CLASSIFY_PROMPT = """Classify this user message into exactly ONE category:
- "conversation" — greeting, chitchat, general question, help request, thank you
- "command" — wants to CREATE, MODIFY, DELETE, or CONFIGURE something on Discord server
- "server_query" — asking about current server state (list channels, show roles, who is online, server info)

User message: "{message}"

Respond with ONLY the category name. No explanation, no quotes, no punctuation."""


class IntentClassifier:
    """
    Fast intent classification — single cheap LLM call.
    Determines routing BEFORE expensive agentic loop.
    """

    def __init__(self, llm: LLMProvider):
        self._llm = llm

    async def classify(self, message: str) -> IntentType:
        """
        Classify user message intent.
        Returns: 'conversation' | 'command' | 'server_query'
        """
        try:
            response = await self._llm.generate(
                messages=[{"role": "user", "content": message}],
                system_prompt=CLASSIFY_PROMPT.format(message=message[:500]),
                temperature=0.0,
                max_tokens=20,
            )

            result = response.content.strip().lower().strip('"\'.')
            if result in ("conversation", "command", "server_query"):
                return result

            # Fallback heuristics if LLM gives unexpected output
            return self._fallback_classify(message)

        except Exception as e:
            logger.warning(f"Classifier error: {e}, falling back to heuristic")
            return self._fallback_classify(message)

    def _fallback_classify(self, message: str) -> IntentType:
        """Rule-based fallback when LLM fails."""
        msg_lower = message.lower()

        # Command keywords
        command_words = [
            "tạo", "xóa", "sửa", "đổi", "thêm", "bỏ", "set", "move",
            "create", "delete", "remove", "add", "modify", "setup", "configure",
            "kick", "ban", "mute", "timeout", "assign", "role",
        ]
        if any(w in msg_lower for w in command_words):
            return "command"

        # Query keywords
        query_words = [
            "list", "liệt kê", "show", "hiện", "bao nhiêu", "how many",
            "ai là", "who is", "info", "thông tin", "server",
        ]
        if any(w in msg_lower for w in query_words):
            return "server_query"

        return "conversation"

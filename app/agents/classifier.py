# app/agents/classifier.py
"""
Intent Classifier — single LLM call to route messages.
Returns: intent + complexity in one call.
"""
import json
import logging
from typing import Literal, Tuple
from dataclasses import dataclass

from app.infra.llm.base import LLMProvider

logger = logging.getLogger(__name__)

IntentType = Literal["conversation", "command", "server_query"]
ComplexityType = Literal["simple", "complex"]


@dataclass
class ClassifyResult:
    """Result of classification."""
    intent: IntentType
    complexity: ComplexityType

    @property
    def is_fast_track(self) -> bool:
        return self.intent == "command" and self.complexity == "simple"

    @property
    def is_react_track(self) -> bool:
        return self.intent == "command" and self.complexity == "complex"


CLASSIFY_PROMPT = """Classify this Discord message. Return JSON only:
{{"intent": "conversation|command|server_query", "complexity": "simple|complex"}}

Rules:
- "command": wants to CREATE/MODIFY/DELETE something (channels, roles, members, permissions)
- "server_query": asking about server state (list channels, member count, server info)
- "conversation": greeting, chitchat, general question, thanks
- "simple": 1-2 clear actions (e.g. "tạo channel general", "kick user X")
- "complex": 3+ actions, vague, needs planning (e.g. "setup server for gaming", "reorganize channels")

Message: "{message}"
JSON:"""


class IntentClassifier:
    """
    Single LLM call: intent + complexity.
    Determines routing: fast track vs react track vs assistant.
    """

    def __init__(self, llm: LLMProvider):
        self._llm = llm

    async def classify(self, message: str) -> ClassifyResult:
        """
        Classify user message.
        Returns ClassifyResult with intent + complexity.
        """
        try:
            response = await self._llm.generate(
                messages=[{"role": "user", "content": message}],
                system_prompt=CLASSIFY_PROMPT.format(message=message[:300]),
                temperature=0.0,
                max_tokens=50,
            )

            raw = response.content.strip()
            parsed = self._parse_json(raw)

            intent = parsed.get("intent", "conversation")
            complexity = parsed.get("complexity", "simple")

            # Validate
            if intent not in ("conversation", "command", "server_query"):
                intent = self._fallback_intent(message)
            if complexity not in ("simple", "complex"):
                complexity = "simple"

            return ClassifyResult(intent=intent, complexity=complexity)

        except Exception as e:
            logger.warning(f"Classifier error: {e}, falling back to heuristic")
            return ClassifyResult(
                intent=self._fallback_intent(message),
                complexity=self._fallback_complexity(message),
            )

    def _parse_json(self, raw: str) -> dict:
        """Extract JSON from LLM output."""
        text = raw.strip().strip("`").strip()
        if text.startswith("json"):
            text = text[4:].strip()
        if "{" in text:
            start = text.index("{")
            end = text.rindex("}") + 1
            return json.loads(text[start:end])
        return {}

    def _fallback_intent(self, message: str) -> IntentType:
        """Rule-based fallback."""
        msg = message.lower()
        command_words = [
            "tạo", "xóa", "sửa", "đổi", "thêm", "bỏ", "set", "move",
            "create", "delete", "remove", "add", "modify", "setup", "configure",
            "kick", "ban", "mute", "timeout", "assign", "role",
        ]
        if any(w in msg for w in command_words):
            return "command"

        query_words = [
            "list", "liệt kê", "show", "hiện", "bao nhiêu", "how many",
            "ai là", "who is", "info", "thông tin",
        ]
        if any(w in msg for w in query_words):
            return "server_query"

        return "conversation"

    def _fallback_complexity(self, message: str) -> ComplexityType:
        """Rule-based complexity detection."""
        msg = message.lower()
        complex_signals = [
            "setup", "cấu hình", "toàn bộ", "full", "reorganize",
            "thiết kế", "đề xuất", "propose", "plan",
            " và ", " and ", ",",  # Multiple items
        ]
        if sum(1 for s in complex_signals if s in msg) >= 2:
            return "complex"
        return "simple"

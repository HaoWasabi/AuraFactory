# app/agents/classifier.py
"""
IntentClassifier — Classifies user messages into routing intents.
Uses LLM with structured prompt, with heuristic fallback.
Output: FAST_TRACK | ADMIN_COMPLEX | ASSISTANT
"""
import json
import logging
from typing import Optional
from app.agents.contracts import IntentType
from app.infra.llm.base import LLMProvider
logger = logging.getLogger(__name__)


# ============================================================
# CLASSIFICATION PROMPT
# ============================================================

CLASSIFY_PROMPT: str = """Classify this user request. Output ONLY one of: FAST_TRACK, ADMIN_COMPLEX, ASSISTANT

Rules:
- FAST_TRACK: Single clear action with 1 verb + 1 object (e.g., "tạo channel general", "kick @user", "xóa role X")
- ADMIN_COMPLEX: Multiple actions, vague request needing planning, setup commands, bulk operations (e.g., "setup gaming server", "reorganize all channels", "tạo 5 channel")
- ASSISTANT: Questions, greetings, help requests, info queries, chitchat (e.g., "server có bao nhiêu member?", "hi", "how do I use this bot?")

User role: {role}
Message: {msg}

Output ONLY one of: FAST_TRACK, ADMIN_COMPLEX, ASSISTANT"""


# ============================================================
# HEURISTIC PATTERNS
# ============================================================

_QUESTION_STARTERS: set[str] = {
    "?", "what", "how", "why", "when", "where", "who", "which",
    "là gì", "bao nhiêu", "như thế nào", "tại sao", "ở đâu",
    "ai là", "cái gì", "có bao nhiêu", "help", "giúp",
}

_SINGLE_ACTION_VERBS: set[str] = {
    "tạo", "xóa", "sửa", "đổi", "thêm", "bỏ", "kick", "ban",
    "mute", "unmute", "unban", "timeout", "create", "delete",
    "remove", "add", "rename", "move", "set", "assign",
}

_COMPLEX_SIGNALS: set[str] = {
    "setup", "cấu hình", "thiết lập", "toàn bộ", "tất cả",
    "reorganize", "redesign", "full", "propose", "đề xuất",
    "kế hoạch", "plan", "nhiều", "batch", "bulk",
}


class IntentClassifier:
    """
    Classifies incoming messages into IntentType.

    Strategy:
    1. Try LLM classification (structured prompt → single token output).
    2. If LLM fails or is unavailable → use heuristic fallback.

    Heuristic rules:
    - Message starts with "?" or contains question words → ASSISTANT
    - Single clear action verb + object → FAST_TRACK
    - Multiple actions or complex signals → ADMIN_COMPLEX
    - Default → ASSISTANT
    """

    def __init__(self, llm: LLMProvider) -> None:
        self._llm = llm

    async def classify(self, message: str, user_role: str = "member") -> IntentType:
        """
        Classify a user message into an IntentType.

        Args:
            message: The raw user message text.
            user_role: The user's detected role (owner/admin/moderator/member).

        Returns:
            IntentType: FAST_TRACK, ADMIN_COMPLEX, or ASSISTANT.
        """
        # Try LLM classification first
        llm_result = await self._classify_with_llm(message, user_role)
        if llm_result is not None:
            return llm_result

        # Fallback to heuristic
        logger.debug("LLM classification failed, using heuristic fallback")
        return self._classify_heuristic(message)

    async def _classify_with_llm(
        self, message: str, user_role: str
    ) -> Optional[IntentType]:
        """
        Use LLM to classify the message.
        Returns None if LLM call fails or returns invalid output.
        """
        try:
            prompt = CLASSIFY_PROMPT.format(
                role=user_role,
                msg=message[:300],  # Truncate long messages
            )

            response = await self._llm.generate(
                messages=[{"role": "user", "content": prompt}],
                system_prompt="",
                temperature=0.0,
                max_tokens=20,
            )

            if not response or not response.content:
                return None

            raw = response.content.strip().upper()

            # Parse the response — look for one of the three values
            if "FAST_TRACK" in raw:
                return IntentType.FAST_TRACK
            elif "ADMIN_COMPLEX" in raw:
                return IntentType.ADMIN_COMPLEX
            elif "ASSISTANT" in raw:
                return IntentType.ASSISTANT

            logger.warning(f"LLM classifier returned unexpected: '{raw}'")
            return None

        except Exception as e:
            logger.warning(f"LLM classification error: {e}")
            return None

    def _classify_heuristic(self, message: str) -> IntentType:
        """
        Rule-based fallback classification.

        Logic:
        1. If starts with "?" or contains question words → ASSISTANT
        2. If single clear action verb + object → FAST_TRACK
        3. If contains complex signals or multiple actions → ADMIN_COMPLEX
        4. Default → ASSISTANT
        """
        msg_lower = message.lower().strip()

        # Rule 1: Question detection
        if msg_lower.startswith("?"):
            return IntentType.ASSISTANT

        # Rule 1.5: Check for "setup"/"set up" FIRST (before single verbs catch "set")
        if "setup" in msg_lower or "set up" in msg_lower or "settup" in msg_lower:
            return IntentType.ADMIN_COMPLEX

        for starter in _QUESTION_STARTERS:
            if msg_lower.startswith(starter) or f" {starter}" in msg_lower:
                return IntentType.ASSISTANT

        # Rule 3: Complex signals (check before simple to avoid false positives)
        complex_count = sum(1 for signal in _COMPLEX_SIGNALS if signal in msg_lower)
        if complex_count >= 1:
            return IntentType.ADMIN_COMPLEX

        # Multiple commas or "và"/"and" suggest multiple items
        if msg_lower.count(",") >= 2 or (" và " in msg_lower and any(v in msg_lower for v in _SINGLE_ACTION_VERBS)):
            return IntentType.ADMIN_COMPLEX

        # Rule 2: Single action verb detection
        for verb in _SINGLE_ACTION_VERBS:
            if verb in msg_lower:
                return IntentType.FAST_TRACK

        # Default: treat as assistant/conversation
        return IntentType.ASSISTANT

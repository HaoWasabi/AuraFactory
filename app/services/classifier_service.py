"""ClassifierService — classifies user intent into categories."""
import json
import logging
from typing import Optional

from app.llm.base import BaseLLM

logger = logging.getLogger(__name__)

# Intent categories from spec §7
INTENTS = {
    "setup": "Create categories, channels, roles, permissions from scratch",
    "manage": "Move, rename, edit, delete channels/roles/categories",
    "moderate": "Kick, ban, timeout, unban members",
    "query": "Read-only questions about server state",
    "server_settings": "Edit server profile, verification level, invites, emojis, webhooks",
    "automod": "Create/delete automod rules, events",
    "clarify": "User message is too vague to determine intent",
    "out_of_scope": "Request is outside what AuraFactory can do",
}

CLASSIFIER_SYSTEM_PROMPT = """You are an intent classifier for a Discord server management AI.
Given a user message, classify it into ONE of these intents:
- setup: Creating new categories, channels, roles, permissions
- manage: Moving, renaming, editing, deleting existing channels/roles
- moderate: Kick/ban/timeout/unban members
- query: Read-only questions about server state (list channels, roles, etc.)
- server_settings: Server profile, verification level, invites, emojis, webhooks
- automod: Automod rules, scheduled events
- clarify: Message is too vague, need more info
- out_of_scope: Not related to Discord server management

Also determine:
- tool_mode: "action" (setup/manage/moderate/server_settings/automod), "read_only" (query), "none" (clarify/out_of_scope)
- lang: detect the language of the user message — "vi" for Vietnamese, "en" for English

Respond in JSON only: {"intent": "...", "tool_mode": "...", "confidence": 0.0-1.0, "lang": "vi"|"en"}"""


class ClassifierService:
    """Classifies user messages into intents."""

    def __init__(self, llm: BaseLLM):
        self.llm = llm

    async def classify(self, message: str, history: list = None) -> dict:
        """Classify a user message.

        Returns:
            {"intent": str, "tool_mode": str, "confidence": float, "lang": str}
        """
        if self.llm is None:
            logger.error("LLM not initialized — cannot classify")
            return {"intent": "clarify", "tool_mode": "none", "confidence": 0.0, "lang": self._detect_lang_simple(message)}

        messages = []
        if history:
            # Include last 2 messages for context
            for h in history[-2:]:
                messages.append({"role": h.get("role", "user"), "content": h.get("content", "")})
        messages.append({"role": "user", "content": message})

        try:
            response = await self.llm.generate(
                messages=messages,
                system_prompt=CLASSIFIER_SYSTEM_PROMPT,
                temperature=0.1,
                max_tokens=200,
            )
            result = json.loads(response.content.strip().strip("```json").strip("```"))
            # Validate
            if result.get("intent") not in INTENTS:
                result["intent"] = "clarify"
            if result.get("tool_mode") not in ("action", "read_only", "none"):
                result["tool_mode"] = "none"
            if result.get("lang") not in ("vi", "en"):
                result["lang"] = self._detect_lang_simple(message)
            return result
        except (json.JSONDecodeError, Exception) as e:
            logger.warning("Classification failed: %s — defaulting to clarify", e)
            return {"intent": "clarify", "tool_mode": "none", "confidence": 0.0, "lang": self._detect_lang_simple(message)}

    @staticmethod
    def _detect_lang_simple(text: str) -> str:
        """Simple heuristic language detection fallback."""
        # Vietnamese-specific characters
        viet_chars = set("àáảãạăắằẳẵặâấầẩẫậèéẻẽẹêếềểễệìíỉĩịòóỏõọôốồổỗộơớờởỡợùúủũụưứừửữựỳýỷỹỵđ")
        text_lower = text.lower()
        if any(c in viet_chars for c in text_lower):
            return "vi"
        return "en"

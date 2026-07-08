"""ClassifierService — classifies user intent into categories."""
import json
import logging
from typing import Optional

from app.llm.base import BaseLLM
from app.services._token_tracker import record_token_usage

logger = logging.getLogger(__name__)

# Intent categories from spec §7
INTENTS = {
    "setup": "Create categories, channels (text/voice/stage/forum/news), roles, permissions from scratch",
    "manage": "Move, rename, edit, delete channels/roles/categories; change channel permissions",
    "moderate": "Kick, ban, timeout, unban members",
    "query": "Read-only questions about server state",
    "server_settings": (
        "Edit server profile (name/icon/banner/description), verification level, Community feature, "
        "system channels, notification level, AFK config, preferred locale, content filter"
    ),
    "automod": "Create/delete automod rules, events",
    "clarify": "User message is too vague to determine intent",
    "out_of_scope": "Request is outside what AuraFactory can do",
}

CLASSIFIER_SYSTEM_PROMPT = """You are an intent classifier for a Discord server management AI.
Given a user message, classify it into ONE of these intents:

- setup: Creating NEW categories, channels (text/voice/stage/forum/news), roles, permissions from scratch;
         also includes creating a role AND immediately assigning it to a member in the same request
- manage: Moving, renaming, editing, deleting EXISTING channels/roles/categories;
          also includes changing channel permissions (is_private, allowed_roles, slowmode, nsfw, bitrate, user_limit);
          also includes assigning or removing EXISTING roles to/from members (gán role, gỡ role, thêm role cho user)
- moderate: Kick/ban/timeout/unban/warn members
- query: Read-only questions — "list channels", "what roles exist", "server info", "thông tin server"
- server_settings: Any change to the server (guild) itself:
    * Server name, icon, banner, description
    * Verification level / security level
    * Enable/disable Community feature
    * System messages channel, join/boost/tips notifications
    * Default notification level (all messages vs only mentions)
    * AFK channel and timeout
    * Server language / preferred locale
    * Explicit content filter
- automod: Automod rules, scheduled events
- clarify: Message is too vague or missing required details
- out_of_scope: Not related to Discord server management

CLASSIFICATION HINTS:
- "tạo role ... và gán cho", "tạo role ... rồi gán", "tạo role cho tôi" → setup  (tạo mới + gán = setup)
- "gán role", "thêm role cho", "assign role", "gắn role", "cấp role" → manage  (role đã tồn tại)
- "gỡ role", "xóa role khỏi", "remove role", "lấy lại role" → manage
- "đổi tên server", "đổi icon", "đổi banner" → server_settings
- "bật/tắt Community", "bật community" → server_settings
- "tăng bảo mật", "verification level" → server_settings
- "tắt thông báo join", "thông báo boost" → server_settings
- "đặt kênh AFK", "AFK timeout" → server_settings
- "đổi ngôn ngữ server" → server_settings
- "thông tin server", "xem server info" → query
- "tạo kênh private", "kênh ẩn", "kênh chỉ cho role X" → setup
- "tạo kênh forum/stage/news/announcement" → setup
- "sửa quyền kênh", "tắt quyền gửi tin" → manage

Also determine:
- tool_mode: "action" (setup/manage/moderate/server_settings/automod), "read_only" (query), "none" (clarify/out_of_scope)
- lang: "vi" for Vietnamese, "en" for English

Respond in JSON only: {"intent": "...", "tool_mode": "...", "confidence": 0.0-1.0, "lang": "vi"|"en"}"""


class ClassifierService:
    """Classifies user messages into intents."""

    def __init__(self, llm: BaseLLM):
        self.llm = llm

    async def classify(self, message: str, history: list = None, db=None, request_id: str = None) -> dict:
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
            # Record token usage if db and request_id provided
            if db and request_id:
                await record_token_usage(db, request_id, response.usage, getattr(self.llm, 'provider_name', 'unknown'))
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

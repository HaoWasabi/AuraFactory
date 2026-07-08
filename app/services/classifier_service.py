"""ClassifierService — classifies user intent into categories."""
import json
import logging
from dataclasses import dataclass, field
from typing import Optional

from app.llm.base import BaseLLM
from app.services._token_tracker import record_token_usage

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

CLASSIFIER_SYSTEM_PROMPT = """Bạn là Aura — trợ lý Discord thông minh của AuraFactory, thân thiện và am hiểu Discord.
Phân loại tin nhắn người dùng thành MỘT trong các intents sau:
- setup: Tạo mới categories, channels, roles, permissions
- manage: Di chuyển, đổi tên, chỉnh sửa, xóa channels/roles/categories hiện có
- moderate: Kick/ban/timeout/unban thành viên
- query: Câu hỏi read-only về trạng thái server
- server_settings: Cài đặt server, verification level, invites, emojis, webhooks
- automod: Automod rules, scheduled events
- clarify: Tin nhắn quá mơ hồ, cần thêm thông tin
- out_of_scope: Không liên quan đến quản lý Discord server

Ngoài intent chính, hãy trích xuất thêm:
- understood_as: mô tả ngắn (1 câu) bằng ngôn ngữ người dùng về ý định được hiểu
- entities: Discord entities được nhắc đến {"channels": ["tên"], "roles": ["tên"], "categories": ["tên"], "members": ["tên"]}
- emotional_tone: "neutral" | "frustrated" | "excited" | "confused"
- is_goal_statement: true nếu user mô tả mục tiêu tổng thể (ví dụ "tôi muốn setup server gaming")
- is_diagnostic_request: true nếu user báo cáo lỗi hoặc vấn đề

Trả về JSON duy nhất, không có markdown:
{"intent": "...", "tool_mode": "action|read_only|none", "confidence": 0.0-1.0, "lang": "vi|en",
 "understood_as": "...", "entities": {"channels": [], "roles": [], "categories": [], "members": []},
 "emotional_tone": "neutral", "is_goal_statement": false, "is_diagnostic_request": false}"""


@dataclass
class EnrichedClassification:
    """Enriched classification result — superset of the legacy dict format."""
    # === Legacy fields (backward compatible) ===
    intent: str
    tool_mode: str          # "action" | "read_only" | "none"
    confidence: float       # 0.0 – 1.0
    lang: str               # "vi" | "en"

    # === New fields ===
    understood_as: str = ""
    actions: list = field(default_factory=list)
    entities: dict = field(default_factory=dict)
    # {"channels": [], "roles": [], "categories": [], "members": []}
    emotional_tone: str = "neutral"
    # "neutral" | "frustrated" | "excited" | "confused"
    clarification_needed: bool = False
    is_goal_statement: bool = False
    is_diagnostic_request: bool = False

    def to_legacy_dict(self) -> dict:
        """Return dict with only the 4 legacy keys — for backward compat."""
        return {
            "intent": self.intent,
            "tool_mode": self.tool_mode,
            "confidence": self.confidence,
            "lang": self.lang,
        }


class ClassifierService:
    """Classifies user messages into intents."""

    def __init__(self, llm: BaseLLM):
        self.llm = llm

    async def classify(self, message: str, history: list = None, db=None, request_id: str = None, enriched: bool = False):
        """Classify a user message.

        Args:
            enriched: If True, return EnrichedClassification. If False (default),
                      return legacy dict {"intent", "tool_mode", "confidence", "lang"}.
        """
        # Pre-process: expand semantic terms
        try:
            from app.data.semantic_map import expand_message, detect_goal_statement, detect_diagnostic_request
            expanded_message, matched_terms = expand_message(message)
        except ImportError:
            expanded_message, matched_terms = message, []

        if self.llm is None:
            logger.error("LLM not initialized — cannot classify")
            result = EnrichedClassification(
                intent="clarify", tool_mode="none", confidence=0.0,
                lang=self._detect_lang_simple(message),
            )
            return result if enriched else result.to_legacy_dict()

        messages = []
        if history:
            for h in history[-2:]:
                messages.append({"role": h.get("role", "user"), "content": h.get("content", "")})
        messages.append({"role": "user", "content": expanded_message})

        # Inject semantic context hint if matches found
        system_prompt = CLASSIFIER_SYSTEM_PROMPT
        if matched_terms:
            hint = f"\n[Semantic hint: user message matches: {', '.join(matched_terms[:5])}]"
            system_prompt = CLASSIFIER_SYSTEM_PROMPT + hint

        try:
            response = await self.llm.generate(
                messages=messages,
                system_prompt=system_prompt,
                temperature=0.1,
                max_tokens=300,
            )
            raw = response.content.strip().strip("```json").strip("```").strip()
            parsed = json.loads(raw)

            # Record token usage
            if db and request_id:
                await record_token_usage(db, request_id, response.usage, getattr(self.llm, 'provider_name', 'unknown'))

            # Build EnrichedClassification
            intent = parsed.get("intent", "clarify")
            if intent not in INTENTS:
                intent = "clarify"
            tool_mode = parsed.get("tool_mode", "none")
            if tool_mode not in ("action", "read_only", "none"):
                tool_mode = "none"
            lang = parsed.get("lang", self._detect_lang_simple(message))
            if lang not in ("vi", "en"):
                lang = self._detect_lang_simple(message)

            # Try to get goal/diagnostic from semantic map if LLM missed it
            try:
                from app.data.semantic_map import detect_goal_statement, detect_diagnostic_request
                is_goal = parsed.get("is_goal_statement", False) or detect_goal_statement(message)
                is_diag = parsed.get("is_diagnostic_request", False) or detect_diagnostic_request(message)
            except ImportError:
                is_goal = parsed.get("is_goal_statement", False)
                is_diag = parsed.get("is_diagnostic_request", False)

            result = EnrichedClassification(
                intent=intent,
                tool_mode=tool_mode,
                confidence=float(parsed.get("confidence", 0.5)),
                lang=lang,
                understood_as=parsed.get("understood_as", ""),
                actions=parsed.get("actions", []),
                entities=parsed.get("entities", {"channels": [], "roles": [], "categories": [], "members": []}),
                emotional_tone=parsed.get("emotional_tone", "neutral"),
                clarification_needed=(intent == "clarify"),
                is_goal_statement=is_goal,
                is_diagnostic_request=is_diag,
            )

            return result if enriched else result.to_legacy_dict()

        except (json.JSONDecodeError, Exception) as e:
            logger.warning("Classification failed: %s — defaulting to clarify", e)
            result = EnrichedClassification(
                intent="clarify", tool_mode="none", confidence=0.0,
                lang=self._detect_lang_simple(message),
            )
            return result if enriched else result.to_legacy_dict()

    @staticmethod
    def _detect_lang_simple(text: str) -> str:
        """Simple heuristic language detection fallback."""
        # Vietnamese-specific characters
        viet_chars = set("àáảãạăắằẳẵặâấầẩẫậèéẻẽẹêếềểễệìíỉĩịòóỏõọôốồổỗộơớờởỡợùúủũụưứừửữựỳýỷỹỵđ")
        text_lower = text.lower()
        if any(c in viet_chars for c in text_lower):
            return "vi"
        return "en"

"""Semantic map — zero-LLM preprocessing for AuraFactory.

Maps informal Vietnamese/English user terms to canonical Discord actions.
Loaded once at startup; supports hot-reload via reload_semantic_map().
"""
from __future__ import annotations

import importlib
import logging
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class SemanticEntry:
    canonical_action: str   # e.g. "create_channel"
    params_hint: dict = field(default_factory=dict)


@dataclass
class ArchetypeConfig:
    name: str
    tone: str                      # "casual" | "structured" | "warm" | "formal"
    vocabulary_tags: list[str] = field(default_factory=list)
    suggestion_style: str = "neutral"


# ---------------------------------------------------------------------------
# Semantic Map — 60+ entries, Vietnamese + English
# ---------------------------------------------------------------------------

SEMANTIC_MAP: dict[str, SemanticEntry] = {
    # ---- Create channel (Vietnamese) ----
    "tạo kênh": SemanticEntry("create_channel"),
    "thêm kênh": SemanticEntry("create_channel"),
    "tạo channel": SemanticEntry("create_channel"),
    "thêm channel": SemanticEntry("create_channel"),
    "kênh text": SemanticEntry("create_channel", {"type": "text"}),
    "kênh thoại": SemanticEntry("create_channel", {"type": "voice"}),
    "kênh voice": SemanticEntry("create_channel", {"type": "voice"}),
    "kênh âm thanh": SemanticEntry("create_channel", {"type": "voice"}),
    # ---- Delete channel ----
    "xóa kênh": SemanticEntry("delete_channel"),
    "xóa channel": SemanticEntry("delete_channel"),
    "bỏ kênh": SemanticEntry("delete_channel"),
    "xóa bỏ kênh": SemanticEntry("delete_channel"),
    "remove kênh": SemanticEntry("delete_channel"),
    # ---- Edit channel ----
    "đổi tên kênh": SemanticEntry("rename_channel"),
    "đổi tên channel": SemanticEntry("rename_channel"),
    "sửa kênh": SemanticEntry("edit_channel"),
    "chỉnh kênh": SemanticEntry("edit_channel"),
    "di chuyển kênh": SemanticEntry("move_channel"),
    "khóa kênh": SemanticEntry("lock_channel"),
    "mở khóa kênh": SemanticEntry("unlock_channel"),
    # ---- Category ----
    "tạo danh mục": SemanticEntry("create_category"),
    "tạo category": SemanticEntry("create_category"),
    "thêm danh mục": SemanticEntry("create_category"),
    "xóa danh mục": SemanticEntry("delete_category"),
    "xóa category": SemanticEntry("delete_category"),
    "đổi tên danh mục": SemanticEntry("rename_category"),
    # ---- Role ----
    "tạo role": SemanticEntry("create_role"),
    "thêm role": SemanticEntry("create_role"),
    "xóa role": SemanticEntry("delete_role"),
    "bỏ role": SemanticEntry("delete_role"),
    "gán role": SemanticEntry("assign_role"),
    "cấp role": SemanticEntry("assign_role"),
    "gỡ role": SemanticEntry("remove_role"),
    "đổi tên role": SemanticEntry("rename_role"),
    "sửa role": SemanticEntry("edit_role"),
    # ---- Permissions ----
    "cấp quyền": SemanticEntry("set_permission"),
    "phân quyền": SemanticEntry("set_permission"),
    "thiết lập quyền": SemanticEntry("set_permission"),
    "chỉnh quyền": SemanticEntry("set_permission"),
    # ---- Members ----
    "kick": SemanticEntry("kick_member"),
    "đá": SemanticEntry("kick_member"),
    "mời ra": SemanticEntry("kick_member"),
    "ban": SemanticEntry("ban_member"),
    "cấm": SemanticEntry("ban_member"),
    "unban": SemanticEntry("unban_member"),
    "bỏ cấm": SemanticEntry("unban_member"),
    "mute": SemanticEntry("timeout_member"),
    "im lặng": SemanticEntry("timeout_member"),
    "timeout": SemanticEntry("timeout_member"),
    # ---- Query ----
    "xem kênh": SemanticEntry("list_channels"),
    "liệt kê kênh": SemanticEntry("list_channels"),
    "danh sách kênh": SemanticEntry("list_channels"),
    "xem role": SemanticEntry("list_roles"),
    "liệt kê role": SemanticEntry("list_roles"),
    "danh sách role": SemanticEntry("list_roles"),
    "danh sách thành viên": SemanticEntry("list_members"),
    "xem thành viên": SemanticEntry("list_members"),
    # ---- Server features ----
    "webhook": SemanticEntry("create_webhook"),
    "tạo webhook": SemanticEntry("create_webhook"),
    "emoji": SemanticEntry("add_emoji"),
    "thêm emoji": SemanticEntry("add_emoji"),
    "automod": SemanticEntry("create_automod_rule"),
    "chống spam": SemanticEntry("create_automod_rule", {"trigger": "spam"}),
    "chống từ xấu": SemanticEntry("create_automod_rule", {"trigger": "keyword"}),
    # ---- English terms ----
    "create channel": SemanticEntry("create_channel"),
    "add channel": SemanticEntry("create_channel"),
    "text channel": SemanticEntry("create_channel", {"type": "text"}),
    "voice channel": SemanticEntry("create_channel", {"type": "voice"}),
    "delete channel": SemanticEntry("delete_channel"),
    "remove channel": SemanticEntry("delete_channel"),
    "rename channel": SemanticEntry("rename_channel"),
    "move channel": SemanticEntry("move_channel"),
    "lock channel": SemanticEntry("lock_channel"),
    "unlock channel": SemanticEntry("unlock_channel"),
    "create category": SemanticEntry("create_category"),
    "delete category": SemanticEntry("delete_category"),
    "create role": SemanticEntry("create_role"),
    "add role": SemanticEntry("create_role"),
    "delete role": SemanticEntry("delete_role"),
    "assign role": SemanticEntry("assign_role"),
    "remove role": SemanticEntry("remove_role"),
    "set permission": SemanticEntry("set_permission"),
    "set permissions": SemanticEntry("set_permission"),
    "kick member": SemanticEntry("kick_member"),
    "ban member": SemanticEntry("ban_member"),
    "unban member": SemanticEntry("unban_member"),
    "mute member": SemanticEntry("timeout_member"),
    "list channels": SemanticEntry("list_channels"),
    "list roles": SemanticEntry("list_roles"),
    "list members": SemanticEntry("list_members"),
    "create webhook": SemanticEntry("create_webhook"),
    "add emoji": SemanticEntry("add_emoji"),
    "setup automod": SemanticEntry("create_automod_rule"),
}


# ---------------------------------------------------------------------------
# Archetype Map
# ---------------------------------------------------------------------------

ARCHETYPE_MAP: dict[str, ArchetypeConfig] = {
    "gaming_casual": ArchetypeConfig(
        name="gaming_casual",
        tone="casual",
        vocabulary_tags=["game", "play", "squad", "gg", "gaming", "gamer"],
        suggestion_style="energetic",
    ),
    "gaming_community": ArchetypeConfig(
        name="gaming_community",
        tone="casual",
        vocabulary_tags=["community", "event", "tournament", "esport"],
        suggestion_style="warm",
    ),
    "study_group": ArchetypeConfig(
        name="study_group",
        tone="structured",
        vocabulary_tags=["study", "class", "lecture", "homework", "học", "lớp"],
        suggestion_style="calm",
    ),
    "work_team": ArchetypeConfig(
        name="work_team",
        tone="formal",
        vocabulary_tags=["meeting", "project", "team", "task", "sprint", "họp"],
        suggestion_style="precise",
    ),
}


# ---------------------------------------------------------------------------
# Goal statement keywords
# ---------------------------------------------------------------------------

_GOAL_KEYWORDS_VI = [
    "tôi muốn", "mình muốn", "tôi cần", "mình cần",
    "setup server", "xây dựng server", "tổ chức server",
    "mục tiêu", "kế hoạch", "thiết kế server",
    "tôi đang muốn", "mình đang muốn",
]
_GOAL_KEYWORDS_EN = [
    "i want to", "i need to", "i'd like to",
    "setup server", "build server", "organize server",
    "goal is", "plan to", "i'm looking to",
]

_DIAGNOSTIC_KEYWORDS = [
    # Vietnamese
    "lỗi", "bị lỗi", "không hoạt động", "không được", "không thấy",
    "sai rồi", "có vấn đề", "bị sao", "hỏng", "không chạy",
    "vẫn không", "thử rồi", "không fix được",
    # English
    "error", "broken", "not working", "doesn't work", "can't",
    "issue", "problem", "bug", "failed", "wrong",
]


# ---------------------------------------------------------------------------
# Public functions
# ---------------------------------------------------------------------------

def expand_message(text: str) -> tuple[str, list[str]]:
    """Pre-process message: inject canonical context hints for the LLM.

    Searches SEMANTIC_MAP for matching keywords in the text (case-insensitive).
    If matches found, prepends a compact context hint to the original text.

    Returns:
        (expanded_text, matched_terms): expanded_text is idempotent —
        applying expand_message twice gives the same result.

    Idempotent guarantee: the injected prefix starts with a sentinel marker
    "[ctx:" that is detected on re-entry to skip re-injection.
    """
    text_stripped = text.strip()

    # Idempotency: skip if already expanded
    if text_stripped.startswith("[ctx:"):
        return text_stripped, []

    text_lower = text_stripped.lower()
    matched: dict[str, SemanticEntry] = {}

    for keyword, entry in SEMANTIC_MAP.items():
        if keyword in text_lower:
            matched[keyword] = entry

    if not matched:
        return text_stripped, []

    # Build compact context hint
    actions = list({e.canonical_action for e in matched.values()})
    hint = "[ctx: " + ", ".join(actions) + "]"
    expanded = f"{hint} {text_stripped}"
    return expanded, list(matched.keys())


def detect_goal_statement(text: str) -> bool:
    """Heuristic: detect if user is stating a high-level goal rather than a command."""
    text_lower = text.lower()
    return any(kw in text_lower for kw in _GOAL_KEYWORDS_VI + _GOAL_KEYWORDS_EN)


def detect_diagnostic_request(text: str) -> bool:
    """Heuristic: detect if user is reporting an error or problem."""
    text_lower = text.lower()
    return any(kw in text_lower for kw in _DIAGNOSTIC_KEYWORDS)


def reload_semantic_map() -> None:
    """Hot-reload SEMANTIC_MAP from the module file without service restart."""
    import app.data.semantic_map as _self
    try:
        importlib.reload(_self)
        logger.info("[SemanticMap] hot-reload successful — %d entries", len(_self.SEMANTIC_MAP))
    except Exception as e:
        logger.error("[SemanticMap] hot-reload failed: %s — keeping current map", e)

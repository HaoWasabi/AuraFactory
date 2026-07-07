"""Tests for bilingual approval messages (tasks 11.3 and 11.4)."""
import pytest
import uuid
from unittest.mock import AsyncMock, MagicMock
from hypothesis import given, settings
from hypothesis import strategies as st

from app.messages import msg, MESSAGES
from app.services.approval_service import ApprovalService


# --- Task 11.4: Unit tests for message keys ---

def test_all_new_message_keys_exist():
    """MESSAGES dict must contain all 4 new approval error keys with vi and en."""
    required_keys = [
        "plan_not_found",
        "plan_not_pending",
        "only_creator_can_approve",
        "only_creator_can_reject",
    ]
    for key in required_keys:
        assert key in MESSAGES, f"Missing key: {key}"
        assert "vi" in MESSAGES[key], f"Missing 'vi' for key: {key}"
        assert "en" in MESSAGES[key], f"Missing 'en' for key: {key}"
        assert MESSAGES[key]["vi"], f"Empty 'vi' value for key: {key}"
        assert MESSAGES[key]["en"], f"Empty 'en' value for key: {key}"


@pytest.mark.asyncio
async def test_approve_plan_not_found_returns_bilingual_error():
    """approve_plan() with non-existent plan_id → error matches msg('plan_not_found', lang=lang)."""
    db = MagicMock()
    # transaction context manager returns conn that returns None on fetchrow
    conn = MagicMock()
    conn.fetchrow = AsyncMock(return_value=None)
    conn.execute = AsyncMock()
    tx_cm = MagicMock()
    tx_cm.__aenter__ = AsyncMock(return_value=conn)
    tx_cm.__aexit__ = AsyncMock(return_value=False)
    db.transaction = MagicMock(return_value=tx_cm)

    service = ApprovalService(db)
    plan_id = str(uuid.uuid4())

    for lang in ("vi", "en"):
        result = await service.approve_plan(plan_id, 999, lang=lang)
        assert result["ok"] is False
        assert result["error"] == msg("plan_not_found", lang=lang), \
            f"lang={lang}: expected '{msg('plan_not_found', lang=lang)}', got '{result['error']}'"


@pytest.mark.asyncio
async def test_approve_plan_not_pending_returns_bilingual_error():
    """approve_plan() with plan in wrong status → error matches msg('plan_not_pending', ...)."""
    db = MagicMock()
    import uuid as _uuid
    plan_uuid = _uuid.uuid4()
    plan_record = MagicMock()
    plan_record.__getitem__ = MagicMock(side_effect=lambda k: {
        "id": plan_uuid,
        "request_id": _uuid.uuid4(),
        "user_id": 123,
        "status": "completed",
    }[k])
    conn = MagicMock()
    conn.fetchrow = AsyncMock(return_value=plan_record)
    conn.execute = AsyncMock()
    tx_cm = MagicMock()
    tx_cm.__aenter__ = AsyncMock(return_value=conn)
    tx_cm.__aexit__ = AsyncMock(return_value=False)
    db.transaction = MagicMock(return_value=tx_cm)

    service = ApprovalService(db)

    for lang in ("vi", "en"):
        result = await service.approve_plan(str(plan_uuid), 123, lang=lang)
        assert result["ok"] is False
        expected = msg("plan_not_pending", lang=lang, status="completed")
        assert result["error"] == expected, f"lang={lang}: expected '{expected}', got '{result['error']}'"


# --- Task 11.3: Property 7 — bilingual approval messages ---
# Feature: optimization, Property 7: Bilingual approval messages
# Validates: Requirements 1.2

@given(lang=st.sampled_from(["vi", "en"]))
@settings(max_examples=20)
def test_approval_error_messages_match_msg_system(lang: str):
    """Property 7: For any lang in {vi, en}, approval errors match msg(key, lang=lang)."""
    error_keys = [
        "plan_not_found",
        "plan_not_pending",
        "only_creator_can_approve",
        "only_creator_can_reject",
    ]
    for key in error_keys:
        result = msg(key, lang=lang)
        # Must be a non-empty string in the correct language
        assert isinstance(result, str), f"msg({key!r}, lang={lang!r}) must be str"
        assert len(result) > 0, f"msg({key!r}, lang={lang!r}) must not be empty"
        # Must NOT be a fallback key placeholder
        assert not result.startswith("["), f"msg({key!r}, lang={lang!r}) returned placeholder: {result}"

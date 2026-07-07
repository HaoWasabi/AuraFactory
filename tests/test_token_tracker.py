"""Tests for record_token_usage — property test and edge cases.

Feature: optimization
Property 6: Token usage recording
Validates: Requirements 5.1, 5.2, 5.3, 5.4, 5.5
"""
import asyncio
import logging
import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from app.services._token_tracker import record_token_usage


# ---- Helpers ----

def make_usage(prompt_tokens: int, completion_tokens: int):
    usage = MagicMock()
    usage.prompt_tokens = prompt_tokens
    usage.completion_tokens = completion_tokens
    return usage


def make_db(side_effect=None):
    db = MagicMock()
    db.execute = AsyncMock(return_value="UPDATE 1", side_effect=side_effect)
    return db


# ---- Property Test (Task 8.5) ----
# Feature: optimization, Property 6: Token usage recording

@given(
    prompt_tokens=st.integers(min_value=1, max_value=100_000),
    completion_tokens=st.integers(min_value=1, max_value=100_000),
)
@settings(max_examples=100)
def test_token_usage_recorded_correctly(prompt_tokens, completion_tokens):
    """Property 6: For any non-zero token counts, DB is updated with correct values.

    Validates: Requirements 5.1, 5.2, 5.3
    """
    db = make_db()
    request_id = str(uuid.uuid4())
    usage = make_usage(prompt_tokens, completion_tokens)

    asyncio.run(record_token_usage(db, request_id, usage, "test-provider"))

    db.execute.assert_called_once()
    call_args = db.execute.call_args
    # Positional args: query, uuid, tokens_in, tokens_out, provider
    assert call_args.args[1] == uuid.UUID(request_id)
    assert call_args.args[2] == prompt_tokens
    assert call_args.args[3] == completion_tokens
    assert call_args.args[4] == "test-provider"


# ---- Edge Case Tests (Task 8.6) ----

@pytest.mark.asyncio
async def test_skips_when_usage_is_none():
    """usage=None → no DB call.

    Validates: Requirements 5.4
    """
    db = make_db()
    await record_token_usage(db, str(uuid.uuid4()), None, "gemini")
    db.execute.assert_not_called()


@pytest.mark.asyncio
async def test_skips_when_request_id_is_none():
    """request_id=None → no DB call.

    Validates: Requirements 5.4
    """
    db = make_db()
    usage = make_usage(10, 5)
    await record_token_usage(db, None, usage, "gemini")
    db.execute.assert_not_called()


@pytest.mark.asyncio
async def test_skips_when_both_tokens_are_zero():
    """usage with both counts=0 → no DB call.

    Validates: Requirements 5.4
    """
    db = make_db()
    usage = make_usage(0, 0)
    await record_token_usage(db, str(uuid.uuid4()), usage, "gemini")
    db.execute.assert_not_called()


@pytest.mark.asyncio
async def test_db_error_logs_warning_does_not_raise(caplog):
    """DB error → warning logged, no exception propagated.

    Validates: Requirements 5.5
    """
    db = make_db(side_effect=Exception("connection lost"))
    usage = make_usage(100, 50)
    request_id = str(uuid.uuid4())

    with caplog.at_level(logging.WARNING, logger="app.services._token_tracker"):
        # Must not raise
        await record_token_usage(db, request_id, usage, "gemini")

    assert any("Failed to update token usage" in r.message for r in caplog.records)

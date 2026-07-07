"""Tests for DiscordBot UI: message truncation (12.2) and ApprovalView resilience (13.3)."""
import pytest
from unittest.mock import AsyncMock, MagicMock
from hypothesis import given, settings
from hypothesis import strategies as st


# ---- Helpers ----

def make_plan(n_steps: int, step_description: str = "A" * 80) -> dict:
    """Build a plan dict with n_steps steps."""
    return {
        "description": "Test plan",
        "steps": [
            {"description": step_description, "risk_level": "LOW"}
            for _ in range(n_steps)
        ],
    }


def make_bot_stub():
    """Create a minimal DiscordBot-like object with _format_plan method."""
    from app.interfaces.discord_bot import DiscordBot
    # We only need _format_plan and MAX_PLAN_CHARS, not the full bot
    bot = object.__new__(DiscordBot)
    return bot


# ---- Task 12.2: Property 8 — truncation invariant ----
# Feature: optimization, Property 8: Message truncation invariant
# Validates: Requirements 1.2

@given(n_steps=st.integers(min_value=1, max_value=100))
@settings(max_examples=100, deadline=None)
def test_format_plan_never_exceeds_1800_chars(n_steps: int):
    """Property 8: _format_plan() always returns <= 1800 chars for any number of steps."""
    bot = make_bot_stub()
    plan = make_plan(n_steps)
    result = bot._format_plan(plan, lang="vi")
    assert len(result) <= 1800, (
        f"_format_plan with {n_steps} steps returned {len(result)} chars (>1800)"
    )


def test_format_plan_short_plan_not_truncated():
    """Plans with few short steps are returned intact."""
    bot = make_bot_stub()
    plan = make_plan(3, step_description="Short step")
    result = bot._format_plan(plan, lang="vi")
    assert "Short step" in result
    assert len(result) <= 1800


def test_format_plan_truncation_adds_suffix_vi():
    """Vietnamese truncation suffix is added when plan is too long."""
    bot = make_bot_stub()
    plan = make_plan(50, step_description="A" * 100)  # Will definitely overflow
    result = bot._format_plan(plan, lang="vi")
    assert "bước khác" in result
    assert len(result) <= 1800


def test_format_plan_truncation_adds_suffix_en():
    """English truncation suffix is added when plan is too long."""
    bot = make_bot_stub()
    plan = make_plan(50, step_description="A" * 100)
    result = bot._format_plan(plan, lang="en")
    assert "more steps" in result
    assert len(result) <= 1800


# ---- Task 13.3: ApprovalView resilience ----

@pytest.mark.asyncio
async def test_on_timeout_disables_all_buttons():
    """on_timeout() must set disabled=True on all button children."""
    from app.interfaces.discord_bot import ApprovalView

    # Build a minimal ApprovalView without a real bot
    view = object.__new__(ApprovalView)
    view.bot = MagicMock()
    view.plan_id = "test-plan-id"
    view.user_id = 12345
    view.lang = "vi"
    view.message = None

    # Add fake button children
    btn1 = MagicMock()
    btn1.disabled = False
    btn2 = MagicMock()
    btn2.disabled = False
    view.children = [btn1, btn2]

    await view.on_timeout()

    assert btn1.disabled is True
    assert btn2.disabled is True


@pytest.mark.asyncio
async def test_on_timeout_edits_message_when_available():
    """on_timeout() tries to edit the original message with '(Expired)' text."""
    from app.interfaces.discord_bot import ApprovalView

    view = object.__new__(ApprovalView)
    view.plan_id = "test"
    view.user_id = 1
    view.lang = "vi"
    view.children = []

    mock_msg = MagicMock()
    mock_msg.content = "Original plan text"
    mock_msg.edit = AsyncMock()
    view.message = mock_msg

    await view.on_timeout()

    mock_msg.edit.assert_called_once()
    call_kwargs = mock_msg.edit.call_args.kwargs
    assert "Expired" in call_kwargs.get("content", "")


@pytest.mark.asyncio
async def test_on_timeout_handles_edit_failure_gracefully():
    """on_timeout() must not raise even if message.edit() throws an exception."""
    from app.interfaces.discord_bot import ApprovalView

    view = object.__new__(ApprovalView)
    view.plan_id = "test"
    view.user_id = 1
    view.lang = "vi"
    view.children = []

    mock_msg = MagicMock()
    mock_msg.content = "Original"
    mock_msg.edit = AsyncMock(side_effect=Exception("Discord API error"))
    view.message = mock_msg

    # Must not raise — exception from edit() should be swallowed
    await view.on_timeout()

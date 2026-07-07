"""Tests for RateLimitService — rate limiting enforcement (§Req 2)."""
import logging
import pytest
from unittest.mock import AsyncMock, MagicMock

from hypothesis import given, settings
from hypothesis import strategies as st

from app.services.rate_limit_service import RateLimitService


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_mock_db(request_count: int) -> MagicMock:
    """Return a mock Database whose fetchrow() simulates a DB upsert result
    with the given request_count value."""
    record = MagicMock()
    record.__getitem__ = MagicMock(
        side_effect=lambda k: request_count if k == "request_count" else None
    )
    db = MagicMock()
    db.fetchrow = AsyncMock(return_value=record)
    return db


# ---------------------------------------------------------------------------
# Task 4.4 — Property test
# Feature: optimization, Property 1: Rate limit enforcement
# Validates: Requirements 2.1, 2.2
# ---------------------------------------------------------------------------

# Feature: optimization, Property 1: Rate limit enforcement
@given(
    user_id=st.integers(min_value=1, max_value=10**15),
    guild_id=st.integers(min_value=1, max_value=10**15),
)
@settings(max_examples=100)
def test_rate_limit_enforcement_property(user_id: int, guild_id: int):
    """Property 1: For any user_id and guild_id, requests 1-10 are allowed and
    request 11 (count > LIMIT) is denied.

    Validates: Requirements 2.1, 2.2
    """
    import asyncio

    async def run_all() -> None:
        # Requests 1 through LIMIT (count 1..10) must all be allowed
        for count in range(1, RateLimitService.LIMIT + 1):
            db = make_mock_db(count)
            service = RateLimitService(db)
            result = await service.check_and_increment(user_id, guild_id)
            assert result is True, (
                f"Expected allowed for count={count} (user={user_id}, guild={guild_id})"
            )

        # Request at count = LIMIT + 1 (11) must be denied
        over_limit_count = RateLimitService.LIMIT + 1
        db = make_mock_db(over_limit_count)
        service = RateLimitService(db)
        result = await service.check_and_increment(user_id, guild_id)
        assert result is False, (
            f"Expected denied for count={over_limit_count} (user={user_id}, guild={guild_id})"
        )

    asyncio.run(run_all())


# ---------------------------------------------------------------------------
# Task 4.5 — Edge case tests
# Validates: Requirements 2.2, 2.5
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_rate_limit_boundary():
    """count=10 (exactly at limit) → allowed; count=11 → denied."""
    service_at_limit = RateLimitService(make_mock_db(RateLimitService.LIMIT))
    assert await service_at_limit.check_and_increment(111, 222) is True

    service_over_limit = RateLimitService(make_mock_db(RateLimitService.LIMIT + 1))
    assert await service_over_limit.check_and_increment(111, 222) is False


@pytest.mark.asyncio
async def test_rate_limit_db_error_fail_open(caplog):
    """DB raises an exception → request is allowed (fail open) and warning is logged."""
    db = MagicMock()
    db.fetchrow = AsyncMock(side_effect=Exception("connection refused"))

    service = RateLimitService(db)

    with caplog.at_level(logging.WARNING, logger="app.services.rate_limit_service"):
        result = await service.check_and_increment(999, 888)

    assert result is True, "Fail-open: DB error must allow the request through"
    assert any("Rate limit check failed" in record.message for record in caplog.records), (
        "A WARNING must be logged when the DB raises an exception"
    )

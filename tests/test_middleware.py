"""Tests for middleware pipeline — circuit breaker, rate limiting, metrics."""

import pytest
import asyncio
from unittest.mock import AsyncMock

from app.core.middleware import (
    ExecutionContext,
    ExecutionResult,
    CircuitBreakerMiddleware,
    RateLimitMiddleware,
    RetryMiddleware,
    ErrorBoundaryMiddleware,
)


class TestCircuitBreaker:
    """Test circuit breaker state transitions."""

    @pytest.mark.asyncio
    async def test_stays_closed_on_success(self):
        cb = CircuitBreakerMiddleware(failure_threshold=3, cooldown_seconds=1.0)
        ctx = ExecutionContext(tool_name="test", params={}, guild_id=1, user_id=1)

        success_fn = AsyncMock(return_value=ExecutionResult(success=True, data={}))
        result = await cb(ctx, success_fn)
        assert result.success
        assert cb.state == "closed"

    @pytest.mark.asyncio
    async def test_opens_after_threshold(self):
        cb = CircuitBreakerMiddleware(failure_threshold=3, cooldown_seconds=1.0)
        ctx = ExecutionContext(tool_name="test", params={}, guild_id=1, user_id=1)

        fail_fn = AsyncMock(return_value=ExecutionResult(success=False, error="fail"))
        for _ in range(3):
            await cb(ctx, fail_fn)
        assert cb.state == "open"

    @pytest.mark.asyncio
    async def test_rejects_when_open(self):
        cb = CircuitBreakerMiddleware(failure_threshold=1, cooldown_seconds=10.0)
        ctx = ExecutionContext(tool_name="test", params={}, guild_id=1, user_id=1)

        fail_fn = AsyncMock(return_value=ExecutionResult(success=False, error="fail"))
        await cb(ctx, fail_fn)  # Opens circuit

        # Next call should be rejected immediately
        never_called = AsyncMock()
        result = await cb(ctx, never_called)
        assert not result.success
        assert "Circuit breaker OPEN" in result.error
        never_called.assert_not_called()

    @pytest.mark.asyncio
    async def test_half_open_after_cooldown(self):
        cb = CircuitBreakerMiddleware(failure_threshold=1, cooldown_seconds=0.1)
        ctx = ExecutionContext(tool_name="test", params={}, guild_id=1, user_id=1)

        fail_fn = AsyncMock(return_value=ExecutionResult(success=False, error="fail"))
        await cb(ctx, fail_fn)  # Opens
        assert cb.state == "open"

        await asyncio.sleep(0.15)  # Wait for cooldown

        success_fn = AsyncMock(return_value=ExecutionResult(success=True, data={}))
        result = await cb(ctx, success_fn)
        assert result.success
        assert cb.state == "closed"


class TestRateLimiter:
    """Test rate limiting middleware."""

    @pytest.mark.asyncio
    async def test_allows_burst(self):
        rl = RateLimitMiddleware(min_delay=0.1, burst_limit=3)
        ctx = ExecutionContext(tool_name="test", params={}, guild_id=1, user_id=1)
        success_fn = AsyncMock(return_value=ExecutionResult(success=True, data={}))

        # First 3 should pass immediately
        for _ in range(3):
            result = await rl(ctx, success_fn)
            assert result.success


class TestRetryMiddleware:
    """Test retry with exponential backoff."""

    @pytest.mark.asyncio
    async def test_no_retry_on_success(self):
        retry = RetryMiddleware(max_retries=3, base_delay=0.01)
        ctx = ExecutionContext(tool_name="test", params={}, guild_id=1, user_id=1)

        fn = AsyncMock(return_value=ExecutionResult(success=True, data={}))
        result = await retry(ctx, fn)
        assert result.success
        assert fn.call_count == 1

    @pytest.mark.asyncio
    async def test_retries_on_transient(self):
        retry = RetryMiddleware(max_retries=2, base_delay=0.01)
        ctx = ExecutionContext(tool_name="test", params={}, guild_id=1, user_id=1)

        # Fail twice, then succeed
        fn = AsyncMock(side_effect=[
            ExecutionResult(success=False, error="timeout", should_retry=True),
            ExecutionResult(success=False, error="timeout", should_retry=True),
            ExecutionResult(success=True, data={"ok": True}),
        ])
        result = await retry(ctx, fn)
        assert result.success
        assert fn.call_count == 3

    @pytest.mark.asyncio
    async def test_no_retry_on_permanent(self):
        retry = RetryMiddleware(max_retries=3, base_delay=0.01)
        ctx = ExecutionContext(tool_name="test", params={}, guild_id=1, user_id=1)

        fn = AsyncMock(return_value=ExecutionResult(success=False, error="403 forbidden", should_retry=False))
        result = await retry(ctx, fn)
        assert not result.success
        assert fn.call_count == 1


class TestErrorBoundary:
    """Test error boundary catches all exceptions."""

    @pytest.mark.asyncio
    async def test_catches_permission_error(self):
        eb = ErrorBoundaryMiddleware()
        ctx = ExecutionContext(tool_name="test", params={}, guild_id=1, user_id=1)

        fn = AsyncMock(side_effect=PermissionError("Not allowed"))
        result = await eb(ctx, fn)
        assert not result.success
        assert not result.should_retry
        assert "Not allowed" in result.error

    @pytest.mark.asyncio
    async def test_catches_unexpected(self):
        eb = ErrorBoundaryMiddleware()
        ctx = ExecutionContext(tool_name="test", params={}, guild_id=1, user_id=1)

        fn = AsyncMock(side_effect=RuntimeError("Something unexpected"))
        result = await eb(ctx, fn)
        assert not result.success

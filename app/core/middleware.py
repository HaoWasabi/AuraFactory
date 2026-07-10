"""Execution Middleware Pipeline — composable chain for tool execution.

Each middleware handles ONE concern. Chain order determines behavior.
Adding new concerns (metrics, circuit breaker, caching) = add 1 class.

Design: inspired by Express.js/Koa middleware, adapted for async Python.
"""

from __future__ import annotations

import asyncio
import logging
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Callable, Coroutine, Dict, List, Optional

logger = logging.getLogger(__name__)


# ===========================================================================
# Core Types
# ===========================================================================

@dataclass
class ExecutionContext:
    """All information needed for a single tool execution.

    This object flows through the middleware chain. Each middleware
    can read/modify it before passing to the next.
    """
    tool_name: str            # MCP tool name (e.g. "discord.channels.create")
    params: Dict[str, Any]    # Tool parameters
    guild_id: int
    user_id: int
    risk_level: str = "medium"
    attempt: int = 0          # Current retry attempt (set by RetryMiddleware)
    request_id: str = ""      # Linked request lifecycle ID
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ExecutionResult:
    """Result of a tool execution flowing back through the chain.

    Each middleware can inspect/modify this on the way back up.
    """
    success: bool
    data: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    should_retry: bool = False
    duration_ms: float = 0.0
    metadata: Dict[str, Any] = field(default_factory=dict)


# Type alias for the next function in the chain
NextFn = Callable[[ExecutionContext], Coroutine[Any, Any, ExecutionResult]]


# ===========================================================================
# Base Middleware
# ===========================================================================

class Middleware(ABC):
    """Abstract middleware — implement __call__ to handle one concern.

    Pattern:
        async def __call__(self, ctx, next_fn):
            # Pre-processing (before execution)
            ...
            result = await next_fn(ctx)  # Pass to next middleware
            # Post-processing (after execution)
            ...
            return result
    """

    @abstractmethod
    async def __call__(self, ctx: ExecutionContext, next_fn: NextFn) -> ExecutionResult:
        ...


# ===========================================================================
# Middleware Implementations
# ===========================================================================

class ErrorBoundaryMiddleware(Middleware):
    """Outermost layer — catches ALL exceptions. Nothing ever leaks.

    Classifies errors as:
      - Transient (should_retry=True): rate limit, 5xx, connection errors
      - Permanent (should_retry=False): 403, 404, validation errors
    """

    _TRANSIENT_SIGNALS = ("429", "rate limit", "5xx", "timeout", "connection", "unavailable")
    _PERMANENT_SIGNALS = ("403", "forbidden", "404", "not found", "400", "bad request", "invalid", "cannot")

    async def __call__(self, ctx: ExecutionContext, next_fn: NextFn) -> ExecutionResult:
        try:
            return await next_fn(ctx)
        except PermissionError as e:
            return ExecutionResult(
                success=False,
                error=str(e),
                should_retry=False,
                metadata={"error_type": "permission"},
            )
        except ValueError as e:
            return ExecutionResult(
                success=False,
                error=str(e),
                should_retry=False,
                metadata={"error_type": "validation"},
            )
        except Exception as e:
            error_str = str(e).lower()
            is_transient = any(sig in error_str for sig in self._TRANSIENT_SIGNALS)
            is_permanent = any(sig in error_str for sig in self._PERMANENT_SIGNALS)

            # If matches permanent → don't retry. Otherwise if transient → retry.
            should_retry = is_transient and not is_permanent

            logger.warning(
                "ErrorBoundary caught %s for %s: %s (retry=%s)",
                type(e).__name__, ctx.tool_name, str(e)[:100], should_retry,
            )
            return ExecutionResult(
                success=False,
                error=str(e),
                should_retry=should_retry,
                metadata={"error_type": type(e).__name__, "transient": is_transient},
            )


class RateLimitMiddleware(Middleware):
    """Throttle execution to prevent hitting Discord API limits.

    Strategy: token bucket — burst allowed, then enforced delay.
    """

    def __init__(self, min_delay: float = 0.5, burst_limit: int = 5) -> None:
        self._min_delay = min_delay
        self._burst_limit = burst_limit
        self._call_times: List[float] = []
        self._lock = asyncio.Lock()

    async def __call__(self, ctx: ExecutionContext, next_fn: NextFn) -> ExecutionResult:
        async with self._lock:
            now = time.time()
            # Clean timestamps older than 10s
            self._call_times = [t for t in self._call_times if now - t < 10]

            if len(self._call_times) >= self._burst_limit:
                elapsed = now - self._call_times[-1] if self._call_times else self._min_delay
                if elapsed < self._min_delay:
                    wait = self._min_delay - elapsed
                    await asyncio.sleep(wait)

            self._call_times.append(time.time())

        return await next_fn(ctx)


class RetryMiddleware(Middleware):
    """Exponential backoff retry for transient failures.

    Only retries if inner result has should_retry=True.
    """

    def __init__(self, max_retries: int = 3, base_delay: float = 1.0, max_delay: float = 10.0) -> None:
        self._max_retries = max_retries
        self._base_delay = base_delay
        self._max_delay = max_delay

    async def __call__(self, ctx: ExecutionContext, next_fn: NextFn) -> ExecutionResult:
        last_result: Optional[ExecutionResult] = None

        for attempt in range(self._max_retries + 1):
            ctx.attempt = attempt
            result = await next_fn(ctx)

            if result.success or not result.should_retry:
                return result

            last_result = result

            # Don't wait after last attempt
            if attempt < self._max_retries:
                delay = min(self._base_delay * (2 ** attempt), self._max_delay)
                logger.info(
                    "Retry %d/%d for %s after %.1fs (error: %s)",
                    attempt + 1, self._max_retries, ctx.tool_name, delay,
                    (result.error or "")[:80],
                )
                await asyncio.sleep(delay)

        # All retries exhausted
        if last_result:
            last_result.metadata["retries_exhausted"] = True
        return last_result or ExecutionResult(success=False, error="All retries exhausted")


class AuditMiddleware(Middleware):
    """Log every execution (success and failure) for accountability."""

    def __init__(self, audit_logger) -> None:
        self._audit = audit_logger

    async def __call__(self, ctx: ExecutionContext, next_fn: NextFn) -> ExecutionResult:
        start = time.time()
        result = await next_fn(ctx)
        result.duration_ms = (time.time() - start) * 1000

        # Log asynchronously (don't block the response)
        try:
            await self._audit.log_execution(
                guild_id=ctx.guild_id,
                user_id=ctx.user_id,
                tool_name=ctx.tool_name,
                kwargs=ctx.params,
                result=result.data or {"error": result.error},
                risk_level=ctx.risk_level,
                duration_ms=result.duration_ms,
            )
        except Exception as e:
            # Audit failure should NEVER break execution
            logger.warning("Audit logging failed (non-fatal): %s", e)

        return result


class MemoryMiddleware(Middleware):
    """Record successful executions to conversation memory."""

    def __init__(self, memory) -> None:
        self._memory = memory

    async def __call__(self, ctx: ExecutionContext, next_fn: NextFn) -> ExecutionResult:
        result = await next_fn(ctx)

        if result.success and result.data:
            self._record(ctx, result)

        return result

    def _record(self, ctx: ExecutionContext, result: ExecutionResult) -> None:
        """Extract resource info and record."""
        data = result.data or {}
        module = ctx.tool_name.split(".")[1] if "." in ctx.tool_name else ""
        action_part = ctx.tool_name.split(".")[-1] if "." in ctx.tool_name else ""

        type_map = {
            "channels": "channel", "categories": "category",
            "roles": "role", "members": "member",
            "webhooks": "webhook", "threads": "thread",
        }
        action_map = {
            "create": "created", "edit": "edited", "modify": "edited",
            "delete": "deleted", "assign": "assigned", "remove": "removed",
        }

        resource_type = type_map.get(module, module)
        action = action_map.get(action_part, action_part)
        res_id = str(data.get("id", data.get("channel_id", data.get("role_id", ""))))
        res_name = data.get("name", data.get("channel_name", data.get("role_name", "")))

        if res_id or res_name:
            self._memory.record(ctx.guild_id, resource_type, res_id, res_name, action)


class TimingMiddleware(Middleware):
    """Track execution duration (set on result.duration_ms)."""

    async def __call__(self, ctx: ExecutionContext, next_fn: NextFn) -> ExecutionResult:
        start = time.time()
        result = await next_fn(ctx)
        result.duration_ms = (time.time() - start) * 1000
        return result


# ===========================================================================
# Pipeline Composer
# ===========================================================================

class ExecutionPipeline:
    """Compose middlewares into a chain and execute.

    Usage:
        pipeline = ExecutionPipeline(
            middlewares=[ErrorBoundary(), RateLimit(), Retry(), Audit(), Memory()],
            executor=mcp_execute_fn,
        )
        result = await pipeline.execute(ctx)

    The executor is the innermost function — the actual MCP/connector call.
    """

    def __init__(
        self,
        middlewares: List[Middleware],
        executor: Callable[[ExecutionContext], Coroutine[Any, Any, ExecutionResult]],
    ) -> None:
        self._middlewares = middlewares
        self._executor = executor

    async def execute(self, ctx: ExecutionContext) -> ExecutionResult:
        """Run the full middleware chain."""
        return await self._build_chain(0, ctx)

    async def _build_chain(self, index: int, ctx: ExecutionContext) -> ExecutionResult:
        """Recursively build the middleware chain."""
        if index >= len(self._middlewares):
            # End of chain → call the actual executor
            return await self._executor(ctx)

        middleware = self._middlewares[index]
        next_fn: NextFn = lambda c: self._build_chain(index + 1, c)
        return await middleware(ctx, next_fn)

    @property
    def middleware_count(self) -> int:
        return len(self._middlewares)


class CircuitBreakerMiddleware(Middleware):
    """Prevent retry storms when Discord API is consistently failing.

    States:
      - CLOSED: normal operation, failures counted
      - OPEN: all calls fail-fast (no execution), cooldown timer
      - HALF_OPEN: allow 1 probe call, if success → CLOSED, if fail → OPEN

    Thresholds configurable. Prevents wasting LLM calls on doomed executions.
    """

    def __init__(self, failure_threshold: int = 5, cooldown_seconds: float = 30.0) -> None:
        self._failure_threshold = failure_threshold
        self._cooldown = cooldown_seconds
        self._failure_count = 0
        self._state = "closed"  # closed | open | half_open
        self._opened_at: float = 0.0

    async def __call__(self, ctx: ExecutionContext, next_fn: NextFn) -> ExecutionResult:
        # Check circuit state
        if self._state == "open":
            elapsed = time.time() - self._opened_at
            if elapsed >= self._cooldown:
                self._state = "half_open"
                logger.info("CircuitBreaker: HALF_OPEN (cooldown elapsed)")
            else:
                return ExecutionResult(
                    success=False,
                    error="Circuit breaker OPEN — Discord API experiencing failures. Retry later.",
                    should_retry=False,
                    metadata={"circuit_breaker": "open", "retry_after": self._cooldown - elapsed},
                )

        # Execute
        result = await next_fn(ctx)

        # Update state based on result
        if result.success:
            if self._state == "half_open":
                logger.info("CircuitBreaker: CLOSED (probe succeeded)")
            self._state = "closed"
            self._failure_count = 0
        else:
            self._failure_count += 1
            if self._failure_count >= self._failure_threshold:
                self._state = "open"
                self._opened_at = time.time()
                logger.warning(
                    "CircuitBreaker: OPEN (failures=%d >= threshold=%d)",
                    self._failure_count, self._failure_threshold,
                )

        return result

    @property
    def state(self) -> str:
        return self._state


class MetricsMiddleware(Middleware):
    """Record execution metrics to Prometheus."""

    async def __call__(self, ctx: ExecutionContext, next_fn: NextFn) -> ExecutionResult:
        from app.core.observability import tool_calls_total, tool_call_duration

        start = time.time()
        result = await next_fn(ctx)
        duration = time.time() - start

        status = "success" if result.success else "error"
        tool_calls_total.labels(tool_name=ctx.tool_name, status=status).inc()
        tool_call_duration.labels(tool_name=ctx.tool_name).observe(duration)

        return result

"""Observability Layer — Structured logging, metrics, and request tracing.

Provides:
  1. JSONFormatter — structured JSON log output
  2. Prometheus metrics — counters, histograms, gauges
  3. RequestContext — request_id propagation
  4. metrics_endpoint — FastAPI handler for /metrics
"""

from __future__ import annotations

import json
import logging
import time
import uuid
from contextvars import ContextVar
from typing import Any, Dict, Optional

from prometheus_client import Counter, Histogram, Gauge, generate_latest, CONTENT_TYPE_LATEST

# ===========================================================================
# Request Context (propagated via contextvars)
# ===========================================================================

_request_id: ContextVar[str] = ContextVar("request_id", default="")
_guild_id: ContextVar[int] = ContextVar("guild_id", default=0)


def set_request_context(request_id: str, guild_id: int = 0) -> None:
    _request_id.set(request_id)
    _guild_id.set(guild_id)


def get_request_id() -> str:
    return _request_id.get()


def get_context_guild_id() -> int:
    return _guild_id.get()


def generate_request_id() -> str:
    return uuid.uuid4().hex[:12]


# ===========================================================================
# Structured JSON Formatter
# ===========================================================================

class JSONFormatter(logging.Formatter):
    """Structured JSON log formatter for production.

    Output format:
    {"ts": 1720000000.0, "level": "INFO", "msg": "...", "module": "...", "request_id": "...", "guild_id": 0}
    """

    def format(self, record: logging.LogRecord) -> str:
        log_entry: Dict[str, Any] = {
            "ts": record.created,
            "level": record.levelname,
            "msg": record.getMessage(),
            "module": record.module,
            "func": record.funcName,
            "request_id": _request_id.get(""),
            "guild_id": _guild_id.get(0),
        }
        if record.exc_info and record.exc_info[1]:
            log_entry["exception"] = self.formatException(record.exc_info)
        if hasattr(record, "extra_data"):
            log_entry["data"] = record.extra_data
        return json.dumps(log_entry, default=str)


def configure_logging(level: str = "INFO", json_output: bool = True) -> None:
    """Configure root logger with structured JSON output."""
    root = logging.getLogger()
    root.setLevel(getattr(logging, level.upper(), logging.INFO))
    
    # Remove existing handlers
    root.handlers.clear()
    
    handler = logging.StreamHandler()
    if json_output:
        handler.setFormatter(JSONFormatter())
    else:
        handler.setFormatter(logging.Formatter(
            "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        ))
    root.addHandler(handler)


# ===========================================================================
# Prometheus Metrics
# ===========================================================================

# Request metrics
request_total = Counter(
    "aurafactory_requests_total",
    "Total requests processed",
    ["source", "status"],
)

request_duration = Histogram(
    "aurafactory_request_duration_seconds",
    "Request processing duration",
    ["source"],
    buckets=[0.1, 0.5, 1.0, 2.0, 5.0, 10.0, 30.0, 60.0],
)

# LLM metrics
llm_calls_total = Counter(
    "aurafactory_llm_calls_total",
    "Total LLM API calls",
    ["phase", "provider"],
)

llm_tokens_total = Counter(
    "aurafactory_llm_tokens_total",
    "Total LLM tokens consumed",
    ["direction", "provider"],  # direction: input/output
)

llm_call_duration = Histogram(
    "aurafactory_llm_call_duration_seconds",
    "LLM API call duration",
    ["phase", "provider"],
    buckets=[0.5, 1.0, 2.0, 5.0, 10.0, 30.0],
)

# Tool metrics
tool_calls_total = Counter(
    "aurafactory_tool_calls_total",
    "Total tool executions",
    ["tool_name", "status"],
)

tool_call_duration = Histogram(
    "aurafactory_tool_call_duration_seconds",
    "Tool execution duration",
    ["tool_name"],
    buckets=[0.1, 0.5, 1.0, 2.0, 5.0, 10.0],
)

# System metrics
active_sessions = Gauge(
    "aurafactory_active_sessions",
    "Currently active user sessions",
)

guilds_active = Gauge(
    "aurafactory_guilds_active",
    "Number of active guilds",
)

daily_token_usage = Gauge(
    "aurafactory_daily_token_usage",
    "Token usage today (resets daily)",
    ["guild_id"],
)

# Circuit breaker
circuit_breaker_state = Gauge(
    "aurafactory_circuit_breaker_state",
    "Circuit breaker state (0=closed, 1=open, 2=half-open)",
)


# ===========================================================================
# Metrics Endpoint
# ===========================================================================

async def metrics_endpoint():
    """FastAPI handler for Prometheus /metrics endpoint."""
    from fastapi.responses import Response
    return Response(
        content=generate_latest(),
        media_type=CONTENT_TYPE_LATEST,
    )

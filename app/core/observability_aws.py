"""AWS Observability Layer — CloudWatch Logs + Metrics + X-Ray Tracing.

Replaces Prometheus-based observability with AWS-native services:
  1. CloudWatch Logs — Structured JSON logs (via watchtower)
  2. CloudWatch Embedded Metrics — Zero-config custom metrics (EMF)
  3. AWS X-Ray — Distributed tracing for LLM calls, tool execution, Discord API

Pricing (Free Tier):
  - CloudWatch Logs: 5 GB ingestion + 5 GB storage/month
  - CloudWatch Metrics: 10 custom metrics + 1M API requests
  - X-Ray: 100,000 traces recorded + 1M traces scanned/month
  → For hackathon traffic: $0/month

Environment variables:
    AWS_XRAY_ENABLED: "true" to enable X-Ray tracing (default: true)
    CLOUDWATCH_LOG_GROUP: Log group name (default: /aurafactory/app)
    AWS_REGION: Region for CloudWatch (default: us-east-1)

Usage in code:
    from app.core.observability_aws import (
        configure_logging, metrics_endpoint,
        generate_request_id, set_request_context,
        trace_llm_call, trace_tool_call, emit_metric,
    )
"""

from __future__ import annotations

import json
import logging
import os
import time
import uuid
from contextlib import asynccontextmanager
from contextvars import ContextVar
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

# ===========================================================================
# Request Context (same interface as observability.py)
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
# Structured JSON Formatter (CloudWatch-optimized)
# ===========================================================================

class CloudWatchJSONFormatter(logging.Formatter):
    """Structured JSON formatter optimized for CloudWatch Logs Insights.

    CloudWatch Logs Insights can auto-parse JSON logs, enabling queries like:
        fields @timestamp, level, msg, guild_id
        | filter level = "ERROR"
        | sort @timestamp desc
    """

    def format(self, record: logging.LogRecord) -> str:
        log_entry: Dict[str, Any] = {
            "timestamp": record.created,
            "level": record.levelname,
            "msg": record.getMessage(),
            "logger": record.name,
            "module": record.module,
            "func": record.funcName,
            "request_id": _request_id.get(""),
            "guild_id": _guild_id.get(0),
        }

        # Add exception info
        if record.exc_info and record.exc_info[1]:
            log_entry["exception"] = self.formatException(record.exc_info)

        # Add extra data
        if hasattr(record, "extra_data"):
            log_entry["data"] = record.extra_data

        # Add X-Ray trace ID if available
        trace_id = _get_xray_trace_id()
        if trace_id:
            log_entry["xray_trace_id"] = trace_id

        return json.dumps(log_entry, default=str)


# ===========================================================================
# Logging Configuration
# ===========================================================================

def configure_logging(level: str = "INFO", json_output: bool = True) -> None:
    """Configure logging with CloudWatch-compatible JSON output.

    In AWS (App Runner/ECS), stdout logs are automatically captured by
    CloudWatch Logs. No watchtower agent needed — just structured JSON.
    """
    root = logging.getLogger()
    root.setLevel(getattr(logging, level.upper(), logging.INFO))

    # Remove existing handlers
    root.handlers.clear()

    handler = logging.StreamHandler()
    if json_output:
        handler.setFormatter(CloudWatchJSONFormatter())
    else:
        handler.setFormatter(logging.Formatter(
            "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        ))
    root.addHandler(handler)

    # Suppress noisy boto3/botocore logs
    logging.getLogger("boto3").setLevel(logging.WARNING)
    logging.getLogger("botocore").setLevel(logging.WARNING)
    logging.getLogger("urllib3").setLevel(logging.WARNING)


# ===========================================================================
# X-Ray Tracing
# ===========================================================================

_xray_enabled = os.getenv("AWS_XRAY_ENABLED", "true").lower() == "true"
_xray_recorder = None


def _init_xray():
    """Initialize X-Ray SDK (lazy, only when first trace is created)."""
    global _xray_recorder
    if _xray_recorder is not None:
        return _xray_recorder

    if not _xray_enabled:
        return None

    try:
        from aws_xray_sdk.core import xray_recorder, patch
        from aws_xray_sdk.core.context import Context

        xray_recorder.configure(
            service="AuraFactory",
            context=Context(),
            sampling=True,
            daemon_address="127.0.0.1:2000",  # X-Ray daemon (auto on App Runner)
        )

        # Patch boto3 for automatic tracing of AWS API calls
        patch(["boto3"])

        _xray_recorder = xray_recorder
        logger.info("[OK] X-Ray tracing initialized")
        return _xray_recorder

    except ImportError:
        logger.warning(
            "aws-xray-sdk not installed — X-Ray tracing disabled. "
            "Install with: pip install aws-xray-sdk"
        )
        return None
    except Exception as e:
        logger.warning("X-Ray init failed (non-fatal): %s", e)
        return None


def _get_xray_trace_id() -> Optional[str]:
    """Get current X-Ray trace ID for log correlation."""
    if not _xray_enabled or _xray_recorder is None:
        return None
    try:
        segment = _xray_recorder.current_segment()
        if segment:
            return segment.trace_id
    except Exception:
        pass
    return None


@asynccontextmanager
async def trace_segment(name: str, **annotations):
    """Create an X-Ray subsegment for tracing a code block.

    Usage:
        async with trace_segment("llm_call", model="nova-micro", phase="understand"):
            response = await llm.generate(...)
    """
    recorder = _init_xray()
    if not recorder:
        yield
        return

    try:
        subsegment = recorder.begin_subsegment(name)
        if subsegment:
            for key, value in annotations.items():
                subsegment.put_annotation(key, str(value))
        try:
            yield
        except Exception as e:
            if subsegment:
                subsegment.add_exception(e)
            raise
        finally:
            recorder.end_subsegment()
    except Exception:
        # Never let X-Ray errors break the app
        yield


@asynccontextmanager
async def trace_llm_call(provider: str, model: str, phase: str):
    """Trace an LLM API call with provider/model/phase annotations.

    Usage:
        async with trace_llm_call("bedrock", "nova-micro", "understand"):
            response = await llm.generate(...)
    """
    start = time.time()
    async with trace_segment(
        f"LLM.{phase}",
        provider=provider,
        model=model,
        phase=phase,
    ):
        yield

    duration = time.time() - start
    # Emit metric
    emit_metric("LLMCallDuration", duration, unit="Seconds", dimensions={
        "Provider": provider,
        "Phase": phase,
    })
    emit_metric("LLMCallCount", 1, unit="Count", dimensions={
        "Provider": provider,
        "Phase": phase,
    })


@asynccontextmanager
async def trace_tool_call(tool_name: str, guild_id: int = 0):
    """Trace a tool/MCP execution.

    Usage:
        async with trace_tool_call("discord.channels.create", guild_id=123):
            result = await mcp_client.call_tool(...)
    """
    start = time.time()
    async with trace_segment(
        f"Tool.{tool_name}",
        tool_name=tool_name,
        guild_id=str(guild_id),
    ):
        yield

    duration = time.time() - start
    emit_metric("ToolCallDuration", duration, unit="Seconds", dimensions={
        "ToolName": tool_name.split(".")[-1],  # Short name for dimension
    })
    emit_metric("ToolCallCount", 1, unit="Count", dimensions={
        "ToolName": tool_name.split(".")[-1],
    })


# ===========================================================================
# CloudWatch Embedded Metrics Format (EMF)
# ===========================================================================

_METRIC_NAMESPACE = "AuraFactory"


def emit_metric(
    name: str,
    value: float,
    unit: str = "None",
    dimensions: Optional[Dict[str, str]] = None,
) -> None:
    """Emit a CloudWatch metric using Embedded Metric Format (EMF).

    EMF works by printing a specially-formatted JSON line to stdout.
    CloudWatch Logs agent automatically extracts it as a metric.
    No API calls needed — zero latency overhead!

    Supported units: Seconds, Count, Bytes, Percent, None

    Usage:
        emit_metric("RequestLatency", 1.23, unit="Seconds", dimensions={"Source": "discord"})
        emit_metric("TokensUsed", 1500, unit="Count", dimensions={"Provider": "bedrock"})
    """
    dims = dimensions or {}

    # EMF format: https://docs.aws.amazon.com/AmazonCloudWatch/latest/monitoring/CloudWatch_Embedded_Metric_Format_Specification.html
    emf_log = {
        "_aws": {
            "Timestamp": int(time.time() * 1000),
            "CloudWatchMetrics": [
                {
                    "Namespace": _METRIC_NAMESPACE,
                    "Dimensions": [list(dims.keys())] if dims else [[]],
                    "Metrics": [
                        {"Name": name, "Unit": unit}
                    ],
                }
            ],
        },
        # Metric value
        name: value,
        # Dimension values
        **dims,
        # Context (for log correlation)
        "request_id": _request_id.get(""),
        "guild_id": _guild_id.get(0),
    }

    # Print to stdout — CloudWatch agent picks it up
    print(json.dumps(emf_log))


# ===========================================================================
# Pre-built metric helpers (compatible with existing observability.py usage)
# ===========================================================================

def record_request(source: str, status: str, duration: float) -> None:
    """Record a request metric (replaces prometheus Counter/Histogram)."""
    emit_metric("RequestCount", 1, unit="Count", dimensions={
        "Source": source,
        "Status": status,
    })
    emit_metric("RequestDuration", duration, unit="Seconds", dimensions={
        "Source": source,
    })


def record_llm_tokens(provider: str, direction: str, count: int) -> None:
    """Record LLM token usage (replaces prometheus Counter)."""
    emit_metric("TokensUsed", count, unit="Count", dimensions={
        "Provider": provider,
        "Direction": direction,  # "input" or "output"
    })


def record_tool_execution(tool_name: str, status: str, duration: float) -> None:
    """Record tool execution (replaces prometheus Counter/Histogram)."""
    short_name = tool_name.split(".")[-1] if "." in tool_name else tool_name
    emit_metric("ToolExecution", 1, unit="Count", dimensions={
        "Tool": short_name,
        "Status": status,
    })
    emit_metric("ToolDuration", duration, unit="Seconds", dimensions={
        "Tool": short_name,
    })


# ===========================================================================
# Metrics Endpoint (backward compatible — now returns JSON summary)
# ===========================================================================

async def metrics_endpoint():
    """FastAPI handler for /metrics endpoint.

    In Phase 2, primary metrics go to CloudWatch via EMF.
    This endpoint returns a simple JSON summary for health checks.
    """
    from fastapi.responses import JSONResponse
    return JSONResponse({
        "status": "healthy",
        "observability": {
            "logs": "CloudWatch Logs (stdout JSON)",
            "metrics": "CloudWatch EMF (embedded in logs)",
            "tracing": "X-Ray" if _xray_enabled else "disabled",
        },
        "namespace": _METRIC_NAMESPACE,
        "xray_enabled": _xray_enabled,
    })

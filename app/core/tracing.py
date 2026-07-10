"""Tracing Foundation — OpenTelemetry-compatible request tracing.

Phase 1: Lightweight context propagation using contextvars (no SDK dependency).
Phase 2: Add opentelemetry-sdk for full distributed tracing to Jaeger/Tempo.

This module provides:
  1. Span-like context tracking (start_span, end_span)
  2. Trace ID propagation across async boundaries
  3. Integration points for future OTel SDK

Usage:
    from app.core.tracing import start_span, end_span, get_trace_id

    span = start_span("process_request", attributes={"guild_id": 123})
    try:
        # ... do work ...
        span.set_status("ok")
    except Exception as e:
        span.set_status("error", str(e))
    finally:
        end_span(span)
"""

from __future__ import annotations

import logging
import time
import uuid
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# Context propagation
_current_trace_id: ContextVar[str] = ContextVar("trace_id", default="")
_current_spans: ContextVar[List["Span"]] = ContextVar("spans", default_factory=list)


@dataclass
class Span:
    """Lightweight span for request tracing.

    Compatible with OpenTelemetry Span interface (subset).
    When OTel SDK is added, this can be replaced with real spans.
    """

    name: str
    trace_id: str
    span_id: str = field(default_factory=lambda: uuid.uuid4().hex[:16])
    parent_id: Optional[str] = None
    start_time: float = field(default_factory=time.time)
    end_time: Optional[float] = None
    attributes: Dict[str, Any] = field(default_factory=dict)
    status: str = "unset"  # unset | ok | error
    status_message: str = ""
    events: List[Dict[str, Any]] = field(default_factory=list)

    def set_attribute(self, key: str, value: Any) -> None:
        self.attributes[key] = value

    def set_status(self, status: str, message: str = "") -> None:
        self.status = status
        self.status_message = message

    def add_event(self, name: str, attributes: Optional[Dict[str, Any]] = None) -> None:
        self.events.append({
            "name": name,
            "timestamp": time.time(),
            "attributes": attributes or {},
        })

    @property
    def duration_ms(self) -> float:
        if self.end_time:
            return (self.end_time - self.start_time) * 1000
        return (time.time() - self.start_time) * 1000

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "trace_id": self.trace_id,
            "span_id": self.span_id,
            "parent_id": self.parent_id,
            "duration_ms": self.duration_ms,
            "status": self.status,
            "attributes": self.attributes,
            "events_count": len(self.events),
        }


def generate_trace_id() -> str:
    """Generate a new trace ID (32-char hex, OTel-compatible length)."""
    return uuid.uuid4().hex


def get_trace_id() -> str:
    """Get current trace ID from context."""
    tid = _current_trace_id.get()
    if not tid:
        tid = generate_trace_id()
        _current_trace_id.set(tid)
    return tid


def set_trace_id(trace_id: str) -> None:
    """Set trace ID (e.g., from incoming request header)."""
    _current_trace_id.set(trace_id)


def start_span(name: str, attributes: Optional[Dict[str, Any]] = None) -> Span:
    """Start a new span in the current trace.

    Args:
        name: Span name (e.g., "process_request", "llm_call", "tool_execute")
        attributes: Initial span attributes

    Returns:
        Span object (call end_span when done)
    """
    trace_id = get_trace_id()
    spans = _current_spans.get([])

    parent_id = spans[-1].span_id if spans else None
    span = Span(
        name=name,
        trace_id=trace_id,
        parent_id=parent_id,
        attributes=attributes or {},
    )
    spans.append(span)
    _current_spans.set(spans)

    logger.debug("Span started: %s (trace=%s)", name, trace_id[:8])
    return span


def end_span(span: Span) -> None:
    """End a span and remove from context stack."""
    span.end_time = time.time()

    spans = _current_spans.get([])
    if spans and spans[-1].span_id == span.span_id:
        spans.pop()
        _current_spans.set(spans)

    # Log completed span
    if span.status == "error":
        logger.warning(
            "Span error: %s (%.1fms) — %s",
            span.name,
            span.duration_ms,
            span.status_message,
        )
    else:
        logger.debug("Span done: %s (%.1fms)", span.name, span.duration_ms)


def get_active_spans() -> List[Span]:
    """Get all active (unfinished) spans in current context."""
    return _current_spans.get([])

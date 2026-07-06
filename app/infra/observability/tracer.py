"""Request tracing for distributed observability."""

import logging
import time
import uuid
from dataclasses import dataclass, field
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class Span:
    """A single span within a trace."""

    name: str
    trace_id: str
    span_id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    start_time: float = field(default_factory=time.time)
    end_time: Optional[float] = None
    metadata: Dict[str, str] = field(default_factory=dict)

    @property
    def duration_ms(self) -> float:
        """Duration in milliseconds."""
        if self.end_time is None:
            return (time.time() - self.start_time) * 1000
        return (self.end_time - self.start_time) * 1000


class Tracer:
    """Simple request tracer for tracking execution flow."""

    def __init__(self) -> None:
        self._active_traces: Dict[str, List[Span]] = {}
        self._current_trace_id: Optional[str] = None

    @staticmethod
    def generate_trace_id() -> str:
        """Generate a unique trace identifier."""
        return str(uuid.uuid4())

    def start_span(self, name: str, trace_id: Optional[str] = None) -> Span:
        """Start a new span within a trace.

        Args:
            name: Descriptive name for the span.
            trace_id: Optional trace ID. Uses current trace if not provided.

        Returns:
            The newly created Span.
        """
        tid = trace_id or self._current_trace_id or self.generate_trace_id()
        self._current_trace_id = tid

        span = Span(name=name, trace_id=tid)

        if tid not in self._active_traces:
            self._active_traces[tid] = []
        self._active_traces[tid].append(span)

        logger.debug("Started span '%s' (trace=%s, span=%s)", name, tid, span.span_id)
        return span

    def end_span(self, span: Span) -> None:
        """End a span and record its duration."""
        span.end_time = time.time()
        logger.debug(
            "Ended span '%s' (trace=%s, duration=%.2fms)",
            span.name,
            span.trace_id,
            span.duration_ms,
        )

    def get_current_trace(self) -> Optional[str]:
        """Get the current active trace ID."""
        return self._current_trace_id

    def get_spans(self, trace_id: str) -> List[Span]:
        """Get all spans for a given trace ID."""
        return self._active_traces.get(trace_id, [])

    def clear_trace(self, trace_id: str) -> None:
        """Remove a completed trace from memory."""
        self._active_traces.pop(trace_id, None)
        if self._current_trace_id == trace_id:
            self._current_trace_id = None

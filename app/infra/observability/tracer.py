# app/infra/observability/tracer.py
"""
Distributed tracing — all agent actions flow through here.
Migrated from app/observability/tracer.py — logic preserved.
Phase 1: Structured logging + JSONL files.
Phase 2: AWS X-Ray / CloudWatch.
"""
import json
import logging
from dataclasses import dataclass, field, asdict
from datetime import datetime
from typing import Optional, Dict, Any, List
from uuid import uuid4
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass
class TraceEvent:
    """A single trace event."""
    trace_id: str
    span_id: str
    agent_id: str
    event_type: str      # reasoning | tool_call | handoff | approval | error
    content: Dict[str, Any]
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())
    parent_span_id: Optional[str] = None
    duration_ms: float = 0.0
    status: str = "ok"


class Tracer:
    """
    Distributed tracing service.
    Logs reasoning, tool calls, handoffs, approvals, errors.
    Persists traces as JSONL files for audit.
    """

    def __init__(self, log_dir: str = "logs/traces", console_output: bool = True):
        self._log_dir = Path(log_dir)
        self._log_dir.mkdir(parents=True, exist_ok=True)
        self._console = console_output
        self._events: List[TraceEvent] = []

    def new_trace(self) -> str:
        """Generate a new trace ID."""
        return str(uuid4())[:8]

    def new_span(self) -> str:
        """Generate a new span ID."""
        return str(uuid4())[:8]

    def log_reasoning(self, trace_id: str, agent_id: str, thought: str, **kwargs) -> str:
        """Log an agent reasoning step."""
        span_id = self.new_span()
        event = TraceEvent(
            trace_id=trace_id, span_id=span_id, agent_id=agent_id,
            event_type="reasoning", content={"thought": thought, **kwargs},
        )
        self._emit(event)
        return span_id

    def log_tool_call(
        self, trace_id: str, agent_id: str,
        tool_name: str, tool_input: Dict, tool_output: Any,
        duration_ms: float, status: str = "ok",
        parent_span_id: Optional[str] = None,
    ) -> str:
        """Log a tool execution."""
        span_id = self.new_span()
        event = TraceEvent(
            trace_id=trace_id, span_id=span_id, agent_id=agent_id,
            event_type="tool_call",
            content={
                "tool_name": tool_name,
                "input": tool_input,
                "output": tool_output if isinstance(tool_output, (dict, str)) else str(tool_output),
            },
            duration_ms=duration_ms, status=status, parent_span_id=parent_span_id,
        )
        self._emit(event)
        return span_id

    def log_handoff(self, trace_id: str, from_agent: str, to_agent: str, task_summary: str) -> str:
        """Log agent-to-agent handoff."""
        span_id = self.new_span()
        event = TraceEvent(
            trace_id=trace_id, span_id=span_id, agent_id=from_agent,
            event_type="handoff",
            content={"from": from_agent, "to": to_agent, "task": task_summary},
        )
        self._emit(event)
        return span_id

    def log_approval(
        self, trace_id: str, agent_id: str,
        action: str, approved: bool, approver: str = "system",
    ) -> str:
        """Log approval request/decision."""
        span_id = self.new_span()
        event = TraceEvent(
            trace_id=trace_id, span_id=span_id, agent_id=agent_id,
            event_type="approval",
            content={"action": action, "approved": approved, "approver": approver},
            status="ok" if approved else "rejected",
        )
        self._emit(event)
        return span_id

    def log_error(self, trace_id: str, agent_id: str, error: str, **kwargs) -> str:
        """Log an error event."""
        span_id = self.new_span()
        event = TraceEvent(
            trace_id=trace_id, span_id=span_id, agent_id=agent_id,
            event_type="error", content={"error": error, **kwargs}, status="error",
        )
        self._emit(event)
        return span_id

    def log_security(self, trace_id: str, event_type: str, details: str) -> str:
        """Log a security event."""
        span_id = self.new_span()
        event = TraceEvent(
            trace_id=trace_id, span_id=span_id, agent_id="security",
            event_type="security",
            content={"event_type": event_type, "details": details},
            status="warning",
        )
        self._emit(event)
        return span_id

    def get_trace(self, trace_id: str) -> List[Dict]:
        """Get all events for a trace."""
        return [asdict(e) for e in self._events if e.trace_id == trace_id]

    def _emit(self, event: TraceEvent) -> None:
        """Store event and optionally output to console/file."""
        self._events.append(event)

        if self._console:
            icon = {
                "reasoning": "🧠", "tool_call": "🔧", "handoff": "🔀",
                "approval": "✅" if event.content.get("approved") else "❌",
                "error": "💥", "security": "🛡️",
            }.get(event.event_type, "📍")
            print(
                f"  {icon} [{event.trace_id}] {event.agent_id}.{event.event_type}: "
                f"{json.dumps(event.content, ensure_ascii=False, default=str)[:200]}"
            )

        # Persist to JSONL file
        try:
            log_file = self._log_dir / f"trace_{event.trace_id}.jsonl"
            with open(log_file, "a", encoding="utf-8") as f:
                f.write(json.dumps(asdict(event), ensure_ascii=False, default=str) + "\n")
        except Exception as e:
            logger.warning(f"Failed to persist trace event: {e}")

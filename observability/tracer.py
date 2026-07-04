# observability/tracer.py
"""
Agentic AI Lens Principle 2: Make every agent action observable and traceable end-to-end
Well-Architected (Ops): Implement observability for actionable insights

Phase 1: Console/JSON file logging
Phase 2: Swap sang AgentCore Observability (chỉ đổi backend, interface giữ nguyên)
"""
import json
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime
from typing import Optional, Dict, Any, List
from uuid import uuid4
from pathlib import Path


@dataclass
class TraceEvent:
    """Một event trong trace — reasoning, tool_call, handoff, approval"""
    trace_id: str
    span_id: str
    agent_id: str
    event_type: str      # "reasoning" | "tool_call" | "handoff" | "approval" | "error"
    content: Dict[str, Any]
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())
    parent_span_id: Optional[str] = None
    duration_ms: float = 0.0
    status: str = "ok"   # "ok" | "error" | "timeout"


class Tracer:
    """
    Centralized tracing — mọi agent action đi qua đây.
    
    Phase 1: Ghi JSON file + console output
    Phase 2: Gửi lên AgentCore Observability (chỉ đổi _emit method)
    """
    
    def __init__(self, log_dir: str = "logs/traces", console_output: bool = True):
        self._log_dir = Path(log_dir)
        self._log_dir.mkdir(parents=True, exist_ok=True)
        self._console = console_output
        self._events: List[TraceEvent] = []
    
    def new_trace(self) -> str:
        """Bắt đầu trace mới cho 1 user request"""
        return str(uuid4())[:8]
    
    def new_span(self) -> str:
        """Bắt đầu span mới trong trace"""
        return str(uuid4())[:8]
    
    def log_reasoning(self, trace_id: str, agent_id: str, thought: str, **kwargs) -> str:
        """Agent đang suy nghĩ gì"""
        span_id = self.new_span()
        event = TraceEvent(
            trace_id=trace_id,
            span_id=span_id,
            agent_id=agent_id,
            event_type="reasoning",
            content={"thought": thought, **kwargs},
        )
        self._emit(event)
        return span_id
    
    def log_tool_call(
        self, trace_id: str, agent_id: str,
        tool_name: str, tool_input: Dict, tool_output: Any,
        duration_ms: float, status: str = "ok",
        parent_span_id: Optional[str] = None,
    ) -> str:
        """Agent gọi tool — ghi input/output/latency"""
        span_id = self.new_span()
        event = TraceEvent(
            trace_id=trace_id,
            span_id=span_id,
            agent_id=agent_id,
            event_type="tool_call",
            content={
                "tool_name": tool_name,
                "input": tool_input,
                "output": tool_output if isinstance(tool_output, (dict, str)) else str(tool_output),
            },
            duration_ms=duration_ms,
            status=status,
            parent_span_id=parent_span_id,
        )
        self._emit(event)
        return span_id
    
    def log_handoff(
        self, trace_id: str,
        from_agent: str, to_agent: str,
        task_summary: str,
    ) -> str:
        """Agent chuyển việc cho agent khác"""
        span_id = self.new_span()
        event = TraceEvent(
            trace_id=trace_id,
            span_id=span_id,
            agent_id=from_agent,
            event_type="handoff",
            content={
                "from": from_agent,
                "to": to_agent,
                "task": task_summary,
            },
        )
        self._emit(event)
        return span_id
    
    def log_approval(
        self, trace_id: str, agent_id: str,
        action: str, approved: bool,
        approver: str = "system",
    ) -> str:
        """Human-in-the-loop decision"""
        span_id = self.new_span()
        event = TraceEvent(
            trace_id=trace_id,
            span_id=span_id,
            agent_id=agent_id,
            event_type="approval",
            content={
                "action": action,
                "approved": approved,
                "approver": approver,
            },
            status="ok" if approved else "rejected",
        )
        self._emit(event)
        return span_id
    
    def log_error(self, trace_id: str, agent_id: str, error: str, **kwargs) -> str:
        """Lỗi xảy ra"""
        span_id = self.new_span()
        event = TraceEvent(
            trace_id=trace_id,
            span_id=span_id,
            agent_id=agent_id,
            event_type="error",
            content={"error": error, **kwargs},
            status="error",
        )
        self._emit(event)
        return span_id
    
    def get_trace(self, trace_id: str) -> List[Dict]:
        """Lấy toàn bộ events của 1 trace (for debug/display)"""
        return [asdict(e) for e in self._events if e.trace_id == trace_id]
    
    def _emit(self, event: TraceEvent):
        """
        Phase 1: Console + JSON file
        Phase 2: Thay bằng AgentCore Observability SDK call
        """
        self._events.append(event)
        
        # Console output (readable)
        if self._console:
            icon = {
                "reasoning": "🧠",
                "tool_call": "🔧",
                "handoff": "🔀",
                "approval": "✅" if event.content.get("approved") else "❌",
                "error": "💥",
            }.get(event.event_type, "📍")
            
            print(f"  {icon} [{event.trace_id}] {event.agent_id}.{event.event_type}: "
                  f"{json.dumps(event.content, ensure_ascii=False, default=str)[:200]}")
        
        # JSON file (structured, queryable)
        log_file = self._log_dir / f"trace_{event.trace_id}.jsonl"
        with open(log_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(asdict(event), ensure_ascii=False, default=str) + "\n")

# app/infra/observability/metrics.py
"""
Metrics Collector — Lightweight Prometheus-style metrics.
Migrated from app/observability/metrics.py — logic preserved.
"""
import time
import logging
from typing import Dict, Any, Optional, List
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime

logger = logging.getLogger(__name__)


@dataclass
class MetricPoint:
    value: float
    timestamp: float
    labels: Dict[str, str] = field(default_factory=dict)


class MetricsCollector:
    """
    Collects and aggregates metrics for observability.
    Metric types: Counter, Gauge, Histogram.
    """

    def __init__(self):
        self._counters: Dict[str, float] = defaultdict(float)
        self._gauges: Dict[str, float] = {}
        self._histograms: Dict[str, List[float]] = defaultdict(list)
        self._labels: Dict[str, Dict[str, str]] = {}
        self._start_time = time.time()

    # === Counters ===

    def increment(self, name: str, value: float = 1.0, labels: Optional[Dict[str, str]] = None):
        key = self._make_key(name, labels)
        self._counters[key] += value
        if labels:
            self._labels[key] = labels

    def count_request(self, provider: str, agent: str, status: str = "success"):
        self.increment("llm_requests_total", labels={"provider": provider, "agent": agent, "status": status})

    def count_tokens(self, provider: str, input_tokens: int, output_tokens: int):
        self.increment("llm_input_tokens_total", value=input_tokens, labels={"provider": provider})
        self.increment("llm_output_tokens_total", value=output_tokens, labels={"provider": provider})

    def count_tool_call(self, tool_name: str, status: str = "success"):
        self.increment("tool_calls_total", labels={"tool": tool_name, "status": status})

    def count_approval(self, action: str, approved: bool):
        status = "approved" if approved else "rejected"
        self.increment("approvals_total", labels={"action": action, "status": status})

    def count_error(self, error_type: str, component: str):
        self.increment("errors_total", labels={"type": error_type, "component": component})

    # === Gauges ===

    def set_gauge(self, name: str, value: float, labels: Optional[Dict[str, str]] = None):
        key = self._make_key(name, labels)
        self._gauges[key] = value
        if labels:
            self._labels[key] = labels

    def set_active_users(self, count: int):
        self.set_gauge("active_users", count)

    def set_pending_approvals(self, count: int):
        self.set_gauge("pending_approvals", count)

    def set_provider_status(self, provider: str, available: bool):
        self.set_gauge("provider_available", 1.0 if available else 0.0, labels={"provider": provider})

    # === Histograms ===

    def observe(self, name: str, value: float, labels: Optional[Dict[str, str]] = None):
        key = self._make_key(name, labels)
        self._histograms[key].append(value)
        if labels:
            self._labels[key] = labels
        if len(self._histograms[key]) > 1000:
            self._histograms[key] = self._histograms[key][-1000:]

    def observe_latency(self, provider: str, latency_ms: float):
        self.observe("llm_latency_ms", latency_ms, labels={"provider": provider})

    def observe_tool_duration(self, tool_name: str, duration_ms: float):
        self.observe("tool_duration_ms", duration_ms, labels={"tool": tool_name})

    # === Export ===

    def get_summary(self) -> Dict[str, Any]:
        uptime = time.time() - self._start_time
        histogram_stats = {}
        for key, values in self._histograms.items():
            if values:
                sorted_vals = sorted(values)
                histogram_stats[key] = {
                    "count": len(values),
                    "min": sorted_vals[0],
                    "max": sorted_vals[-1],
                    "avg": sum(values) / len(values),
                    "p50": sorted_vals[len(sorted_vals) // 2],
                    "p95": sorted_vals[int(len(sorted_vals) * 0.95)],
                    "p99": sorted_vals[int(len(sorted_vals) * 0.99)],
                }

        return {
            "uptime_seconds": round(uptime, 1),
            "counters": dict(self._counters),
            "gauges": dict(self._gauges),
            "histograms": histogram_stats,
            "collected_at": datetime.now().isoformat(),
        }

    def export_prometheus(self) -> str:
        lines = []
        for key, value in self._counters.items():
            labels_str = self._format_labels(key)
            name = key.split("{")[0] if "{" in key else key
            lines.append(f"{name}{labels_str} {value}")
        for key, value in self._gauges.items():
            labels_str = self._format_labels(key)
            name = key.split("{")[0] if "{" in key else key
            lines.append(f"{name}{labels_str} {value}")
        return "\n".join(lines)

    def reset(self):
        self._counters.clear()
        self._gauges.clear()
        self._histograms.clear()
        self._labels.clear()
        self._start_time = time.time()

    # === Internal ===

    def _make_key(self, name: str, labels: Optional[Dict[str, str]] = None) -> str:
        if not labels:
            return name
        labels_str = ",".join(f'{k}="{v}"' for k, v in sorted(labels.items()))
        return f"{name}{{{labels_str}}}"

    def _format_labels(self, key: str) -> str:
        labels = self._labels.get(key)
        if not labels:
            return ""
        return "{" + ",".join(f'{k}="{v}"' for k, v in labels.items()) + "}"


# Singleton
metrics = MetricsCollector()

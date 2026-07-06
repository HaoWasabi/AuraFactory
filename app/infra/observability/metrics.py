"""Metrics collection for LLM usage and performance."""

import logging
import time
from dataclasses import dataclass, field
from typing import Dict, List

logger = logging.getLogger(__name__)


@dataclass
class RequestMetric:
    """A single LLM request metric record."""

    agent: str
    tokens_in: int
    tokens_out: int
    cost: float
    provider: str
    timestamp: float = field(default_factory=time.time)


@dataclass
class LatencyMetric:
    """A single latency measurement."""

    agent: str
    duration_ms: float
    timestamp: float = field(default_factory=time.time)


class Metrics:
    """Collects and aggregates performance metrics."""

    def __init__(self) -> None:
        self._requests: List[RequestMetric] = []
        self._latencies: List[LatencyMetric] = []

    def track_request(
        self,
        agent: str,
        tokens_in: int,
        tokens_out: int,
        cost: float,
        provider: str,
    ) -> None:
        """Record an LLM request metric.

        Args:
            agent: Name of the agent making the request.
            tokens_in: Number of input tokens.
            tokens_out: Number of output tokens.
            cost: Estimated cost in USD.
            provider: LLM provider name.
        """
        metric = RequestMetric(
            agent=agent,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            cost=cost,
            provider=provider,
        )
        self._requests.append(metric)
        logger.debug(
            "Request metric: agent=%s, tokens=%d/%d, cost=%.6f, provider=%s",
            agent, tokens_in, tokens_out, cost, provider,
        )

    def track_latency(self, agent: str, duration: float) -> None:
        """Record a latency measurement.

        Args:
            agent: Name of the agent.
            duration: Duration in milliseconds.
        """
        metric = LatencyMetric(agent=agent, duration_ms=duration)
        self._latencies.append(metric)
        logger.debug("Latency metric: agent=%s, duration=%.2fms", agent, duration)

    def get_stats(self) -> Dict[str, object]:
        """Get aggregated statistics.

        Returns:
            Dictionary with total requests, total cost, average latency,
            and per-agent breakdowns.
        """
        total_cost = sum(r.cost for r in self._requests)
        total_tokens_in = sum(r.tokens_in for r in self._requests)
        total_tokens_out = sum(r.tokens_out for r in self._requests)
        avg_latency = (
            sum(l.duration_ms for l in self._latencies) / len(self._latencies)
            if self._latencies
            else 0.0
        )

        # Per-agent breakdown
        agent_stats: Dict[str, Dict[str, float]] = {}
        for r in self._requests:
            if r.agent not in agent_stats:
                agent_stats[r.agent] = {"requests": 0, "cost": 0.0, "tokens_in": 0, "tokens_out": 0}
            agent_stats[r.agent]["requests"] += 1
            agent_stats[r.agent]["cost"] += r.cost
            agent_stats[r.agent]["tokens_in"] += r.tokens_in
            agent_stats[r.agent]["tokens_out"] += r.tokens_out

        return {
            "total_requests": len(self._requests),
            "total_cost_usd": total_cost,
            "total_tokens_in": total_tokens_in,
            "total_tokens_out": total_tokens_out,
            "average_latency_ms": avg_latency,
            "agent_stats": agent_stats,
        }

    def reset(self) -> None:
        """Clear all collected metrics."""
        self._requests.clear()
        self._latencies.clear()

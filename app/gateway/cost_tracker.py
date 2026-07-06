# app/gateway/cost_tracker.py
"""
Cost Tracker — tracks token usage and estimated cost per request/guild.
"""
import logging
from typing import Dict
from collections import defaultdict
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


# Cost per million tokens (USD) — approximate
COST_TABLE = {
    "gemini-2.5-flash": {"input": 0.075, "output": 0.30},
    "gemini-2.0-flash": {"input": 0.075, "output": 0.30},
    "llama-3.3-70b-versatile": {"input": 0.0, "output": 0.0},  # Groq free tier
    "qwen2.5:7b": {"input": 0.0, "output": 0.0},  # Ollama local
}


@dataclass
class RequestCost:
    """Cost tracking for a single request."""
    trace_id: str
    model: str
    input_tokens: int
    output_tokens: int
    estimated_cost_usd: float


class CostTracker:
    """Tracks token usage and cost across requests."""

    def __init__(self):
        self._total_input_tokens: int = 0
        self._total_output_tokens: int = 0
        self._total_cost_usd: float = 0.0
        self._per_guild: Dict[int, Dict[str, float]] = defaultdict(
            lambda: {"input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0}
        )
        self._request_count: int = 0

    def track(
        self,
        trace_id: str,
        model: str,
        input_tokens: int,
        output_tokens: int,
        guild_id: int = 0,
    ) -> RequestCost:
        """Track a single LLM request cost."""
        cost = self._estimate_cost(model, input_tokens, output_tokens)

        self._total_input_tokens += input_tokens
        self._total_output_tokens += output_tokens
        self._total_cost_usd += cost
        self._request_count += 1

        if guild_id:
            self._per_guild[guild_id]["input_tokens"] += input_tokens
            self._per_guild[guild_id]["output_tokens"] += output_tokens
            self._per_guild[guild_id]["cost_usd"] += cost

        return RequestCost(
            trace_id=trace_id,
            model=model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            estimated_cost_usd=cost,
        )

    def get_summary(self) -> dict:
        """Get overall cost summary."""
        return {
            "total_requests": self._request_count,
            "total_input_tokens": self._total_input_tokens,
            "total_output_tokens": self._total_output_tokens,
            "total_cost_usd": round(self._total_cost_usd, 6),
        }

    def get_guild_summary(self, guild_id: int) -> dict:
        """Get cost summary for a specific guild."""
        data = self._per_guild.get(guild_id, {})
        return {
            "guild_id": guild_id,
            "input_tokens": data.get("input_tokens", 0),
            "output_tokens": data.get("output_tokens", 0),
            "cost_usd": round(data.get("cost_usd", 0.0), 6),
        }

    def _estimate_cost(self, model: str, input_tokens: int, output_tokens: int) -> float:
        """Estimate USD cost for a request."""
        costs = COST_TABLE.get(model, {"input": 0.0, "output": 0.0})
        input_cost = (input_tokens / 1_000_000) * costs["input"]
        output_cost = (output_tokens / 1_000_000) * costs["output"]
        return input_cost + output_cost


# Singleton
cost_tracker = CostTracker()

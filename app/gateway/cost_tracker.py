# app/gateway/cost_tracker.py
"""
Cost Tracker — per-guild daily budget enforcement.
Uses Postgres `cost_log` table for persistence.
Default daily budget: $1.00 USD per guild.
"""
import time
import logging
from typing import Any, Dict, Optional, Tuple
from datetime import datetime, timezone
from collections import defaultdict

logger = logging.getLogger(__name__)

# Cost per million tokens (USD)
COST_TABLE: Dict[str, Dict[str, float]] = {
    "gemini-2.5-flash": {"input": 0.075, "output": 0.30},
    "gemini-2.0-flash": {"input": 0.075, "output": 0.30},
    "gemini-1.5-flash": {"input": 0.075, "output": 0.30},
    "llama-3.3-70b-versatile": {"input": 0.0, "output": 0.0},  # Groq free tier
    "qwen2.5:7b": {"input": 0.0, "output": 0.0},  # Ollama local
}


class CostTracker:
    """
    Tracks LLM usage cost per guild with daily budget enforcement.

    Features:
    - check_budget: verify guild hasn't exceeded daily spend limit.
    - record_cost: log individual LLM call costs.
    - get_daily_spend: retrieve current day's total for a guild.

    Storage:
    - Phase 1: In-memory with daily reset.
    - Phase 2: Postgres `cost_log` table for persistence and analytics.
    """

    def __init__(self, db: Any = None, daily_budget_usd: float = 1.0) -> None:
        self._db = db  # Postgres connection pool
        self._daily_budget_usd: float = daily_budget_usd

        # In-memory tracking (fast path)
        # Structure: {guild_id: {date_str: total_cost_usd}}
        self._daily_spend: Dict[int, Dict[str, float]] = defaultdict(lambda: defaultdict(float))
        self._total_requests: int = 0
        self._total_cost_usd: float = 0.0

    def check_budget(self, guild_id: int) -> Tuple[bool, float]:
        """
        Check if a guild has remaining budget for today.

        Args:
            guild_id: The Discord guild to check.

        Returns:
            (allowed, remaining_usd)
            - allowed=True if budget remains.
            - remaining_usd: how much budget is left today.
        """
        today = self._today_key()
        spent = self._daily_spend[guild_id][today]
        remaining = max(0.0, self._daily_budget_usd - spent)
        allowed = remaining > 0.0

        if not allowed:
            logger.warning(
                f"Budget exceeded for guild {guild_id}: "
                f"spent=${spent:.4f}, budget=${self._daily_budget_usd:.2f}"
            )

        return allowed, remaining

    async def record_cost(
        self,
        guild_id: int,
        user_id: str,
        agent_name: str,
        provider: str,
        input_tokens: int,
        output_tokens: int,
        cost_usd: Optional[float] = None,
    ) -> float:
        """
        Record cost for a single LLM call.

        If cost_usd is not provided, it's calculated from the cost table.
        Persists to Postgres `cost_log` table if db is configured.

        Args:
            guild_id: Guild where the request originated.
            user_id: User who triggered the request.
            agent_name: Which agent made the call (orchestrator, admin, etc.).
            provider: Model/provider name.
            input_tokens: Number of input tokens consumed.
            output_tokens: Number of output tokens generated.
            cost_usd: Explicit cost override (if None, calculated from table).

        Returns:
            The computed cost in USD.
        """
        if cost_usd is None:
            cost_usd = self._calculate_cost(provider, input_tokens, output_tokens)

        # Update in-memory tracking
        today = self._today_key()
        self._daily_spend[guild_id][today] += cost_usd
        self._total_requests += 1
        self._total_cost_usd += cost_usd

        # Persist to Postgres
        if self._db:
            await self._persist_to_db(
                guild_id=guild_id,
                user_id=user_id,
                agent_name=agent_name,
                provider=provider,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                cost_usd=cost_usd,
            )

        logger.debug(
            f"Cost recorded: guild={guild_id}, agent={agent_name}, "
            f"provider={provider}, tokens={input_tokens}+{output_tokens}, "
            f"cost=${cost_usd:.6f}"
        )
        return cost_usd

    def get_daily_spend(self, guild_id: int) -> float:
        """
        Get today's total spend for a guild.

        Returns:
            Total USD spent today for the guild.
        """
        today = self._today_key()
        return self._daily_spend[guild_id][today]

    def get_summary(self) -> Dict[str, Any]:
        """Get overall cost summary since startup."""
        return {
            "total_requests": self._total_requests,
            "total_cost_usd": round(self._total_cost_usd, 6),
            "daily_budget_usd": self._daily_budget_usd,
        }

    def get_guild_summary(self, guild_id: int) -> Dict[str, Any]:
        """Get cost summary for a specific guild today."""
        today = self._today_key()
        spent = self._daily_spend[guild_id][today]
        return {
            "guild_id": guild_id,
            "date": today,
            "spent_usd": round(spent, 6),
            "remaining_usd": round(max(0.0, self._daily_budget_usd - spent), 6),
            "budget_usd": self._daily_budget_usd,
        }

    # ============================================================
    # POSTGRES PERSISTENCE
    # ============================================================

    async def _persist_to_db(
        self,
        guild_id: int,
        user_id: str,
        agent_name: str,
        provider: str,
        input_tokens: int,
        output_tokens: int,
        cost_usd: float,
    ) -> None:
        """
        Insert cost record into Postgres `cost_log` table.
        Schema:
            CREATE TABLE cost_log (
                id SERIAL PRIMARY KEY,
                guild_id BIGINT NOT NULL,
                user_id TEXT NOT NULL,
                agent_name TEXT NOT NULL,
                provider TEXT NOT NULL,
                input_tokens INT NOT NULL,
                output_tokens INT NOT NULL,
                cost_usd DOUBLE PRECISION NOT NULL,
                created_at TIMESTAMPTZ DEFAULT NOW()
            );
        """
        try:
            await self._db.execute(
                """
                INSERT INTO cost_log
                    (guild_id, user_id, agent_name, provider, input_tokens, output_tokens, cost_usd)
                VALUES ($1, $2, $3, $4, $5, $6, $7)
                """,
                guild_id, user_id, agent_name, provider,
                input_tokens, output_tokens, cost_usd,
            )
        except Exception as e:
            logger.error(f"Failed to persist cost log: {e}")

    # ============================================================
    # HELPERS
    # ============================================================

    def _calculate_cost(self, provider: str, input_tokens: int, output_tokens: int) -> float:
        """Calculate USD cost from token counts using the cost table."""
        costs = COST_TABLE.get(provider, {"input": 0.0, "output": 0.0})
        input_cost = (input_tokens / 1_000_000) * costs["input"]
        output_cost = (output_tokens / 1_000_000) * costs["output"]
        return input_cost + output_cost

    def _today_key(self) -> str:
        """Get today's date string for daily bucketing."""
        return datetime.now(timezone.utc).strftime("%Y-%m-%d")

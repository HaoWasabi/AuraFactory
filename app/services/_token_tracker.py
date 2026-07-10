"""Token usage tracker — records LLM token counts for cost observability.

Records per-request token usage into the audit_log table.
This is fire-and-forget — errors are logged but never propagated.
"""
import logging
from typing import Optional

logger = logging.getLogger(__name__)


async def record_token_usage(
    db,
    guild_id: int,
    user_id: int,
    usage,
    provider: str = "",
    phase: str = "planning",
) -> None:
    """Record LLM token usage as an audit log entry.

    Args:
        db: Database instance.
        guild_id: Guild this request belongs to.
        user_id: User who triggered the request.
        usage: LLMResponse.usage object with prompt_tokens and completion_tokens.
               If None or both counts are 0, recording is skipped.
        provider: LLM provider name (e.g. "gemini", "bedrock").
        phase: Which phase consumed tokens ("planning", "reflect", "assemble", "replan").

    This function never raises — DB errors are logged as warnings.
    """
    if not db or not usage:
        return

    tokens_in = getattr(usage, "prompt_tokens", 0) or 0
    tokens_out = getattr(usage, "completion_tokens", 0) or 0

    if tokens_in == 0 and tokens_out == 0:
        return

    try:
        await db.execute(
            """INSERT INTO audit_log (guild_id, user_id, tool_name, tool_params, risk_level, success, duration_ms)
               VALUES ($1, $2, $3, $4::jsonb, $5, $6, $7)""",
            guild_id,
            user_id,
            f"llm.{phase}",
            f'{{"provider":"{provider}","tokens_in":{tokens_in},"tokens_out":{tokens_out}}}',
            "low",
            True,
            0,
        )
        logger.debug(
            "Token usage [%s/%s]: in=%d out=%d (guild=%d)",
            provider, phase, tokens_in, tokens_out, guild_id,
        )
    except Exception as e:
        logger.warning("Failed to record token usage: %s", e)

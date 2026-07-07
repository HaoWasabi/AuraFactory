"""Token usage tracker — records LLM token counts into the requests table."""
import logging
import uuid
from typing import Optional

logger = logging.getLogger(__name__)


async def record_token_usage(
    db,
    request_id: Optional[str],
    usage,
    provider: str = "",
) -> None:
    """Update the requests table with LLM token usage for a given request.
    
    Args:
        db: Database instance.
        request_id: UUID string of the request to update. If None, does nothing.
        usage: LLMResponse.usage object with prompt_tokens and completion_tokens.
               If None or both counts are 0, update is skipped.
        provider: LLM provider name (e.g. "gemini", "bedrock").
    
    This function never raises — DB errors are logged as warnings.
    """
    if not request_id or not usage:
        return

    tokens_in = getattr(usage, "prompt_tokens", 0) or 0
    tokens_out = getattr(usage, "completion_tokens", 0) or 0

    if tokens_in == 0 and tokens_out == 0:
        return

    try:
        await db.execute(
            """UPDATE requests
               SET llm_tokens_in = $2, llm_tokens_out = $3, llm_provider = $4
               WHERE id = $1""",
            uuid.UUID(request_id),
            tokens_in,
            tokens_out,
            provider or "",
        )
    except Exception as e:
        logger.warning(
            "Failed to update token usage for request %s: %s",
            request_id,
            e,
        )

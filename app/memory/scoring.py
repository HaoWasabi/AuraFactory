# app/memory/scoring.py
"""
Relevance scoring formula for memory retrieval.
S(m) = α·similarity + β·recency_score + δ·importance
"""
import math
from datetime import datetime


# Weights
ALPHA = 0.5  # Semantic relevance (most important)
BETA = 0.3   # Recency preference
DELTA = 0.2  # Importance boost

# Recency half-life
HALF_LIFE_HOURS = 168  # 1 week


def score_memory(
    similarity: float,
    timestamp: datetime,
    importance: float = 0.5,
    now: datetime = None,
) -> float:
    """
    Calculate composite relevance score for a memory.

    Args:
        similarity: Cosine similarity score (0-1)
        timestamp: When the memory was created
        importance: Memory importance (0-1)
        now: Current time (default: utcnow)

    Returns:
        Composite score (0-1)
    """
    if now is None:
        now = datetime.utcnow()

    # Recency score: exponential decay with half-life
    hours_ago = (now - timestamp).total_seconds() / 3600
    recency_score = math.exp(-hours_ago / HALF_LIFE_HOURS)

    # Composite score
    score = ALPHA * similarity + BETA * recency_score + DELTA * importance

    return min(max(score, 0.0), 1.0)  # Clamp to [0, 1]


def compute_importance(
    has_tool_calls: bool = False,
    is_error: bool = False,
    is_user_explicit: bool = False,
    message_length: int = 0,
) -> float:
    """
    Estimate importance of a memory at storage time.
    Higher importance = retained longer and ranked higher.
    """
    base = 0.3

    if is_user_explicit:
        base += 0.4  # User-confirmed facts are very important
    if has_tool_calls:
        base += 0.2  # Actions taken are memorable
    if is_error:
        base += 0.1  # Errors are important to remember (avoid repeating)
    if message_length > 200:
        base += 0.05  # Longer interactions slightly more important

    return min(base, 1.0)

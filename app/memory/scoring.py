"""ImportanceScoring — heuristic-based message importance scorer.

Scores messages from 0.0 to 1.0 based on heuristic signals like
length, question marks, urgency keywords, and command patterns.
"""

from __future__ import annotations

import logging
import re

logger = logging.getLogger(__name__)

# Keywords that signal high importance
URGENCY_KEYWORDS: set[str] = {
    "important",
    "urgent",
    "critical",
    "asap",
    "immediately",
    "emergency",
    "deadline",
    "priority",
    "breaking",
    "alert",
}

# Keywords that signal moderate importance
ACTION_KEYWORDS: set[str] = {
    "please",
    "need",
    "help",
    "fix",
    "update",
    "change",
    "create",
    "delete",
    "configure",
    "setup",
    "deploy",
    "migrate",
}

# Command-like patterns (e.g., /command, !command, .command)
COMMAND_PATTERN: re.Pattern[str] = re.compile(r"^[/!.]\w+", re.MULTILINE)

# Question pattern
QUESTION_PATTERN: re.Pattern[str] = re.compile(r"\?")

# Mention patterns (@everyone, @here, @role)
MENTION_PATTERN: re.Pattern[str] = re.compile(r"@(everyone|here|\w+)")

# Length thresholds
SHORT_MSG_THRESHOLD: int = 20
MEDIUM_MSG_THRESHOLD: int = 100
LONG_MSG_THRESHOLD: int = 500


class ImportanceScoring:
    """Scores message importance using heuristic signals.

    Returns a float between 0.0 (trivial) and 1.0 (critical).
    """

    def score_message(self, content: str) -> float:
        """Score a message's importance from 0.0 to 1.0.

        Heuristics applied:
        - Message length (longer = more information)
        - Question marks (questions need answers)
        - Urgency keywords (important, urgent, etc.)
        - Action keywords (please, need, help, etc.)
        - Command-like patterns (/cmd, !cmd)
        - Mentions (@everyone, @here)

        Args:
            content: Message text content.

        Returns:
            Importance score between 0.0 and 1.0.
        """
        if not content or not content.strip():
            return 0.0

        score: float = 0.0
        content_lower = content.lower()
        words = set(content_lower.split())

        # Length scoring (0.0 - 0.2)
        length = len(content)
        if length > LONG_MSG_THRESHOLD:
            score += 0.2
        elif length > MEDIUM_MSG_THRESHOLD:
            score += 0.15
        elif length > SHORT_MSG_THRESHOLD:
            score += 0.05

        # Question marks (0.0 - 0.15)
        question_count = len(QUESTION_PATTERN.findall(content))
        if question_count > 0:
            score += min(0.15, question_count * 0.05)

        # Urgency keywords (0.0 - 0.3)
        urgency_hits = words & URGENCY_KEYWORDS
        if urgency_hits:
            score += min(0.3, len(urgency_hits) * 0.15)

        # Action keywords (0.0 - 0.15)
        action_hits = words & ACTION_KEYWORDS
        if action_hits:
            score += min(0.15, len(action_hits) * 0.05)

        # Command patterns (0.0 - 0.1)
        if COMMAND_PATTERN.search(content):
            score += 0.1

        # Mentions (0.0 - 0.15)
        mention_count = len(MENTION_PATTERN.findall(content))
        if mention_count > 0:
            score += min(0.15, mention_count * 0.05)

        # Clamp to [0.0, 1.0]
        final_score = min(1.0, max(0.0, score))

        logger.debug(
            "Scored message (len=%d): %.2f [urgency=%d, action=%d, questions=%d]",
            length,
            final_score,
            len(urgency_hits),
            len(action_hits),
            question_count,
        )
        return final_score

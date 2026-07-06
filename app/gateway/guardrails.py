# app/gateway/guardrails.py
"""
Gateway — Heuristic-based prompt injection detection.
Phase 1: Regex patterns for common injection attacks.
Phase 2: Replace with Bedrock Guardrails (flag: ENABLE_BEDROCK_GUARDRAILS).
"""
import os
import re
import logging
from typing import Tuple

logger = logging.getLogger(__name__)

# Feature flag for Phase 2 Bedrock Guardrails
ENABLE_BEDROCK_GUARDRAILS: bool = os.getenv("ENABLE_BEDROCK_GUARDRAILS", "false").lower() == "true"

# ============================================================
# INJECTION PATTERNS — ordered by severity
# ============================================================

_INJECTION_PATTERNS: list[Tuple[str, str]] = [
    # Direct instruction override
    (r"ignore\s+(previous|above|all|prior)\s+(instructions|prompts|rules|directives)", "instruction_override"),
    (r"disregard\s+(your|all|the|any)\s+(instructions|rules|guidelines|constraints)", "instruction_override"),
    (r"override\s+(your|system|all)\s+(prompt|instructions|rules)", "instruction_override"),
    (r"forget\s+(everything|your\s+instructions|all\s+rules|what\s+you)", "instruction_override"),
    (r"new\s+instructions?\s*:", "instruction_override"),

    # Role manipulation
    (r"you\s+are\s+now\s+(a|an|the)\s+", "role_manipulation"),
    (r"pretend\s+(to\s+be|you\s+are|you're)", "role_manipulation"),
    (r"act\s+as\s+(if|a|an|though)", "role_manipulation"),
    (r"from\s+now\s+on\s+you\s+(are|will|must)", "role_manipulation"),
    (r"your\s+new\s+(role|identity|persona)\s+is", "role_manipulation"),

    # System prompt extraction
    (r"(show|reveal|print|output|repeat)\s+(your|the|full)\s+(system\s+)?prompt", "prompt_extraction"),
    (r"what\s+(is|are)\s+your\s+(system\s+)?(prompt|instructions|rules)", "prompt_extraction"),
    (r"(display|echo|dump)\s+(system|hidden|secret)\s+(prompt|instructions)", "prompt_extraction"),

    # Delimiter injection
    (r"\[system\]", "delimiter_injection"),
    (r"<\|system\|>", "delimiter_injection"),
    (r"</?(system|assistant|user)>", "delimiter_injection"),
    (r"system\s*:\s*(you|ignore|override|new)", "delimiter_injection"),
    (r"###\s*(system|instruction|new\s+prompt)", "delimiter_injection"),

    # Encoding evasion
    (r"base64\s*(decode|encode)\s*:", "encoding_evasion"),
    (r"rot13\s*:", "encoding_evasion"),
    (r"hex\s*(decode|encode)\s*:", "encoding_evasion"),

    # DAN / jailbreak patterns
    (r"(DAN|do\s+anything\s+now)", "jailbreak"),
    (r"developer\s+mode\s+(enabled|on|activated)", "jailbreak"),
    (r"(enable|activate|enter)\s+(god|sudo|admin|root)\s+mode", "jailbreak"),
]

# Pre-compile all patterns for performance
_COMPILED_PATTERNS: list[Tuple[re.Pattern, str]] = [
    (re.compile(pattern, re.IGNORECASE), category)
    for pattern, category in _INJECTION_PATTERNS
]


class Guardrails:
    """
    Heuristic-based content safety checker.
    Detects prompt injection attempts using regex patterns.

    Phase 1: Local regex detection.
    Phase 2: Bedrock Guardrails API (when ENABLE_BEDROCK_GUARDRAILS=true).
    """

    def __init__(self) -> None:
        self._patterns = _COMPILED_PATTERNS
        self._detection_count: int = 0

    def check(self, content: str) -> Tuple[bool, str]:
        """
        Check if content is safe from prompt injection attempts.

        Args:
            content: The user message content to check.

        Returns:
            (safe, reason)
            - safe=True, reason="" if content is clean.
            - safe=False, reason="..." if injection detected.
        """
        if not content or not content.strip():
            return True, ""

        # Phase 2: Use Bedrock Guardrails if enabled
        if ENABLE_BEDROCK_GUARDRAILS:
            return self._check_bedrock(content)

        # Phase 1: Heuristic regex matching
        return self._check_heuristic(content)

    def _check_heuristic(self, content: str) -> Tuple[bool, str]:
        """Run regex patterns against content."""
        for pattern, category in self._patterns:
            match = pattern.search(content)
            if match:
                self._detection_count += 1
                matched_text = match.group()[:80]
                reason = (
                    f"Prompt injection detected [{category}]: "
                    f"'{matched_text}'"
                )
                logger.warning(f"Guardrails blocked: {reason}")
                return False, reason

        return True, ""

    def _check_bedrock(self, content: str) -> Tuple[bool, str]:
        """
        Phase 2 placeholder: Bedrock Guardrails API call.
        When ENABLE_BEDROCK_GUARDRAILS=true, this will call the Bedrock
        Guardrails service for more sophisticated content filtering.
        For now, falls back to heuristic.
        """
        logger.info("Bedrock Guardrails not yet implemented, falling back to heuristic")
        return self._check_heuristic(content)

    @property
    def detection_count(self) -> int:
        """Total number of injection attempts detected since startup."""
        return self._detection_count

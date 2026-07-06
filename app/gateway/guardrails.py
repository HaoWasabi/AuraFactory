"""
Gateway — Prompt injection detection & input sanitization.
"""
import re
from typing import Tuple

# Known prompt injection patterns
_INJECTION_PATTERNS = [
    r"ignore\s+(previous|above|all)\s+(instructions|prompts|rules)",
    r"disregard\s+(your|all|the)\s+(instructions|rules|guidelines)",
    r"you\s+are\s+now\s+(a|an|the)\s+",
    r"pretend\s+(to\s+be|you\s+are)",
    r"act\s+as\s+(if|a|an)",
    r"override\s+(your|system|all)\s+(prompt|instructions)",
    r"forget\s+(everything|your\s+instructions|what)",
    r"new\s+instructions?\s*:",
    r"system\s*:\s*you",
    r"\[system\]",
    r"<\|system\|>",
    r"</?(system|assistant|user)>",
]

_compiled = [re.compile(p, re.IGNORECASE) for p in _INJECTION_PATTERNS]


def check_injection(text: str) -> Tuple[bool, str]:
    """
    Check if input contains prompt injection attempts.
    
    Returns:
        (is_safe, reason) — True if safe, False if injection detected.
    """
    for pattern in _compiled:
        match = pattern.search(text)
        if match:
            return False, f"Phát hiện prompt injection: '{match.group()[:50]}'"
    return True, ""


def sanitize_input(text: str, max_length: int = 2000) -> str:
    """
    Sanitize user input — trim, limit length, remove control characters.
    """
    # Remove null bytes and control chars (except newline/tab)
    text = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]', '', text)
    # Trim and limit
    text = text.strip()[:max_length]
    return text

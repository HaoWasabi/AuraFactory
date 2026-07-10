"""Base LLM provider interface."""
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class LLMQuotaError(Exception):
    """Raised when the LLM API key is exhausted, invalid, or rate-limited.

    Attributes:
        reason: Short machine-readable reason code.
            - "quota_exhausted"  — daily/monthly free quota used up
            - "rate_limited"     — too many requests per minute
            - "invalid_key"      — API key rejected (wrong key / revoked)
            - "permission_denied"— key exists but lacks access to this model
    """
    def __init__(self, reason: str, original: Exception = None):
        self.reason = reason
        self.original = original
        super().__init__(reason)


@dataclass
class ToolCall:
    """Represents a tool/function call returned by the LLM."""
    name: str
    arguments: Dict[str, Any] = field(default_factory=dict)


@dataclass
class UsageStats:
    """Token usage statistics from an LLM response."""
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0


@dataclass
class LLMResponse:
    """Standardized response from any LLM provider."""
    content: str = ""
    tool_calls: List[ToolCall] = field(default_factory=list)
    usage: UsageStats = field(default_factory=UsageStats)

    @property
    def has_tool_calls(self) -> bool:
        return len(self.tool_calls) > 0


class BaseLLM(ABC):
    """Abstract base class for all LLM providers."""

    def __init__(self, model: str = "", api_key: str = "") -> None:
        self.model = model
        self.api_key = api_key

    @abstractmethod
    async def generate(
        self,
        messages: List[Dict[str, str]],
        system_prompt: Optional[str] = None,
        tools: Optional[List[Dict[str, Any]]] = None,
        temperature: float = 0.7,
        max_tokens: int = 4096,
        **kwargs,
    ) -> LLMResponse:
        """Generate a response from the LLM.

        Args:
            messages: Chat messages [{role, content}].
            system_prompt: Optional system instruction.
            tools: Optional tool definitions for function calling.
            temperature: Sampling temperature.
            max_tokens: Max tokens to generate.

        Returns:
            LLMResponse with content, tool_calls, usage.
        """
        ...

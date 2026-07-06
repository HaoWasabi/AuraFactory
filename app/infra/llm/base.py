"""Base LLM provider interface."""

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


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
        """Check if the response contains tool calls."""
        return len(self.tool_calls) > 0


class BaseLLM(ABC):
    """Abstract base class for all LLM providers."""

    def __init__(self, model: str = "", api_key: str = "") -> None:
        self.model = model
        self.api_key = api_key

    @abstractmethod
    async def generate(
        self,
        prompt: str,
        tools: Optional[List[Dict[str, Any]]] = None,
        temperature: float = 0.7,
    ) -> LLMResponse:
        """Generate a response from the LLM.

        Args:
            prompt: The input prompt text.
            tools: Optional list of tool definitions for function calling.
            temperature: Sampling temperature (0.0 to 1.0).

        Returns:
            LLMResponse with content, tool_calls, and usage stats.
        """
        ...

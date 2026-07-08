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
            tools: Optional tool definitions in standard JSON Schema format:
                [
                    {
                        "name": "tool_name",
                        "description": "What it does",
                        "parameters": {
                            "properties": {"param": {"type": "string", "description": "..."}},
                            "required": ["param"]
                        }
                    }
                ]
                Each provider converts this to its native format internally.
                Supported types: string, number, integer, boolean, array, object.
                Array type MUST include "items": {"type": "..."}.
            temperature: Sampling temperature.
            max_tokens: Max tokens to generate.

        Returns:
            LLMResponse with content, tool_calls, usage.
        """
        ...

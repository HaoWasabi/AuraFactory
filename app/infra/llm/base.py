# app/infra/llm/base.py
"""
LLM Provider interface — all providers implement this.
Backward-compatible with existing app/providers/base.py signature.
"""
from abc import ABC, abstractmethod
from typing import List, Dict, Any, Optional
from dataclasses import dataclass


@dataclass
class LLMMessage:
    """Structured message for LLM conversations."""
    role: str       # "system" | "user" | "assistant"
    content: str


@dataclass
class LLMResponse:
    """Standardized LLM response across all providers."""
    content: str
    model: str
    input_tokens: int = 0
    output_tokens: int = 0
    latency_ms: float = 0.0
    finish_reason: str = "stop"  # "stop" | "length" | "error"
    raw_response: Any = None


class LLMProvider(ABC):
    """
    Abstract interface for all LLM providers.
    Phase 1: Gemini, Groq, OpenRouter, Ollama.
    Phase 2: Add AWS Bedrock — same ABC.
    """

    @abstractmethod
    async def generate(
        self,
        messages: List[Dict[str, str]],
        system_prompt: str = "",
        temperature: float = 0.3,
        max_tokens: int = 4096,
        tools: Optional[List[Dict]] = None,
    ) -> LLMResponse:
        """Generate a completion from message history."""
        ...

    @abstractmethod
    async def generate_with_tools(
        self,
        messages: List[Dict[str, str]],
        system_prompt: str,
        tools: List[Dict],
        temperature: float = 0.3,
    ) -> Dict[str, Any]:
        """Generate with function calling / tool use."""
        ...

    @property
    @abstractmethod
    def model_name(self) -> str:
        """Return the model identifier string."""
        ...

    async def count_tokens(self, text: str) -> int:
        """Estimate token count. Default: rough word-based estimate."""
        return len(text.split()) * 4 // 3  # ~1.33 tokens per word

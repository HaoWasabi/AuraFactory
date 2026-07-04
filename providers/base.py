# providers/base.py
"""
Well-Architected Principle: Consider evolutionary architectures
Agentic AI Lens Principle: Ground autonomous behavior in explicit contracts

Interface chuẩn cho mọi LLM provider.
Phase 1: GeminiProvider (open-source/free)
Phase 2: BedrockProvider (AWS) — chỉ cần implement class mới, KHÔNG đổi agent code
"""
from abc import ABC, abstractmethod
from typing import List, Dict, Any, Optional
from dataclasses import dataclass


@dataclass
class LLMResponse:
    """Contract chuẩn cho mọi LLM response"""
    content: str
    model: str
    input_tokens: int = 0
    output_tokens: int = 0
    latency_ms: float = 0.0
    raw_response: Any = None  # Giữ response gốc nếu cần debug


class LLMProvider(ABC):
    """
    Abstract base — mọi provider (Gemini, Bedrock, OpenAI) implement interface này.
    Agent code chỉ gọi qua interface, không biết bên dưới là gì.
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
        """
        Gọi LLM với messages format chuẩn.
        
        messages: [{"role": "user"|"assistant", "content": "..."}]
        tools: Tool definitions (JSON Schema) nếu cần function calling
        """
        ...
    
    @abstractmethod
    async def generate_with_tools(
        self,
        messages: List[Dict[str, str]],
        system_prompt: str,
        tools: List[Dict],
        temperature: float = 0.3,
    ) -> Dict[str, Any]:
        """
        Generate + tự động parse tool calls.
        Returns: {"content": str, "tool_calls": [{"name": str, "arguments": dict}]}
        """
        ...
    
    @property
    @abstractmethod
    def model_name(self) -> str:
        """Tên model đang dùng (for tracing/cost tracking)"""
        ...

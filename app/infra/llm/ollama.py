"""Ollama LLM provider using httpx to localhost:11434."""

import json
import logging
from typing import Any, Dict, List, Optional

import httpx

from .base import BaseLLM, LLMResponse, ToolCall, UsageStats

logger = logging.getLogger(__name__)

OLLAMA_BASE_URL = "http://localhost:11434"


class OllamaLLM(BaseLLM):
    """Ollama local LLM provider."""

    def __init__(self, model: str = "llama3.1", api_key: str = "") -> None:
        super().__init__(model=model, api_key=api_key)
        self._base_url = OLLAMA_BASE_URL
        logger.info("OllamaLLM initialized (model=%s)", self.model)

    async def generate(
        self,
        prompt: str,
        tools: Optional[List[Dict[str, Any]]] = None,
        temperature: float = 0.7,
    ) -> LLMResponse:
        """Generate a response using Ollama."""
        payload: Dict[str, Any] = {
            "model": self.model,
            "messages": [{"role": "user", "content": prompt}],
            "stream": False,
            "options": {"temperature": temperature},
        }

        if tools:
            payload["tools"] = self._convert_tools(tools)

        try:
            async with httpx.AsyncClient(timeout=120.0) as client:
                response = await client.post(
                    f"{self._base_url}/api/chat",
                    json=payload,
                )
                response.raise_for_status()
                data = response.json()
                return self._parse_response(data)

        except httpx.ConnectError:
            logger.error("Cannot connect to Ollama at %s. Is it running?", self._base_url)
            raise ConnectionError(f"Ollama not available at {self._base_url}")
        except Exception as e:
            logger.error("Ollama generation failed: %s", e)
            raise

    def _convert_tools(self, tools: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Convert generic tool definitions to Ollama format."""
        converted = []
        for tool in tools:
            converted.append({
                "type": "function",
                "function": {
                    "name": tool.get("name", ""),
                    "description": tool.get("description", ""),
                    "parameters": tool.get("parameters", {}),
                },
            })
        return converted

    def _parse_response(self, data: Dict[str, Any]) -> LLMResponse:
        """Parse Ollama JSON response into standardized LLMResponse."""
        message = data.get("message", {})
        content = message.get("content", "") or ""
        tool_calls: List[ToolCall] = []

        raw_tool_calls = message.get("tool_calls", [])
        for tc in raw_tool_calls:
            func = tc.get("function", {})
            tool_calls.append(
                ToolCall(
                    name=func.get("name", ""),
                    arguments=func.get("arguments", {}),
                )
            )

        # Ollama provides eval_count and prompt_eval_count
        usage = UsageStats(
            prompt_tokens=data.get("prompt_eval_count", 0),
            completion_tokens=data.get("eval_count", 0),
            total_tokens=data.get("prompt_eval_count", 0) + data.get("eval_count", 0),
        )

        return LLMResponse(content=content, tool_calls=tool_calls, usage=usage)

"""OpenRouter LLM provider using httpx (OpenAI-compatible endpoint)."""

import json
import logging
from typing import Any, Dict, List, Optional

import httpx

from .base import BaseLLM, LLMResponse, ToolCall, UsageStats

logger = logging.getLogger(__name__)

OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1/chat/completions"


class OpenRouterLLM(BaseLLM):
    """OpenRouter LLM provider (OpenAI-compatible API)."""

    def __init__(self, model: str = "openai/gpt-4o", api_key: str = "") -> None:
        super().__init__(model=model, api_key=api_key)
        self._base_url = OPENROUTER_BASE_URL
        logger.info("OpenRouterLLM initialized (model=%s)", self.model)

    async def generate(
        self,
        prompt: str,
        tools: Optional[List[Dict[str, Any]]] = None,
        temperature: float = 0.7,
    ) -> LLMResponse:
        """Generate a response using OpenRouter."""
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://aurafactory.app",
            "X-Title": "AuraFactory",
        }

        payload: Dict[str, Any] = {
            "model": self.model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": temperature,
        }

        if tools:
            payload["tools"] = self._convert_tools(tools)
            payload["tool_choice"] = "auto"

        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
                response = await client.post(self._base_url, headers=headers, json=payload)
                response.raise_for_status()
                data = response.json()
                return self._parse_response(data)

        except httpx.HTTPStatusError as e:
            logger.error("OpenRouter HTTP error %d: %s", e.response.status_code, e.response.text)
            raise
        except Exception as e:
            logger.error("OpenRouter generation failed: %s", e)
            raise

    def _convert_tools(self, tools: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Convert generic tool definitions to OpenAI-compatible format."""
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
        """Parse OpenRouter JSON response into standardized LLMResponse."""
        choices = data.get("choices", [])
        if not choices:
            return LLMResponse()

        message = choices[0].get("message", {})
        content = message.get("content", "") or ""
        tool_calls: List[ToolCall] = []

        raw_tool_calls = message.get("tool_calls", [])
        for tc in raw_tool_calls:
            func = tc.get("function", {})
            args = func.get("arguments", "{}")
            tool_calls.append(
                ToolCall(
                    name=func.get("name", ""),
                    arguments=json.loads(args) if isinstance(args, str) else args,
                )
            )

        usage_data = data.get("usage", {})
        usage = UsageStats(
            prompt_tokens=usage_data.get("prompt_tokens", 0),
            completion_tokens=usage_data.get("completion_tokens", 0),
            total_tokens=usage_data.get("total_tokens", 0),
        )

        return LLMResponse(content=content, tool_calls=tool_calls, usage=usage)

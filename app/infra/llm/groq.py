"""Groq LLM provider using the groq SDK."""

import asyncio
import logging
from typing import Any, Dict, List, Optional

from groq import Groq

from .base import BaseLLM, LLMResponse, ToolCall, UsageStats

logger = logging.getLogger(__name__)


class GroqLLM(BaseLLM):
    """Groq LLM provider for fast inference."""

    def __init__(self, model: str = "llama-3.1-70b-versatile", api_key: str = "") -> None:
        super().__init__(model=model, api_key=api_key)
        self._client = Groq(api_key=self.api_key)
        logger.info("GroqLLM initialized (model=%s)", self.model)

    async def generate(
        self,
        prompt: str,
        tools: Optional[List[Dict[str, Any]]] = None,
        temperature: float = 0.7,
    ) -> LLMResponse:
        """Generate a response using Groq."""
        messages = [{"role": "user", "content": prompt}]

        kwargs: Dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
        }

        if tools:
            kwargs["tools"] = self._convert_tools(tools)
            kwargs["tool_choice"] = "auto"

        try:
            response = await asyncio.to_thread(
                self._client.chat.completions.create, **kwargs
            )
            return self._parse_response(response)

        except Exception as e:
            logger.error("Groq generation failed: %s", e)
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

    def _parse_response(self, response: Any) -> LLMResponse:
        """Parse Groq response into standardized LLMResponse."""
        choice = response.choices[0]
        message = choice.message

        content = message.content or ""
        tool_calls: List[ToolCall] = []

        if message.tool_calls:
            import json
            for tc in message.tool_calls:
                tool_calls.append(
                    ToolCall(
                        name=tc.function.name,
                        arguments=json.loads(tc.function.arguments) if tc.function.arguments else {},
                    )
                )

        usage = UsageStats(
            prompt_tokens=response.usage.prompt_tokens,
            completion_tokens=response.usage.completion_tokens,
            total_tokens=response.usage.total_tokens,
        )

        return LLMResponse(content=content, tool_calls=tool_calls, usage=usage)

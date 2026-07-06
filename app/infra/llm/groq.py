# app/infra/llm/groq.py
"""
Groq LLM Provider — Ultra-fast inference.
Migrated from app/providers/groq.py — logic preserved.
"""
import time
import json
from typing import List, Dict, Any, Optional

import aiohttp

from app.infra.llm.base import LLMProvider, LLMResponse


class GroqProvider(LLMProvider):
    """Groq Cloud API implementation (OpenAI-compatible)."""

    BASE_URL = "https://api.groq.com/openai/v1"

    def __init__(self, api_key: str, model_id: str = "llama-3.3-70b-versatile"):
        self._api_key = api_key
        self._model_id = model_id

    @property
    def model_name(self) -> str:
        return self._model_id

    async def generate(
        self,
        messages: List[Dict[str, str]],
        system_prompt: str = "",
        temperature: float = 0.3,
        max_tokens: int = 4096,
        tools: Optional[List[Dict]] = None,
    ) -> LLMResponse:
        start = time.time()

        payload_messages = []
        if system_prompt:
            payload_messages.append({"role": "system", "content": system_prompt})
        payload_messages.extend(messages)

        payload = {
            "model": self._model_id,
            "messages": payload_messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }

        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }

        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"{self.BASE_URL}/chat/completions",
                json=payload,
                headers=headers,
            ) as resp:
                data = await resp.json()

                if resp.status != 200:
                    error_msg = data.get("error", {}).get("message", str(data))
                    raise Exception(f"Groq API error ({resp.status}): {error_msg}")

        choice = data["choices"][0]
        usage = data.get("usage", {})

        return LLMResponse(
            content=choice["message"]["content"] or "",
            model=self._model_id,
            input_tokens=usage.get("prompt_tokens", 0),
            output_tokens=usage.get("completion_tokens", 0),
            latency_ms=(time.time() - start) * 1000,
            raw_response=data,
        )

    async def generate_with_tools(
        self,
        messages: List[Dict[str, str]],
        system_prompt: str,
        tools: List[Dict],
        temperature: float = 0.3,
    ) -> Dict[str, Any]:
        start = time.time()

        payload_messages = []
        if system_prompt:
            payload_messages.append({"role": "system", "content": system_prompt})
        payload_messages.extend(messages)

        openai_tools = []
        for tool in tools:
            openai_tools.append({
                "type": "function",
                "function": {
                    "name": tool["name"],
                    "description": tool.get("description", ""),
                    "parameters": tool.get("parameters", {"type": "object", "properties": {}}),
                },
            })

        payload = {
            "model": self._model_id,
            "messages": payload_messages,
            "tools": openai_tools,
            "tool_choice": "auto",
            "temperature": temperature,
        }

        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }

        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"{self.BASE_URL}/chat/completions",
                json=payload,
                headers=headers,
            ) as resp:
                data = await resp.json()

                if resp.status != 200:
                    error_msg = data.get("error", {}).get("message", str(data))
                    raise Exception(f"Groq API error ({resp.status}): {error_msg}")

        choice = data["choices"][0]["message"]
        tool_calls = []

        if choice.get("tool_calls"):
            for tc in choice["tool_calls"]:
                tool_calls.append({
                    "name": tc["function"]["name"],
                    "arguments": json.loads(tc["function"]["arguments"])
                    if tc["function"]["arguments"]
                    else {},
                })

        return {
            "content": choice.get("content", "") or "",
            "tool_calls": tool_calls,
            "latency_ms": (time.time() - start) * 1000,
            "model": self._model_id,
        }

    async def is_available(self) -> bool:
        """Check if provider is reachable and has quota."""
        try:
            headers = {
                "Authorization": f"Bearer {self._api_key}",
                "Content-Type": "application/json",
            }
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    f"{self.BASE_URL}/models",
                    headers=headers,
                    timeout=aiohttp.ClientTimeout(total=5),
                ) as resp:
                    return resp.status == 200
        except Exception:
            return False

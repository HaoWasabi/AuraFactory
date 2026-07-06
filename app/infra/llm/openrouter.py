# app/infra/llm/openrouter.py
"""
OpenRouter LLM Provider — Multi-model aggregator.
Migrated from app/providers/openrouter.py — logic preserved.
"""
import time
import json
from typing import List, Dict, Any, Optional

import aiohttp

from app.infra.llm.base import LLMProvider, LLMResponse


class OpenRouterProvider(LLMProvider):
    """OpenRouter API implementation (OpenAI-compatible)."""

    BASE_URL = "https://openrouter.ai/api/v1"

    FREE_MODELS = [
        "meta-llama/llama-3.1-8b-instruct:free",
        "mistralai/mistral-7b-instruct:free",
        "huggingfaceh4/zephyr-7b-beta:free",
        "google/gemma-2-9b-it:free",
    ]

    def __init__(
        self,
        api_key: str,
        model_id: str = "meta-llama/llama-3.1-8b-instruct:free",
        app_name: str = "AuraFactory",
    ):
        self._api_key = api_key
        self._model_id = model_id
        self._app_name = app_name

    @property
    def model_name(self) -> str:
        return self._model_id

    def _get_headers(self) -> Dict[str, str]:
        return {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://github.com/AuraFactory",
            "X-Title": self._app_name,
        }

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

        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"{self.BASE_URL}/chat/completions",
                json=payload,
                headers=self._get_headers(),
            ) as resp:
                data = await resp.json()

                if resp.status != 200:
                    error_msg = data.get("error", {}).get("message", str(data))
                    raise Exception(f"OpenRouter API error ({resp.status}): {error_msg}")

        choice = data["choices"][0]
        usage = data.get("usage", {})

        return LLMResponse(
            content=choice["message"]["content"] or "",
            model=data.get("model", self._model_id),
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

        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"{self.BASE_URL}/chat/completions",
                json=payload,
                headers=self._get_headers(),
            ) as resp:
                data = await resp.json()

                if resp.status != 200:
                    error_msg = data.get("error", {}).get("message", str(data))
                    raise Exception(f"OpenRouter API error ({resp.status}): {error_msg}")

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
            "model": data.get("model", self._model_id),
        }

    async def is_available(self) -> bool:
        """Check rate limit status via OpenRouter."""
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    f"{self.BASE_URL}/auth/key",
                    headers=self._get_headers(),
                    timeout=aiohttp.ClientTimeout(total=5),
                ) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        limit = data.get("data", {}).get("limit")
                        usage = data.get("data", {}).get("usage", 0)
                        if limit is None:
                            return True
                        return usage < limit
                    return False
        except Exception:
            return False

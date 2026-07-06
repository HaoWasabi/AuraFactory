# app/infra/llm/ollama.py
"""
Ollama LLM Provider — Local inference, completely free.
Migrated from app/providers/ollama.py — logic preserved.
"""
import time
import json
from typing import List, Dict, Any, Optional

import aiohttp

from app.infra.llm.base import LLMProvider, LLMResponse


class OllamaProvider(LLMProvider):
    """Ollama local inference implementation."""

    def __init__(
        self,
        base_url: str = "http://localhost:11434",
        model_id: str = "qwen2.5:7b",
    ):
        self._base_url = base_url.rstrip("/")
        self._model_id = model_id

    @property
    def model_name(self) -> str:
        return f"ollama/{self._model_id}"

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
            "stream": False,
            "options": {
                "temperature": temperature,
                "num_predict": max_tokens,
            },
        }

        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"{self._base_url}/api/chat",
                json=payload,
                timeout=aiohttp.ClientTimeout(total=120),
            ) as resp:
                if resp.status != 200:
                    text = await resp.text()
                    raise Exception(f"Ollama error ({resp.status}): {text}")
                data = await resp.json()

        message = data.get("message", {})
        input_tokens = data.get("prompt_eval_count", 0)
        output_tokens = data.get("eval_count", 0)

        return LLMResponse(
            content=message.get("content", ""),
            model=self._model_id,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
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
        """Ollama 0.4+ supports native tool calling with fallback."""
        start = time.time()

        payload_messages = []
        if system_prompt:
            payload_messages.append({"role": "system", "content": system_prompt})
        payload_messages.extend(messages)

        ollama_tools = []
        for tool in tools:
            ollama_tools.append({
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
            "tools": ollama_tools,
            "stream": False,
            "options": {"temperature": temperature},
        }

        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"{self._base_url}/api/chat",
                json=payload,
                timeout=aiohttp.ClientTimeout(total=120),
            ) as resp:
                if resp.status != 200:
                    text = await resp.text()
                    if "tools" in text.lower() or "unknown field" in text.lower():
                        return await self._generate_with_tools_fallback(
                            messages, system_prompt, tools, temperature
                        )
                    raise Exception(f"Ollama error ({resp.status}): {text}")
                data = await resp.json()

        message = data.get("message", {})
        tool_calls = []

        if message.get("tool_calls"):
            for tc in message["tool_calls"]:
                func = tc.get("function", {})
                tool_calls.append({
                    "name": func.get("name", ""),
                    "arguments": func.get("arguments", {}),
                })

        return {
            "content": message.get("content", "") or "",
            "tool_calls": tool_calls,
            "latency_ms": (time.time() - start) * 1000,
            "model": self._model_id,
        }

    async def _generate_with_tools_fallback(
        self,
        messages: List[Dict[str, str]],
        system_prompt: str,
        tools: List[Dict],
        temperature: float,
    ) -> Dict[str, Any]:
        """Fallback for older Ollama: embed tool schema in system prompt."""
        tools_desc = json.dumps(
            [
                {
                    "name": t["name"],
                    "description": t.get("description", ""),
                    "parameters": t.get("parameters", {}),
                }
                for t in tools
            ],
            indent=2,
        )

        enhanced_prompt = f"""{system_prompt}

## Available Tools
{tools_desc}

## Response Format
If you need to call a tool, respond with ONLY this JSON (no extra text):
{{"tool_call": {{"name": "tool_name", "arguments": {{...}}}}}}

If no tool is needed, respond normally with text."""

        response = await self.generate(
            messages=messages,
            system_prompt=enhanced_prompt,
            temperature=temperature,
        )

        content = response.content.strip()
        tool_calls = []

        try:
            if content.startswith("{") and "tool_call" in content:
                parsed = json.loads(content)
                if "tool_call" in parsed:
                    tool_calls.append({
                        "name": parsed["tool_call"]["name"],
                        "arguments": parsed["tool_call"].get("arguments", {}),
                    })
                    content = ""
        except (json.JSONDecodeError, KeyError):
            pass

        return {
            "content": content,
            "tool_calls": tool_calls,
            "latency_ms": response.latency_ms,
            "model": self._model_id,
        }

    async def is_available(self) -> bool:
        """Check if Ollama is running and model is available."""
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    f"{self._base_url}/api/tags",
                    timeout=aiohttp.ClientTimeout(total=3),
                ) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        models = [m["name"] for m in data.get("models", [])]
                        return any(
                            self._model_id in m or self._model_id.split(":")[0] in m
                            for m in models
                        )
                    return False
        except Exception:
            return False

"""Ollama LLM provider implementation — for local/self-hosted models.

Supports tool/function calling via Ollama's OpenAI-compatible chat API.
Designed for models like Qwen2.5:7b-instruct, Mistral 7B v0.3, etc.

Environment variables:
    OLLAMA_BASE_URL: Base URL of Ollama server (e.g. http://localhost:11434 or Colab ngrok URL)
    OLLAMA_MODEL: Model name (e.g. qwen2.5:7b-instruct)
"""

import asyncio
import json
import logging
import os
from typing import Any, Dict, List, Optional

import httpx

from .base import BaseLLM, LLMResponse, ToolCall, UsageStats

logger = logging.getLogger(__name__)

# Default timeout for Ollama (local models can be slow on first load)
_DEFAULT_TIMEOUT = 120.0  # seconds


class OllamaLLM(BaseLLM):
    """Ollama LLM provider with tool calling support.

    Uses Ollama's /api/chat endpoint which supports OpenAI-compatible
    tool definitions and function calling responses.

    Recommended models (7B, tool-calling capable):
        - qwen2.5:7b-instruct     ← BEST for Vietnamese + tool calling
        - mistral:7b-instruct-v0.3  ← Good function calling, weak Vietnamese
        - llama3.1:8b-instruct      ← Decent all-around
        - firefunction-v2:7b        ← Specialized for function calling
    """

    def __init__(
        self,
        model: Optional[str] = None,
        base_url: Optional[str] = None,
        timeout: float = _DEFAULT_TIMEOUT,
        **kwargs,
    ) -> None:
        """Initialize Ollama LLM provider.

        Args:
            model: Model name. Falls back to OLLAMA_MODEL env var.
            base_url: Ollama server URL. Falls back to OLLAMA_BASE_URL env var.
            timeout: Request timeout in seconds (default 120s for slow cold starts).
        """
        self._base_url = (base_url or os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")).rstrip("/")
        resolved_model = model or os.getenv("OLLAMA_MODEL", "qwen2.5:7b-instruct")

        super().__init__(model=resolved_model, api_key="")  # No API key needed

        self._timeout = timeout
        self._client: Optional[httpx.AsyncClient] = None

        logger.info("OllamaLLM initialized: model=%s, base_url=%s", self.model, self._base_url)

    # ------------------------------------------------------------------
    # HTTP Client (lazy init)
    # ------------------------------------------------------------------

    def _get_client(self) -> httpx.AsyncClient:
        """Get or create async HTTP client."""
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                base_url=self._base_url,
                timeout=httpx.Timeout(self._timeout),
            )
        return self._client

    async def close(self) -> None:
        """Close the HTTP client."""
        if self._client and not self._client.is_closed:
            await self._client.aclose()

    # ------------------------------------------------------------------
    # Health check
    # ------------------------------------------------------------------

    async def health_check(self) -> bool:
        """Check if Ollama server is reachable and model is available."""
        try:
            client = self._get_client()
            resp = await client.get("/api/tags")
            if resp.status_code == 200:
                data = resp.json()
                models = [m.get("name", "") for m in data.get("models", [])]
                # Check if our model is available (with or without :latest tag)
                model_base = self.model.split(":")[0]
                available = any(model_base in m for m in models)
                if not available:
                    logger.warning(
                        "Model '%s' not found in Ollama. Available: %s. "
                        "Will attempt to pull on first call.",
                        self.model, models[:5],
                    )
                return True
            return False
        except Exception as e:
            logger.error("Ollama health check failed: %s", e)
            return False

    # ------------------------------------------------------------------
    # Tool conversion (JSON Schema → Ollama format)
    # ------------------------------------------------------------------

    def _convert_tools_to_ollama(self, tools: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Convert standard JSON Schema tool definitions to Ollama tool format.

        Ollama uses OpenAI-compatible format:
        {
            "type": "function",
            "function": {
                "name": "tool_name",
                "description": "...",
                "parameters": {
                    "type": "object",
                    "properties": {...},
                    "required": [...]
                }
            }
        }
        """
        ollama_tools = []
        for tool in tools:
            ollama_tool = {
                "type": "function",
                "function": {
                    "name": tool.get("name", ""),
                    "description": tool.get("description", ""),
                    "parameters": {
                        "type": "object",
                        "properties": tool.get("parameters", {}).get("properties", {}),
                        "required": tool.get("parameters", {}).get("required", []),
                    },
                },
            }
            ollama_tools.append(ollama_tool)
        return ollama_tools

    # ------------------------------------------------------------------
    # Message conversion
    # ------------------------------------------------------------------

    def _build_messages(
        self,
        messages: List[Dict[str, str]],
        system_prompt: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Build Ollama-compatible message list.

        Ollama natively supports 'system' role, so we don't need the
        Gemini-style user/model injection hack.
        """
        ollama_messages = []

        # System prompt as first message
        if system_prompt:
            ollama_messages.append({"role": "system", "content": system_prompt})

        # Convert messages (keep role names as-is: user, assistant)
        for msg in messages:
            role = msg.get("role", "user")
            content = msg.get("content", "")
            if role and content:
                ollama_messages.append({"role": role, "content": content})

        return ollama_messages

    # ------------------------------------------------------------------
    # Main generate method
    # ------------------------------------------------------------------

    async def generate(
        self,
        messages: List[Dict[str, str]],
        system_prompt: Optional[str] = None,
        tools: Optional[List[Dict[str, Any]]] = None,
        temperature: float = 0.7,
        max_tokens: int = 4096,
        **kwargs,
    ) -> LLMResponse:
        """Generate a response from Ollama.

        Args:
            messages: Chat messages [{role, content}].
            system_prompt: Optional system instruction.
            tools: Optional tool definitions (JSON Schema format).
            temperature: Sampling temperature.
            max_tokens: Max tokens to generate (num_predict in Ollama).
            **kwargs: Additional Ollama options.

        Returns:
            LLMResponse with content, tool_calls, usage.
        """
        client = self._get_client()
        ollama_messages = self._build_messages(messages, system_prompt)

        # Build request body
        body: Dict[str, Any] = {
            "model": self.model,
            "messages": ollama_messages,
            "stream": False,
            "options": {
                "temperature": temperature,
                "num_predict": max_tokens,
            },
        }

        # Add tools if provided
        if tools:
            body["tools"] = self._convert_tools_to_ollama(tools)

        # Make request
        try:
            response = await client.post("/api/chat", json=body)
            response.raise_for_status()
        except httpx.TimeoutException:
            logger.error("Ollama request timed out after %.0fs", self._timeout)
            raise RuntimeError(f"Ollama timed out after {self._timeout}s — model may be loading")
        except httpx.HTTPStatusError as e:
            logger.error("Ollama HTTP error: %d %s", e.response.status_code, e.response.text[:200])
            raise RuntimeError(f"Ollama error: {e.response.status_code} — {e.response.text[:200]}")
        except httpx.ConnectError:
            raise RuntimeError(
                f"Cannot connect to Ollama at {self._base_url}. "
                f"Is the server running? Check OLLAMA_BASE_URL."
            )

        data = response.json()

        # Extract content
        message = data.get("message", {})
        content = message.get("content", "")

        # Extract tool calls
        tool_calls = self._extract_tool_calls(message)

        # Extract usage stats
        usage = self._extract_usage(data)

        return LLMResponse(
            content=content,
            tool_calls=tool_calls,
            usage=usage,
        )

    # ------------------------------------------------------------------
    # Response parsing
    # ------------------------------------------------------------------

    def _extract_tool_calls(self, message: Dict[str, Any]) -> List[ToolCall]:
        """Extract tool calls from Ollama response message.

        Ollama returns tool calls in format:
        {
            "message": {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {
                        "function": {
                            "name": "tool_name",
                            "arguments": {"param": "value"}
                        }
                    }
                ]
            }
        }
        """
        tool_calls = []
        raw_calls = message.get("tool_calls", [])

        for call in raw_calls:
            func = call.get("function", {})
            name = func.get("name", "")
            arguments = func.get("arguments", {})

            if not name:
                logger.debug("Skipping tool call with empty name")
                continue

            # Arguments may come as string (JSON) or dict
            if isinstance(arguments, str):
                try:
                    arguments = json.loads(arguments)
                except json.JSONDecodeError:
                    logger.warning("Failed to parse tool call arguments as JSON: %s", arguments[:100])
                    arguments = {}

            tool_calls.append(ToolCall(name=name, arguments=arguments))

        return tool_calls

    def _extract_usage(self, data: Dict[str, Any]) -> UsageStats:
        """Extract token usage from Ollama response.

        Ollama provides:
            prompt_eval_count: input tokens
            eval_count: output tokens
        """
        prompt_tokens = data.get("prompt_eval_count", 0) or 0
        completion_tokens = data.get("eval_count", 0) or 0

        return UsageStats(
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=prompt_tokens + completion_tokens,
        )

"""Gemini LLM provider using google-generativeai SDK."""

import asyncio
import logging
from typing import Any, Dict, List, Optional

import google.generativeai as genai

from .base import BaseLLM, LLMResponse, ToolCall, UsageStats

logger = logging.getLogger(__name__)


class GeminiLLM(BaseLLM):
    """Google Gemini LLM provider."""

    def __init__(self, model: str = "gemini-2.5-flash", api_key: str = "") -> None:
        super().__init__(model=model, api_key=api_key)
        if not self.api_key:
            logger.error("⚠️ GEMINI_API_KEY is empty! LLM calls will fail.")
            # Don't raise — let app start, but log clearly
        genai.configure(api_key=self.api_key)
        # Initialize model with safety settings disabled at model level
        self._model = genai.GenerativeModel(
            self.model,
            safety_settings={
                "HARM_CATEGORY_HARASSMENT": "BLOCK_NONE",
                "HARM_CATEGORY_HATE_SPEECH": "BLOCK_NONE",
                "HARM_CATEGORY_SEXUALLY_EXPLICIT": "BLOCK_NONE",
                "HARM_CATEGORY_DANGEROUS_CONTENT": "BLOCK_NONE",
            }
        )
        logger.info("GeminiLLM initialized (model=%s)", self.model)

    async def generate(
        self,
        prompt: str = "",
        tools: Optional[List[Dict[str, Any]]] = None,
        temperature: float = 0.7,
        messages: Optional[List[Dict[str, str]]] = None,
        system_prompt: Optional[str] = None,
        max_tokens: int = 2000,
        **kwargs,
    ) -> LLMResponse:
        """Generate a response using Gemini.

        Supports two calling styles:
        1. Simple: generate(prompt="hello")
        2. Chat-style: generate(messages=[{"role": "user", "content": "hello"}], system_prompt="You are...")

        Retries once on timeout errors.
        """
        # Build the content for Gemini
        contents = self._build_contents(prompt, messages, system_prompt)

        generation_config = genai.types.GenerationConfig(
            temperature=temperature,
            max_output_tokens=max_tokens,
        )

        # Disable safety filters using string-based config (works with all SDK versions)
        safety_settings = [
            {"category": "HARM_CATEGORY_HARASSMENT", "threshold": "BLOCK_NONE"},
            {"category": "HARM_CATEGORY_HATE_SPEECH", "threshold": "BLOCK_NONE"},
            {"category": "HARM_CATEGORY_SEXUALLY_EXPLICIT", "threshold": "BLOCK_NONE"},
            {"category": "HARM_CATEGORY_DANGEROUS_CONTENT", "threshold": "BLOCK_NONE"},
        ]

        gemini_tools = self._convert_tools(tools) if tools else None

        for attempt in range(2):
            try:
                logger.info("Gemini API call (attempt %d): model=%s, content_len=%d", attempt+1, self.model, len(str(contents)[:100]))
                response = await asyncio.to_thread(
                    self._model.generate_content,
                    contents,
                    generation_config=generation_config,
                    safety_settings=safety_settings,
                    tools=gemini_tools,
                )
                return self._parse_response(response)

            except Exception as e:
                if attempt == 0 and ("timeout" in str(e).lower() or "deadline" in str(e).lower()):
                    logger.warning("Gemini timeout, retrying once... (error: %s)", e)
                    await asyncio.sleep(1.5)
                    continue
                logger.error("Gemini generation failed: %s", e, exc_info=True)
                raise

        return LLMResponse(content="", tool_calls=[], usage=UsageStats())

    def _build_contents(
        self,
        prompt: str,
        messages: Optional[List[Dict[str, str]]],
        system_prompt: Optional[str],
    ) -> Any:
        """Build Gemini-compatible contents from various input formats.

        Gemini expects either:
        - A string prompt
        - A list of Content objects for multi-turn
        """
        # If messages provided, build multi-turn content
        if messages:
            parts = []
            # Add system prompt as first user context if provided
            if system_prompt:
                parts.append({"role": "user", "parts": [f"[System Instructions]\n{system_prompt}\n[End System Instructions]"]})
                parts.append({"role": "model", "parts": ["Understood. I will follow these instructions."]})

            for msg in messages:
                role = msg.get("role", "user")
                content = msg.get("content", "")
                # Gemini uses "user" and "model" (not "assistant")
                gemini_role = "model" if role in ("assistant", "model", "system") else "user"
                parts.append({"role": gemini_role, "parts": [content]})

            return parts

        # Simple prompt mode
        if system_prompt:
            return f"{system_prompt}\n\n{prompt}"
        return prompt

    def _convert_tools(self, tools: List[Dict[str, Any]]) -> List[Any]:
        """Convert generic tool definitions to Gemini format."""
        function_declarations = []
        for tool in tools:
            try:
                func_decl = genai.types.FunctionDeclaration(
                    name=tool.get("name", ""),
                    description=tool.get("description", ""),
                    parameters=tool.get("parameters", {}),
                )
                function_declarations.append(func_decl)
            except Exception as e:
                logger.warning("Failed to convert tool %s: %s", tool.get("name"), e)

        if function_declarations:
            return [genai.types.Tool(function_declarations=function_declarations)]
        return []

    def _parse_response(self, response: Any) -> LLMResponse:
        """Parse Gemini response into standardized LLMResponse."""
        content = ""
        tool_calls: List[ToolCall] = []

        if not response.candidates:
            logger.warning("Gemini returned no candidates")
            return LLMResponse(content="", tool_calls=[], usage=UsageStats())

        candidate = response.candidates[0]

        # Check for safety block
        finish_reason = getattr(candidate, "finish_reason", None)
        if finish_reason and finish_reason not in (None, 1, "STOP"):
            logger.warning("Gemini response blocked: finish_reason=%s", candidate.finish_reason)
            # Don't return early — still try to extract any partial content below
            # If truly empty, the caller's fallback logic will handle it

        if hasattr(candidate, "content") and candidate.content and hasattr(candidate.content, "parts"):
            for part in candidate.content.parts:
                if hasattr(part, "text") and part.text:
                    content += part.text
                elif hasattr(part, "function_call") and part.function_call:
                    fc = part.function_call
                    tool_calls.append(
                        ToolCall(
                            name=fc.name,
                            arguments=dict(fc.args) if fc.args else {},
                        )
                    )

        usage = UsageStats()
        if hasattr(response, "usage_metadata") and response.usage_metadata:
            usage = UsageStats(
                prompt_tokens=getattr(response.usage_metadata, "prompt_token_count", 0),
                completion_tokens=getattr(response.usage_metadata, "candidates_token_count", 0),
                total_tokens=getattr(response.usage_metadata, "total_token_count", 0),
            )

        return LLMResponse(content=content, tool_calls=tool_calls, usage=usage)

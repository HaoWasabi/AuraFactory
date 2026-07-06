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
        genai.configure(api_key=self.api_key)
        self._model = genai.GenerativeModel(self.model)
        logger.info("GeminiLLM initialized (model=%s)", self.model)

    async def generate(
        self,
        prompt: str,
        tools: Optional[List[Dict[str, Any]]] = None,
        temperature: float = 0.7,
    ) -> LLMResponse:
        """Generate a response using Gemini.

        Retries once on timeout errors.
        """
        generation_config = genai.types.GenerationConfig(temperature=temperature)

        gemini_tools = self._convert_tools(tools) if tools else None

        for attempt in range(2):
            try:
                response = await asyncio.to_thread(
                    self._model.generate_content,
                    prompt,
                    generation_config=generation_config,
                    tools=gemini_tools,
                )
                return self._parse_response(response)

            except Exception as e:
                if attempt == 0 and "timeout" in str(e).lower():
                    logger.warning("Gemini timeout, retrying once... (error: %s)", e)
                    await asyncio.sleep(1.0)
                    continue
                logger.error("Gemini generation failed: %s", e)
                raise

        return LLMResponse(content="", tool_calls=[], usage=UsageStats())

    def _convert_tools(self, tools: List[Dict[str, Any]]) -> List[Any]:
        """Convert generic tool definitions to Gemini format."""
        function_declarations = []
        for tool in tools:
            func_decl = genai.types.FunctionDeclaration(
                name=tool.get("name", ""),
                description=tool.get("description", ""),
                parameters=tool.get("parameters", {}),
            )
            function_declarations.append(func_decl)

        if function_declarations:
            return [genai.types.Tool(function_declarations=function_declarations)]
        return []

    def _parse_response(self, response: Any) -> LLMResponse:
        """Parse Gemini response into standardized LLMResponse."""
        content = ""
        tool_calls: List[ToolCall] = []

        if response.candidates:
            candidate = response.candidates[0]
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

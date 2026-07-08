"""Google Gemini LLM provider implementation."""
import asyncio
import json
import logging
import os
from typing import Any, Dict, List, Optional

import google.generativeai as genai
from google.api_core.exceptions import DeadlineExceeded

from .base import BaseLLM, LLMResponse, ToolCall, UsageStats

logger = logging.getLogger(__name__)


class GeminiLLM(BaseLLM):
    """Google Gemini LLM provider."""

    def __init__(self, model: str = "gemini-2.0-flash", api_key: Optional[str] = None) -> None:
        """Initialize Gemini LLM provider.
        
        Args:
            model: Model name (default: gemini-2.0-flash)
            api_key: Optional API key. If not provided, uses GOOGLE_API_KEY env var.
        """
        api_key = api_key or os.getenv("GOOGLE_API_KEY")
        if not api_key:
            raise ValueError("GOOGLE_API_KEY environment variable not set and api_key not provided")
        
        super().__init__(model=model, api_key=api_key)
        genai.configure(api_key=self.api_key)
        
        # Safety settings: allow all content (compatible with google-generativeai >= 0.4)
        try:
            self.safety_settings = {
                "HARM_CATEGORY_HARASSMENT": "BLOCK_NONE",
                "HARM_CATEGORY_HATE_SPEECH": "BLOCK_NONE",
                "HARM_CATEGORY_SEXUALLY_EXPLICIT": "BLOCK_NONE",
                "HARM_CATEGORY_DANGEROUS_CONTENT": "BLOCK_NONE",
            }
        except Exception:
            # Fallback: no safety override
            self.safety_settings = None

    def update_api_key(self, new_api_key: str) -> None:
        """Update the Gemini API key at runtime without restarting.
        
        Reconfigures the global google-generativeai client so all subsequent
        model instantiations (which happen per-call) use the new key.
        
        Args:
            new_api_key: New Gemini API key to use.
        """
        self.api_key = new_api_key
        genai.configure(api_key=new_api_key)
        logger.info("Gemini API key updated at runtime")

    def _convert_tools_to_gemini(self, tools: List[Dict[str, Any]]) -> List[genai.types.Tool]:
        """Convert tool definitions to Gemini FunctionDeclaration format.
        
        Args:
            tools: List of tool definitions with name, description, parameters.
            
        Returns:
            List of Gemini Tool objects with FunctionDeclarations.
        """
        function_declarations = []
        
        for tool in tools:
            func_decl = genai.types.FunctionDeclaration(
                name=tool.get("name", ""),
                description=tool.get("description", ""),
                parameters=genai.types.Schema(
                    type=genai.types.Type.OBJECT,
                    properties=tool.get("parameters", {}).get("properties", {}),
                    required=tool.get("parameters", {}).get("required", []),
                ),
            )
            function_declarations.append(func_decl)
        
        return [genai.types.Tool(function_declarations=function_declarations)]

    def _build_gemini_content(
        self, messages: List[Dict[str, str]], system_prompt: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """Build Gemini-compatible content from messages.
        
        Handles system prompt by injecting it as first user+model exchange.
        Maps OpenAI-style roles to Gemini roles (assistant→model, user→user).
        
        Args:
            messages: List of chat messages.
            system_prompt: Optional system instruction.
            
        Returns:
            List of Gemini content objects.
        """
        gemini_messages = []
        
        # Inject system prompt if provided
        if system_prompt:
            gemini_messages.append(
                {"role": "user", "parts": [{"text": system_prompt}]}
            )
            gemini_messages.append(
                {"role": "model", "parts": [{"text": "I understand. I will follow these instructions."}]}
            )
        
        # Convert messages: map "assistant" → "model", keep "user" as "user"
        for msg in messages:
            role = msg.get("role", "user")
            content = msg.get("content", "")
            
            # Map OpenAI roles to Gemini roles
            if role == "assistant":
                role = "model"
            
            gemini_messages.append(
                {"role": role, "parts": [{"text": content}]}
            )
        
        return gemini_messages

    def _extract_tool_calls(self, response_content: Any) -> List[ToolCall]:
        """Extract tool calls from Gemini response.
        
        Args:
            response_content: Response content part from Gemini.
            
        Returns:
            List of ToolCall objects.
        """
        tool_calls = []
        
        if hasattr(response_content, "function_call"):
            func_call = response_content.function_call
            tool_calls.append(
                ToolCall(
                    name=func_call.name,
                    arguments=json.loads(func_call.args) if func_call.args else {},
                )
            )
        
        return tool_calls

    async def generate(
        self,
        messages: List[Dict[str, str]],
        system_prompt: Optional[str] = None,
        tools: Optional[List[Dict[str, Any]]] = None,
        temperature: float = 0.7,
        max_tokens: int = 4096,
        **kwargs,
    ) -> LLMResponse:
        """Generate a response from Gemini.
        
        Args:
            messages: Chat messages [{role, content}].
            system_prompt: Optional system instruction.
            tools: Optional tool definitions for function calling.
            temperature: Sampling temperature.
            max_tokens: Max tokens to generate.
            **kwargs: Additional arguments (ignored).
            
        Returns:
            LLMResponse with content, tool_calls, usage.
        """
        gemini_messages = self._build_gemini_content(messages, system_prompt)
        
        # Build generation config
        generation_config = {
            "temperature": temperature,
            "max_output_tokens": max_tokens,
        }

        # If no tools are being used, request JSON output directly.
        # This prevents Gemini from wrapping the response in markdown or prose.
        if not tools:
            generation_config["response_mime_type"] = "application/json"
        
        # Create model with tools if provided
        model_kwargs = {
            "model_name": self.model,
            "safety_settings": self.safety_settings,
            "generation_config": generation_config,
        }
        
        if tools:
            gemini_tools = self._convert_tools_to_gemini(tools)
            model_kwargs["tools"] = gemini_tools
        
        model = genai.GenerativeModel(**model_kwargs)
        
        # Call Gemini API with retry on timeout
        response = None
        attempt = 0
        max_retries = 1
        
        while attempt <= max_retries:
            try:
                response = await asyncio.to_thread(
                    model.generate_content,
                    gemini_messages,
                    stream=False,
                )
                break
            except DeadlineExceeded:
                attempt += 1
                if attempt > max_retries:
                    logger.error("Gemini API timeout after retries")
                    raise
                logger.warning(f"Gemini API timeout, retrying in 2s (attempt {attempt}/{max_retries})")
                await asyncio.sleep(2)
        
        if response is None:
            raise RuntimeError("Failed to get response from Gemini API")
        
        # Parse response
        content = ""
        tool_calls = []
        finish_reason = None

        # Extract finish_reason from candidates (helps diagnose empty/blocked responses)
        try:
            if response.candidates:
                cand = response.candidates[0]
                finish_reason = str(getattr(cand, "finish_reason", "")).upper()
        except Exception:
            pass

        if response.parts:
            for part in response.parts:
                if hasattr(part, "text"):
                    content += part.text

                if hasattr(part, "function_call"):
                    tool_calls.extend(self._extract_tool_calls(part))
        else:
            # No parts — response was likely blocked or truncated
            if finish_reason:
                logger.warning(
                    "Gemini returned empty parts. finish_reason=%s model=%s",
                    finish_reason, self.model,
                )
                if finish_reason in ("MAX_TOKENS", "2"):
                    # Attempt to get partial text from prompt_feedback or safety ratings
                    try:
                        content = response.text  # may raise if blocked
                    except Exception:
                        pass
            # Still empty — log safety feedback if available
            if not content:
                try:
                    pf = response.prompt_feedback
                    logger.warning("Gemini prompt_feedback: %s", pf)
                except Exception:
                    pass
        
        # Extract usage stats
        try:
            um = response.usage_metadata
            usage = UsageStats(
                prompt_tokens=getattr(um, 'prompt_token_count', 0) if um else 0,
                completion_tokens=getattr(um, 'candidates_token_count', 0) if um else 0,
                total_tokens=getattr(um, 'total_token_count', 0) if um else 0,
            )
        except Exception:
            usage = UsageStats()
        
        return LLMResponse(
            content=content,
            tool_calls=tool_calls,
            usage=usage,
        )

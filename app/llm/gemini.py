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

    # ------------------------------------------------------------------
    # JSON Schema → Gemini Proto conversion
    # ------------------------------------------------------------------

    def _json_schema_to_proto(self, schema: Dict[str, Any]) -> "genai.protos.Schema":
        """Recursively convert a JSON Schema dict to a Gemini proto Schema.

        Handles: string, number, integer, boolean, array (with items), object (with properties).
        This is the ONLY Gemini-specific conversion layer. Tool definitions stay as standard
        JSON Schema everywhere else — making Bedrock swap trivial (Bedrock accepts JSON Schema directly).
        """
        json_type = schema.get("type", "string")
        proto_type = self._map_type(json_type)
        description = schema.get("description", "")

        kwargs: Dict[str, Any] = {
            "type": proto_type,
            "description": description,
        }

        # Array → must have "items"
        if json_type == "array":
            items_schema = schema.get("items", {"type": "string"})
            kwargs["items"] = self._json_schema_to_proto(items_schema)

        # Object → has "properties" and optionally "required"
        elif json_type == "object":
            props = schema.get("properties", {})
            if props:
                kwargs["properties"] = {
                    k: self._json_schema_to_proto(v) for k, v in props.items()
                }
                required = schema.get("required", [])
                if required:
                    kwargs["required"] = required

        return genai.protos.Schema(**kwargs)

    def _convert_tools_to_gemini(self, tools: List[Dict[str, Any]]) -> List[Any]:
        """Convert standard JSON Schema tool definitions to Gemini proto format."""
        function_declarations = []

        for tool in tools:
            params = tool.get("parameters", {})
            gemini_params = None

            if params and params.get("properties"):
                # Wrap in object schema for recursive conversion
                obj_schema = {
                    "type": "object",
                    "properties": params["properties"],
                    "required": params.get("required", []),
                }
                gemini_params = self._json_schema_to_proto(obj_schema)

            func_decl = genai.protos.FunctionDeclaration(
                name=tool.get("name", ""),
                description=tool.get("description", ""),
                parameters=gemini_params,
            )
            function_declarations.append(func_decl)

        return [genai.protos.Tool(function_declarations=function_declarations)]

    @staticmethod
    def _map_type(json_type: str) -> int:
        """Map JSON Schema type string to Gemini proto Type enum value."""
        type_map = {
            "string": genai.protos.Type.STRING,
            "number": genai.protos.Type.NUMBER,
            "integer": genai.protos.Type.INTEGER,
            "boolean": genai.protos.Type.BOOLEAN,
            "array": genai.protos.Type.ARRAY,
            "object": genai.protos.Type.OBJECT,
        }
        return type_map.get(json_type.lower(), genai.protos.Type.STRING)

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
            # Skip empty/malformed function calls (Gemini sometimes returns name="")
            if not func_call.name:
                logger.debug("Skipping empty function_call (no name)")
                return tool_calls
            # func_call.args is a MapComposite (proto struct), convert to dict
            if func_call.args:
                try:
                    args = dict(func_call.args)
                except (TypeError, ValueError):
                    args = json.loads(str(func_call.args)) if func_call.args else {}
            else:
                args = {}
            tool_calls.append(
                ToolCall(
                    name=func_call.name,
                    arguments=args,
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
        # Log finish_reason for debugging (safety blocks, length limits, etc.)
        try:
            if response.candidates:
                finish_reason = response.candidates[0].finish_reason
                if finish_reason and finish_reason != 1:  # 1 = STOP (normal)
                    logger.warning(
                        "Gemini finish_reason=%s (1=STOP, 2=MAX_TOKENS, 3=SAFETY, 4=RECITATION, 5=OTHER)",
                        finish_reason,
                    )
        except (AttributeError, IndexError):
            pass
        
        content = ""
        tool_calls = []
        
        # Access parts via candidates (more reliable than response.parts convenience property)
        parts = None
        try:
            parts = response.parts  # Try convenience property first
        except (ValueError, IndexError, AttributeError):
            pass
        if not parts:
            # Fallback: access directly via candidates
            try:
                parts = response.candidates[0].content.parts if response.candidates else None
                if parts:
                    logger.debug("Used candidates[0].content.parts fallback (response.parts was empty)")
            except (AttributeError, IndexError):
                parts = None

        if parts:
            for part in parts:
                if hasattr(part, "text"):
                    content = part.text
                
                if hasattr(part, "function_call"):
                    tool_calls.extend(self._extract_tool_calls(part))
        else:
            # No parts at all — log detailed reason
            try:
                candidate = response.candidates[0] if response.candidates else None
                fr = candidate.finish_reason if candidate else "no_candidates"
                logger.warning("Gemini returned empty parts. finish_reason=%s, prompt_feedback=%s",
                               fr, getattr(response, 'prompt_feedback', None))
            except Exception:
                logger.warning("Gemini returned empty parts (could not inspect reason)")
        
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

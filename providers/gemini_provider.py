# providers/gemini_provider.py
"""
Phase 1: Dùng Gemini (free/open) để test agent logic.
Khi chuyển AWS, tạo BedrockProvider implement cùng interface → done.
"""
import time
import json
from typing import List, Dict, Any, Optional
import google.generativeai as genai
from providers.base import LLMProvider, LLMResponse


class GeminiProvider(LLMProvider):
    """Gemini implementation — dùng cho Phase 1 (test local, miễn phí)"""
    
    def __init__(self, api_key: str, model_id: str = "gemini-2.5-flash"):
        genai.configure(api_key=api_key)
        self._model_id = model_id
        self._model = genai.GenerativeModel(model_id)
    
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
        
        # Convert messages → Gemini format
        history = []
        for msg in messages[:-1]:  # All except last
            role = "user" if msg["role"] == "user" else "model"
            history.append({"role": role, "parts": msg["content"]})
        
        chat = self._model.start_chat(history=history)
        
        # System prompt inject vào message cuối
        last_msg = messages[-1]["content"] if messages else ""
        if system_prompt:
            last_msg = f"[System Instructions]\n{system_prompt}\n\n[User Message]\n{last_msg}"
        
        response = chat.send_message(
            last_msg,
            generation_config=genai.GenerationConfig(
                temperature=temperature,
                max_output_tokens=max_tokens,
            )
        )
        
        latency = (time.time() - start) * 1000
        
        # Parse token usage (usage_metadata là protobuf, không phải dict)
        input_tokens = 0
        output_tokens = 0
        try:
            if hasattr(response, 'usage_metadata') and response.usage_metadata:
                input_tokens = getattr(response.usage_metadata, 'prompt_token_count', 0) or 0
                output_tokens = getattr(response.usage_metadata, 'candidates_token_count', 0) or 0
        except Exception:
            pass

        return LLMResponse(
            content=response.text,
            model=self._model_id,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            latency_ms=latency,
            raw_response=response,
        )
    
    async def generate_with_tools(
        self,
        messages: List[Dict[str, str]],
        system_prompt: str,
        tools: List[Dict],
        temperature: float = 0.3,
    ) -> Dict[str, Any]:
        """
        Gemini function calling.
        tools format: [{"name": "...", "description": "...", "parameters": {...}}]
        """
        start = time.time()
        
        # Convert tools → Gemini format
        gemini_tools = []
        for tool in tools:
            gemini_tools.append(genai.protos.Tool(
                function_declarations=[
                    genai.protos.FunctionDeclaration(
                        name=tool["name"],
                        description=tool.get("description", ""),
                        parameters=tool.get("parameters", {}),
                    )
                ]
            ))
        
        model_with_tools = genai.GenerativeModel(
            self._model_id,
            tools=gemini_tools,
            system_instruction=system_prompt,
        )
        
        # Convert messages
        history = []
        for msg in messages[:-1]:
            role = "user" if msg["role"] == "user" else "model"
            history.append({"role": role, "parts": msg["content"]})
        
        chat = model_with_tools.start_chat(history=history)
        last_msg = messages[-1]["content"] if messages else ""
        
        response = chat.send_message(
            last_msg,
            generation_config=genai.GenerationConfig(temperature=temperature),
        )
        
        # Parse tool calls
        tool_calls = []
        content = ""
        
        for part in response.parts:
            if hasattr(part, 'function_call') and part.function_call:
                fc = part.function_call
                tool_calls.append({
                    "name": fc.name,
                    "arguments": dict(fc.args) if fc.args else {}
                })
            elif hasattr(part, 'text') and part.text:
                content += part.text
        
        return {
            "content": content,
            "tool_calls": tool_calls,
            "latency_ms": (time.time() - start) * 1000,
            "model": self._model_id,
        }

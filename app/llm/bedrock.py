"""Amazon Bedrock LLM provider implementation — using the Converse API.

Supports tool/function calling via Bedrock's Converse API which provides a
unified interface across all foundation models (Nova, Claude, Llama, Mistral).

Recommended models (cost-optimized for AuraFactory):
    - amazon.nova-micro-v1:0     ← CHEAPEST: $0.035/1M in, $0.14/1M out (structured JSON)
    - amazon.nova-lite-v1:0      ← BALANCED: $0.06/1M in, $0.24/1M out (complex reasoning)
    - amazon.nova-pro-v1:0       ← POWERFUL: $0.80/1M in, $3.20/1M out (if needed)

Environment variables:
    AWS_REGION: AWS region (default: us-east-1)
    BEDROCK_MODEL_ID: Model ID (default: amazon.nova-micro-v1:0)
    AWS_ACCESS_KEY_ID: (optional if using IAM role/profile)
    AWS_SECRET_ACCESS_KEY: (optional if using IAM role/profile)

Authentication:
    Uses standard boto3 credential chain:
    1. Environment variables (AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY)
    2. AWS credentials file (~/.aws/credentials)
    3. IAM instance role (EC2, ECS, App Runner)
    4. IAM Identity Center (SSO)
"""

import asyncio
import json
import logging
import os
from typing import Any, Dict, List, Optional

import boto3
from botocore.config import Config as BotoConfig
from botocore.exceptions import ClientError

from .base import BaseLLM, LLMResponse, ToolCall, UsageStats

logger = logging.getLogger(__name__)

# Retry config for transient Bedrock errors
_BOTO_CONFIG = BotoConfig(
    retries={"max_attempts": 3, "mode": "adaptive"},
    connect_timeout=10,
    read_timeout=120,  # LLM responses can be slow
)


class BedrockLLM(BaseLLM):
    """Amazon Bedrock LLM provider using the Converse API.

    The Converse API is model-agnostic — same code works for Nova, Claude,
    Llama, Mistral, etc. It natively supports tool/function calling.

    Architecture note:
        Bedrock accepts JSON Schema for tool parameters directly — no
        conversion needed (unlike Gemini which requires proto objects).
        This makes this provider simpler than gemini.py.
    """

    def __init__(
        self,
        model: Optional[str] = None,
        region: Optional[str] = None,
        **kwargs,
    ) -> None:
        """Initialize Bedrock LLM provider.

        Args:
            model: Bedrock model ID. Falls back to BEDROCK_MODEL_ID env var.
            region: AWS region. Falls back to AWS_REGION env var.
        """
        resolved_model = model or os.getenv("BEDROCK_MODEL_ID", "amazon.nova-micro-v1:0")
        resolved_region = region or os.getenv("AWS_REGION", "us-east-1")

        super().__init__(model=resolved_model, api_key="")  # No API key — uses IAM

        self._region = resolved_region
        self._client = boto3.client(
            "bedrock-runtime",
            region_name=self._region,
            config=_BOTO_CONFIG,
        )

        logger.info(
            "BedrockLLM initialized: model=%s, region=%s",
            self.model, self._region,
        )

    # ------------------------------------------------------------------
    # Tool conversion (JSON Schema → Bedrock Converse format)
    # ------------------------------------------------------------------

    def _convert_tools_to_bedrock(self, tools: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Convert standard JSON Schema tool definitions to Bedrock toolConfig format.

        Bedrock Converse expects:
        {
            "tools": [
                {
                    "toolSpec": {
                        "name": "tool_name",
                        "description": "...",
                        "inputSchema": {
                            "json": {
                                "type": "object",
                                "properties": {...},
                                "required": [...]
                            }
                        }
                    }
                }
            ]
        }

        Our internal format is already close to JSON Schema, so conversion is minimal.
        """
        bedrock_tools = []

        for tool in tools:
            params = tool.get("parameters", {})
            input_schema = {
                "type": "object",
                "properties": params.get("properties", {}),
                "required": params.get("required", []),
            }

            bedrock_tool = {
                "toolSpec": {
                    "name": tool.get("name", ""),
                    "description": tool.get("description", ""),
                    "inputSchema": {
                        "json": input_schema
                    },
                }
            }
            bedrock_tools.append(bedrock_tool)

        return bedrock_tools

    # ------------------------------------------------------------------
    # Message conversion
    # ------------------------------------------------------------------

    def _build_messages(
        self,
        messages: List[Dict[str, str]],
    ) -> List[Dict[str, Any]]:
        """Build Bedrock Converse-compatible message list.

        Bedrock Converse message format:
        {
            "role": "user" | "assistant",
            "content": [{"text": "..."}]
        }

        Note: System prompt is passed separately (not in messages).
        """
        bedrock_messages = []

        for msg in messages:
            role = msg.get("role", "user")
            content = msg.get("content", "")

            # Skip system messages (handled separately by Converse API)
            if role == "system":
                continue

            # Normalize role: "assistant" stays "assistant" in Bedrock
            if role not in ("user", "assistant"):
                role = "user"

            bedrock_messages.append({
                "role": role,
                "content": [{"text": content}],
            })

        # Bedrock requires messages to alternate user/assistant.
        # If we have consecutive same-role messages, merge them.
        merged = self._merge_consecutive_roles(bedrock_messages)

        return merged

    @staticmethod
    def _merge_consecutive_roles(messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Merge consecutive messages with the same role.

        Bedrock Converse requires strict alternation of user/assistant.
        If multiple consecutive user or assistant messages exist, merge their content.
        """
        if not messages:
            return messages

        merged = [messages[0]]

        for msg in messages[1:]:
            if msg["role"] == merged[-1]["role"]:
                # Same role — merge content blocks
                merged[-1]["content"].extend(msg["content"])
            else:
                merged.append(msg)

        return merged

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
        """Generate a response from Amazon Bedrock via the Converse API.

        Args:
            messages: Chat messages [{role, content}].
            system_prompt: Optional system instruction.
            tools: Optional tool definitions (JSON Schema format).
            temperature: Sampling temperature.
            max_tokens: Max tokens to generate.
            **kwargs: Additional arguments (ignored).

        Returns:
            LLMResponse with content, tool_calls, usage.
        """
        bedrock_messages = self._build_messages(messages)

        # Build request params
        params: Dict[str, Any] = {
            "modelId": self.model,
            "messages": bedrock_messages,
            "inferenceConfig": {
                "temperature": temperature,
                "maxTokens": max_tokens,
            },
        }

        # System prompt (Converse API supports it natively)
        if system_prompt:
            params["system"] = [{"text": system_prompt}]

        # Tool config
        if tools:
            bedrock_tools = self._convert_tools_to_bedrock(tools)
            if bedrock_tools:
                params["toolConfig"] = {"tools": bedrock_tools}

        # Call Bedrock Converse API (sync boto3 → async via thread pool)
        try:
            response = await asyncio.to_thread(
                self._client.converse, **params
            )
        except ClientError as e:
            error_code = e.response["Error"]["Code"]
            error_msg = e.response["Error"]["Message"]

            if error_code == "ThrottlingException":
                logger.warning("Bedrock throttled, retrying in 2s: %s", error_msg)
                await asyncio.sleep(2)
                try:
                    response = await asyncio.to_thread(
                        self._client.converse, **params
                    )
                except ClientError as retry_error:
                    logger.error("Bedrock retry failed: %s", retry_error)
                    raise RuntimeError(f"Bedrock API error after retry: {retry_error}")
            elif error_code == "ValidationException":
                logger.error("Bedrock validation error: %s", error_msg)
                raise ValueError(f"Bedrock validation error: {error_msg}")
            elif error_code == "AccessDeniedException":
                logger.error("Bedrock access denied: %s", error_msg)
                raise PermissionError(
                    f"Bedrock access denied for model {self.model}. "
                    f"Ensure the model is enabled in region {self._region} "
                    f"and your IAM role has bedrock:InvokeModel permission."
                )
            else:
                logger.error("Bedrock error [%s]: %s", error_code, error_msg)
                raise RuntimeError(f"Bedrock API error [{error_code}]: {error_msg}")

        # Parse response
        return self._parse_response(response)

    # ------------------------------------------------------------------
    # Response parsing
    # ------------------------------------------------------------------

    def _parse_response(self, response: Dict[str, Any]) -> LLMResponse:
        """Parse Bedrock Converse API response into LLMResponse.

        Converse response format:
        {
            "output": {
                "message": {
                    "role": "assistant",
                    "content": [
                        {"text": "..."},              ← text response
                        {"toolUse": {                 ← tool call
                            "toolUseId": "...",
                            "name": "tool_name",
                            "input": {"param": "value"}
                        }}
                    ]
                }
            },
            "usage": {
                "inputTokens": 123,
                "outputTokens": 456,
                "totalTokens": 579
            },
            "stopReason": "end_turn" | "tool_use" | "max_tokens"
        }
        """
        output = response.get("output", {})
        message = output.get("message", {})
        content_blocks = message.get("content", [])

        # Extract text content and tool calls
        text_parts = []
        tool_calls = []

        for block in content_blocks:
            # Text block
            if "text" in block:
                text_parts.append(block["text"])

            # Tool use block
            elif "toolUse" in block:
                tool_use = block["toolUse"]
                tool_name = tool_use.get("name", "")
                tool_input = tool_use.get("input", {})

                if tool_name:
                    tool_calls.append(ToolCall(
                        name=tool_name,
                        arguments=tool_input if isinstance(tool_input, dict) else {},
                    ))
                else:
                    logger.debug("Skipping toolUse block with empty name")

        # Combine text parts
        content = "\n".join(text_parts) if text_parts else ""

        # Extract usage
        usage_data = response.get("usage", {})
        usage = UsageStats(
            prompt_tokens=usage_data.get("inputTokens", 0),
            completion_tokens=usage_data.get("outputTokens", 0),
            total_tokens=usage_data.get("totalTokens", 0),
        )

        # Log stop reason for debugging
        stop_reason = response.get("stopReason", "unknown")
        if stop_reason == "max_tokens":
            logger.warning("Bedrock response hit max_tokens limit")
        elif stop_reason == "tool_use":
            logger.debug("Bedrock response stopped for tool_use (%d calls)", len(tool_calls))

        return LLMResponse(
            content=content,
            tool_calls=tool_calls,
            usage=usage,
        )

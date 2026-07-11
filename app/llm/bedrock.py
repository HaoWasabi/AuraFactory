"""AWS Bedrock LLM provider — Converse API (supports Nova, Claude, Titan, etc.)"""
import asyncio
import json
import logging
from typing import Any, Dict, List, Optional

import boto3
from botocore.exceptions import ClientError, NoCredentialsError, NoRegionError

from .base import BaseLLM, LLMResponse, LLMQuotaError, ToolCall, UsageStats

logger = logging.getLogger(__name__)


class BedrockLLM(BaseLLM):
    """AWS Bedrock LLM provider using the unified Converse API.

    Supports any model available on Bedrock:
        - amazon.nova-micro-v1:0    (fastest, cheapest)
        - amazon.nova-lite-v1:0     (balanced)
        - amazon.nova-pro-v1:0      (most capable)
        - anthropic.claude-3-haiku-20240307-v1:0  (alternative)

    Auth: uses boto3 credential chain — IAM role (recommended on AWS),
    or AWS_ACCESS_KEY_ID + AWS_SECRET_ACCESS_KEY env vars for local dev.
    """

    provider_name = "bedrock"

    def __init__(
        self,
        model: str = "amazon.nova-lite-v1:0",
        region: str = "us-east-1",
        api_key: str = "",          # ignored — Bedrock uses IAM
        **kwargs,
    ) -> None:
        super().__init__(model=model, api_key="")
        self.region = region

        # boto3.client() does NOT validate credentials at construction time —
        # it only fails when the first API call is made.  We create the client
        # eagerly here so import-time wiring is cheap; credential errors will
        # surface as ClientError / NoCredentialsError on the first generate() call.
        try:
            self._client = boto3.client("bedrock-runtime", region_name=region)
            logger.info("BedrockLLM initialized: model=%s region=%s", model, region)
        except NoRegionError as e:
            raise ValueError(
                f"AWS region not configured. Set AWS_REGION env var or pass region= explicitly. "
                f"Original: {e}"
            ) from e
        except Exception as e:
            # Catch unexpected boto3 init errors (e.g. malformed endpoint override)
            raise ValueError(f"Failed to create Bedrock client: {e}") from e

    # ------------------------------------------------------------------
    # Public interface
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
        """Generate a response from Bedrock using the Converse API.

        Args:
            messages: Chat messages [{role, content}].
            system_prompt: Optional system instruction.
            tools: Optional tool definitions for function calling.
            temperature: Sampling temperature (0.0–1.0).
            max_tokens: Maximum tokens to generate.

        Returns:
            LLMResponse with content, tool_calls, usage.
        """
        converse_messages = self._build_messages(messages)

        call_kwargs: Dict[str, Any] = {
            "modelId": self.model,
            "messages": converse_messages,
            "inferenceConfig": {
                "temperature": temperature,
                "maxTokens": max_tokens,
            },
        }

        if system_prompt:
            call_kwargs["system"] = [{"text": system_prompt}]

        if tools:
            call_kwargs["toolConfig"] = {
                "tools": self._convert_tools(tools)
            }

        try:
            response = await asyncio.to_thread(
                self._client.converse, **call_kwargs
            )
        except NoCredentialsError as e:
            raise ValueError(
                "AWS credentials not found. Set AWS_ACCESS_KEY_ID + "
                "AWS_SECRET_ACCESS_KEY env vars, or use an IAM role."
            ) from e
        except ClientError as e:
            code = e.response["Error"]["Code"]
            msg = e.response["Error"]["Message"]
            logger.warning("Bedrock ClientError %s: %s", code, msg)

            if code in ("ThrottlingException", "TooManyRequestsException", "ServiceUnavailableException"):
                raise LLMQuotaError("rate_limited", original=e) from e
            if code in ("AccessDeniedException",):
                raise LLMQuotaError("permission_denied", original=e) from e
            if code in ("ValidationException",):
                # Model not enabled in this region — guide user
                if "model" in msg.lower() and ("access" in msg.lower() or "enabled" in msg.lower()):
                    raise LLMQuotaError("permission_denied", original=e) from e
            raise

        return self._parse_response(response)

    # ------------------------------------------------------------------
    # Message conversion
    # ------------------------------------------------------------------

    def _build_messages(
        self, messages: List[Dict[str, str]]
    ) -> List[Dict[str, Any]]:
        """Convert OpenAI-style messages to Bedrock Converse format.

        Bedrock Converse requires:
        - Alternating user/assistant turns
        - First message must be "user"
        - Content as list of blocks: [{"text": "..."}]
        """
        result = []
        for m in messages:
            role = m.get("role", "user")
            content = m.get("content", "")

            # Map "system" and unknown roles to "user"
            if role not in ("user", "assistant"):
                role = "user"

            # Merge consecutive same-role messages (Bedrock doesn't allow them)
            if result and result[-1]["role"] == role:
                result[-1]["content"][0]["text"] += f"\n\n{content}"
            else:
                result.append({
                    "role": role,
                    "content": [{"text": content}],
                })

        # Bedrock requires at least one user message to start
        if not result or result[0]["role"] != "user":
            result.insert(0, {
                "role": "user",
                "content": [{"text": "Please proceed."}],
            })

        return result

    def _convert_tools(
        self, tools: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """Convert tool definitions to Bedrock toolSpec format."""
        bedrock_tools = []
        for t in tools:
            bedrock_tools.append({
                "toolSpec": {
                    "name": t.get("name", ""),
                    "description": t.get("description", ""),
                    "inputSchema": {
                        "json": t.get("parameters", {
                            "type": "object",
                            "properties": {},
                        }),
                    },
                }
            })
        return bedrock_tools

    # ------------------------------------------------------------------
    # Response parsing
    # ------------------------------------------------------------------

    def _parse_response(self, response: Dict[str, Any]) -> LLMResponse:
        """Parse Bedrock Converse API response into LLMResponse."""
        content = ""
        tool_calls: List[ToolCall] = []

        # Extract message content
        output_msg = response.get("output", {}).get("message", {})
        for block in output_msg.get("content", []):
            if "text" in block:
                content += block["text"]
            elif "toolUse" in block:
                tu = block["toolUse"]
                tool_calls.append(ToolCall(
                    name=tu.get("name", ""),
                    arguments=tu.get("input", {}),
                ))

        # Extract stop reason for debugging
        stop_reason = response.get("stopReason", "")
        if stop_reason and stop_reason not in ("end_turn", "tool_use"):
            logger.warning(
                "Bedrock stopReason=%s model=%s", stop_reason, self.model
            )

        # Extract usage stats
        usage_raw = response.get("usage", {})
        usage = UsageStats(
            prompt_tokens=usage_raw.get("inputTokens", 0),
            completion_tokens=usage_raw.get("outputTokens", 0),
            total_tokens=usage_raw.get("totalTokens", 0),
        )

        return LLMResponse(
            content=content,
            tool_calls=tool_calls,
            usage=usage,
        )

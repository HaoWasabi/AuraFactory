# app/services/react_step_handler.py
"""
ReActStepHandler — Hybrid ReAct for single step retry (§5.6b).

When a plan step fails during execution, this handler:
1. Calls the LLM (Reason phase) to suggest adjusted parameters.
2. Re-executes the SAME tool with adjusted params (Act phase).
3. Returns success/failure — hard limit of 1 retry per step.

Constraints:
- Only adjust PARAMETERS of the current step.
- Cannot add/remove steps.
- Cannot change the tool.
- Cannot exceed approved risk level.
- Maximum 1 retry per step.
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any, Dict, Optional

from app.llm.base import BaseLLM, LLMResponse
from app.mcp.client import MCPClient
from app.mcp.protocol import MCPResponse

logger = logging.getLogger(__name__)

# System prompt for the ReAct Reason phase
REACT_SYSTEM_PROMPT = """You are fixing a failed Discord operation. The step failed with this error.
You can ONLY adjust the parameters (tool_params) of the same tool.
You CANNOT: add new steps, change the tool name, or exceed the approved risk.
Given the current server state and the error, suggest adjusted parameters.
Respond in JSON: {"adjusted_params": {...}, "reason": "why this fix should work"}
If the error is unfixable with parameter adjustment alone, respond: {"unfixable": true, "reason": "..."}"""


class ReActStepHandler:
    """Handles single-step retry with parameter adjustment (§5.6b).

    Constraints:
    - Only adjust PARAMETERS of the current step
    - Cannot add/remove steps
    - Cannot change the tool
    - Cannot exceed approved risk level
    - Maximum 1 retry per step
    """

    def __init__(self, llm: BaseLLM, mcp_client: MCPClient) -> None:
        self._llm = llm
        self._mcp_client = mcp_client

    async def handle(
        self, step: dict, error: str, server_context: dict
    ) -> dict:
        """Attempt to fix a failed step by adjusting parameters.

        Args:
            step: dict with tool_name, tool_params, description, risk_level.
            error: the error message from the failed execution.
            server_context: current server state for the LLM.

        Returns:
            {
                "success": True/False,
                "result": <tool result if success>,
                "adjusted_params": <adjusted params used>,
                "reason": <LLM reasoning>,
                "error": <error message if failed>,
                "duration_ms": <total ReAct duration>,
            }
        """
        tool_name: str = step["tool_name"]
        tool_params: dict = step.get("tool_params", {})
        description: str = step.get("description", "")
        risk_level: str = step.get("risk_level", "low")

        start_time = time.time()

        # ------------------------------------------------------------------
        # REASON phase: Ask LLM to suggest adjusted parameters
        # ------------------------------------------------------------------
        reason_result = await self._reason(
            tool_name=tool_name,
            tool_params=tool_params,
            description=description,
            risk_level=risk_level,
            error=error,
            server_context=server_context,
        )

        if reason_result is None:
            duration_ms = int((time.time() - start_time) * 1000)
            return {
                "success": False,
                "error": "ReAct: LLM failed to generate parameter adjustment",
                "adjusted_params": None,
                "reason": None,
                "duration_ms": duration_ms,
            }

        # Check if LLM determined the error is unfixable
        if reason_result.get("unfixable"):
            duration_ms = int((time.time() - start_time) * 1000)
            return {
                "success": False,
                "error": f"ReAct: Unfixable — {reason_result.get('reason', 'unknown')}",
                "adjusted_params": None,
                "reason": reason_result.get("reason"),
                "duration_ms": duration_ms,
            }

        adjusted_params: dict = reason_result.get("adjusted_params", {})
        reason_text: str = reason_result.get("reason", "")

        if not adjusted_params:
            duration_ms = int((time.time() - start_time) * 1000)
            return {
                "success": False,
                "error": "ReAct: LLM returned empty adjusted_params",
                "adjusted_params": None,
                "reason": reason_text,
                "duration_ms": duration_ms,
            }

        # ------------------------------------------------------------------
        # ACT phase: Re-execute the SAME tool with adjusted parameters
        # ------------------------------------------------------------------
        logger.info(
            "[ReActStepHandler] Retrying '%s' with adjusted params: %s (reason: %s)",
            tool_name,
            adjusted_params,
            reason_text,
        )

        response: MCPResponse = await self._mcp_client.call_tool(
            tool_name, adjusted_params
        )

        duration_ms = int((time.time() - start_time) * 1000)

        if response.success:
            logger.info(
                "[ReActStepHandler] Retry succeeded for '%s'", tool_name
            )
            return {
                "success": True,
                "result": response.result,
                "adjusted_params": adjusted_params,
                "reason": reason_text,
                "duration_ms": duration_ms,
            }

        # Retry also failed — hard limit: no more retries
        logger.warning(
            "[ReActStepHandler] Retry FAILED for '%s': %s",
            tool_name,
            response.error,
        )
        return {
            "success": False,
            "error": response.error or "Retry failed with unknown error",
            "adjusted_params": adjusted_params,
            "reason": reason_text,
            "duration_ms": duration_ms,
        }

    # ------------------------------------------------------------------
    # Internal: LLM Reason Phase
    # ------------------------------------------------------------------

    async def _reason(
        self,
        tool_name: str,
        tool_params: dict,
        description: str,
        risk_level: str,
        error: str,
        server_context: dict,
    ) -> Optional[dict]:
        """Call LLM to reason about the failure and suggest adjusted params.

        Returns:
            Parsed dict with either:
                {"adjusted_params": {...}, "reason": "..."}
            or:
                {"unfixable": true, "reason": "..."}
            Returns None if LLM call or parsing fails.
        """
        user_message = self._build_reason_prompt(
            tool_name=tool_name,
            tool_params=tool_params,
            description=description,
            risk_level=risk_level,
            error=error,
            server_context=server_context,
        )

        try:
            response: LLMResponse = await self._llm.generate(
                messages=[{"role": "user", "content": user_message}],
                system_prompt=REACT_SYSTEM_PROMPT,
                temperature=0.1,  # Low temperature for deterministic fixes
                max_tokens=1024,
            )
        except Exception as e:
            logger.error("[ReActStepHandler] LLM call failed: %s", str(e))
            return None

        if not response.content:
            return None

        # Parse JSON from LLM response
        return self._parse_llm_response(response.content)

    def _build_reason_prompt(
        self,
        tool_name: str,
        tool_params: dict,
        description: str,
        risk_level: str,
        error: str,
        server_context: dict,
    ) -> str:
        """Build the user message for the Reason phase LLM call."""
        return f"""A plan step failed during execution. Please analyze and suggest fixed parameters.

## Failed Step
- **Tool**: {tool_name}
- **Description**: {description}
- **Risk Level**: {risk_level}
- **Parameters Used**: {json.dumps(tool_params, indent=2)}

## Error
{error}

## Current Server State
{json.dumps(server_context, indent=2, default=str) if isinstance(server_context, dict) else str(server_context)}

## Instructions
Suggest adjusted parameters for the SAME tool ({tool_name}) that will fix the error.
You CANNOT change the tool name or add additional steps.
The adjusted parameters must not exceed the approved risk level ({risk_level}).

Respond in JSON only."""

    def _parse_llm_response(self, raw: str) -> Optional[dict]:
        """Parse LLM response into structured dict.

        Handles:
        - Direct JSON
        - JSON wrapped in code blocks (```json ... ```)
        """
        text = raw.strip()

        # Strip markdown code blocks
        if text.startswith("```"):
            lines = text.split("\n")
            # Remove first and last lines if they are code fences
            if lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]
            text = "\n".join(lines).strip()

        # Try to find JSON object
        try:
            # Direct parse
            result = json.loads(text)
            if isinstance(result, dict):
                return result
        except json.JSONDecodeError:
            pass

        # Try to extract JSON from text
        try:
            start = text.index("{")
            end = text.rindex("}") + 1
            result = json.loads(text[start:end])
            if isinstance(result, dict):
                return result
        except (ValueError, json.JSONDecodeError):
            pass

        logger.warning(
            "[ReActStepHandler] Failed to parse LLM response as JSON: %s",
            text[:200],
        )
        return None

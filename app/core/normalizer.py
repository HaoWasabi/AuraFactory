"""Response Normalizer — guarantees consistent shape from any LLM output.

Regardless of what the LLM returns (empty, malformed, safety-blocked,
partial, wrong types), this module produces a NormalizedLLMOutput that
downstream code can trust unconditionally.

Design principle: downstream code NEVER touches raw LLM response.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set

from app.llm.base import LLMResponse, ToolCall

logger = logging.getLogger(__name__)


@dataclass
class NormalizedToolCall:
    """A tool call with validated, type-coerced arguments."""
    name: str
    mcp_name: str  # Mapped MCP tool name
    arguments: Dict[str, Any] = field(default_factory=dict)
    validation_warnings: List[str] = field(default_factory=list)


@dataclass
class NormalizedLLMOutput:
    """Guaranteed output shape — all downstream code only sees this.

    Invariants:
      - usable is always bool
      - tool_calls is always List (may be empty)
      - text is always str (may be empty)
      - If not usable, failure_reason explains why
    """
    usable: bool
    tool_calls: List[NormalizedToolCall] = field(default_factory=list)
    text: str = ""
    failure_reason: Optional[str] = None
    raw_metadata: Dict[str, Any] = field(default_factory=dict)

    @property
    def has_tool_calls(self) -> bool:
        return len(self.tool_calls) > 0

    @property
    def is_text_only(self) -> bool:
        return self.usable and not self.has_tool_calls and bool(self.text)


class LLMResponseNormalizer:
    """Normalize any LLM response into NormalizedLLMOutput.

    Handles:
      - Empty/None response (safety block, quota exceeded)
      - Tool calls with unknown names (filtered out)
      - Tool call arguments with wrong types (coerced or dropped)
      - Partial responses (some tool calls valid, some not)
      - Any future API changes (graceful degradation)

    Args:
        tool_name_map: {llm_tool_name: mcp_tool_name} for validation
        type_hints: {tool_name: {param: expected_type}} for coercion (optional)
    """

    def __init__(
        self,
        tool_name_map: Dict[str, str],
        type_hints: Optional[Dict[str, Dict[str, str]]] = None,
    ) -> None:
        self._tool_name_map = tool_name_map
        self._valid_tool_names: Set[str] = set(tool_name_map.keys())
        self._type_hints = type_hints or {}

    def normalize(self, response: Optional[LLMResponse]) -> NormalizedLLMOutput:
        """Main entry — normalize any LLMResponse.

        This method NEVER raises. Any exception is caught and returned
        as a non-usable output with failure_reason.
        """
        try:
            return self._do_normalize(response)
        except Exception as e:
            logger.error("Normalizer unexpected error: %s", e, exc_info=True)
            return NormalizedLLMOutput(
                usable=False,
                failure_reason=f"Internal normalizer error: {type(e).__name__}: {e}",
                raw_metadata={"exception": str(e)},
            )

    def _do_normalize(self, response: Optional[LLMResponse]) -> NormalizedLLMOutput:
        """Core normalization logic."""
        # Case 1: None/empty response
        if response is None:
            return NormalizedLLMOutput(
                usable=False,
                failure_reason="LLM returned None response (possible network error or quota exceeded)",
            )

        # Extract raw metadata for debugging
        metadata: Dict[str, Any] = {}
        if response.usage:
            metadata["prompt_tokens"] = response.usage.prompt_tokens
            metadata["completion_tokens"] = response.usage.completion_tokens
            metadata["total_tokens"] = response.usage.total_tokens

        # Case 2: No content AND no tool calls → unusable
        has_content = bool(response.content and response.content.strip())
        has_tools = bool(response.tool_calls)

        if not has_content and not has_tools:
            return NormalizedLLMOutput(
                usable=False,
                failure_reason="LLM returned empty response (possible safety block or content filter)",
                raw_metadata=metadata,
            )

        # Case 3: Has tool calls → validate and normalize each
        normalized_tools: List[NormalizedToolCall] = []
        if has_tools:
            for tc in response.tool_calls:
                normalized = self._normalize_tool_call(tc)
                if normalized is not None:
                    normalized_tools.append(normalized)

        # Case 4: Had tool calls but ALL were invalid
        if has_tools and not normalized_tools and not has_content:
            tool_names = [tc.name for tc in response.tool_calls]
            return NormalizedLLMOutput(
                usable=False,
                failure_reason=f"LLM called unknown tools: {tool_names}. None matched registered tools.",
                raw_metadata=metadata,
            )

        # Case 5: Usable — has valid tool calls and/or text content
        text = response.content.strip() if has_content else ""
        return NormalizedLLMOutput(
            usable=True,
            tool_calls=normalized_tools,
            text=text,
            raw_metadata=metadata,
        )

    def _normalize_tool_call(self, tc: ToolCall) -> Optional[NormalizedToolCall]:
        """Validate and normalize a single tool call.

        Returns None if tool name is not recognized (filtered out).
        """
        # Validate tool name
        if tc.name not in self._valid_tool_names:
            logger.warning("Normalizer: unknown tool '%s' — skipping", tc.name)
            return None

        mcp_name = self._tool_name_map[tc.name]

        # Normalize arguments
        raw_args = tc.arguments if tc.arguments else {}
        if not isinstance(raw_args, dict):
            # Edge case: arguments is not a dict (shouldn't happen but safety)
            try:
                raw_args = dict(raw_args)
            except (TypeError, ValueError):
                raw_args = {}

        # Type coercion
        coerced_args, warnings = self._coerce_arguments(tc.name, raw_args)

        return NormalizedToolCall(
            name=tc.name,
            mcp_name=mcp_name,
            arguments=coerced_args,
            validation_warnings=warnings,
        )

    def _coerce_arguments(
        self,
        tool_name: str,
        args: Dict[str, Any],
    ) -> tuple[Dict[str, Any], List[str]]:
        """Coerce argument types based on hints. Drop uncoercible.

        Returns (coerced_args, warnings).
        """
        hints = self._type_hints.get(tool_name, {})
        if not hints:
            # No hints available — pass through as-is
            return args, []

        coerced: Dict[str, Any] = {}
        warnings: List[str] = []

        for key, value in args.items():
            expected_type = hints.get(key)
            if expected_type is None:
                # No hint — pass through
                coerced[key] = value
                continue

            coerced_value = self._try_coerce(value, expected_type)
            if coerced_value is not None:
                coerced[key] = coerced_value
            else:
                warnings.append(f"Dropped '{key}': cannot coerce {type(value).__name__} to {expected_type}")

        return coerced, warnings

    @staticmethod
    def _try_coerce(value: Any, expected_type: str) -> Any:
        """Attempt type coercion. Returns None if impossible."""
        if value is None:
            return None

        try:
            if expected_type in ("integer", "int"):
                if isinstance(value, int):
                    return value
                if isinstance(value, str) and value.strip().isdigit():
                    return int(value.strip())
                if isinstance(value, float):
                    return int(value)
                return None

            elif expected_type in ("string", "str"):
                return str(value)

            elif expected_type in ("boolean", "bool"):
                if isinstance(value, bool):
                    return value
                if isinstance(value, str):
                    if value.lower() in ("true", "1", "yes"):
                        return True
                    if value.lower() in ("false", "0", "no"):
                        return False
                return None

            elif expected_type == "array":
                if isinstance(value, list):
                    return value
                if isinstance(value, str):
                    # Try JSON parse
                    import json
                    try:
                        parsed = json.loads(value)
                        if isinstance(parsed, list):
                            return parsed
                    except json.JSONDecodeError:
                        pass
                return None

            elif expected_type == "object":
                if isinstance(value, dict):
                    return value
                return None

        except (ValueError, TypeError):
            return None

        # Unknown type — pass through
        return value

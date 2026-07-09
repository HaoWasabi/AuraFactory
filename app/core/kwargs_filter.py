"""Runtime kwargs filter — lightweight safety net for **kwargs pattern.

Validates and filters kwargs BEFORE they are spread into Nextcord API calls.
Derived entirely from tools_spec.yaml via SpecRegistry.

This is the LAST line of defense:
  Layer 1: Graph retrieval → only relevant tools in prompt
  Layer 2: Schema → LLM knows valid params
  Layer 3: THIS → drops any hallucinated/invalid params at runtime
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional, Tuple

from app.core.spec_loader import SpecRegistry, ToolSpec

logger = logging.getLogger(__name__)


class KwargsFilter:
    """Runtime filter that validates kwargs against the spec whitelist.

    Usage:
        filter = KwargsFilter(registry)
        clean, dropped = filter.validate(
            "discord.channels.create",
            {"topic": "Hello", "invalid_param": 123, "nsfw": True},
            context="text"
        )
        # clean = {"topic": "Hello", "nsfw": True}
        # dropped = ["invalid_param"]
    """

    def __init__(self, registry: SpecRegistry) -> None:
        self._registry = registry

    def validate(
        self,
        tool_name: str,
        kwargs: Dict[str, Any],
        context: Optional[str] = None,
    ) -> Tuple[Dict[str, Any], list]:
        """Filter kwargs to only spec-allowed params.

        Invalid params are logged as warnings and dropped (not hard errors).
        LLM may hallucinate extra fields — this should not crash the tool.

        Args:
            tool_name: Fully qualified tool name (e.g. "discord.channels.create").
            kwargs: Raw kwargs from LLM-generated plan.
            context: Sub-context (e.g. channel type "text", "voice").

        Returns:
            Tuple of (clean_kwargs, dropped_param_names).
        """
        tool_spec = self._registry.get_tool(tool_name)
        if tool_spec is None:
            # No spec found — pass through (read-only / custom tools)
            logger.debug("No spec for tool '%s' — passing all kwargs", tool_name)
            return kwargs, []

        allowed = tool_spec.get_allowed_params(context)

        clean: Dict[str, Any] = {}
        dropped: list = []

        for key, value in kwargs.items():
            if key in allowed:
                clean[key] = value
            else:
                dropped.append(key)

        if dropped:
            logger.warning(
                "[KwargsFilter] Tool '%s' (ctx=%s): dropped invalid params: %s",
                tool_name,
                context,
                dropped,
            )

        return clean, dropped

    def validate_and_coerce(
        self,
        tool_name: str,
        kwargs: Dict[str, Any],
        context: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Filter + type coercion. Returns only clean kwargs.

        Attempts basic type coercion:
          - string "123" → int 123 if spec says integer
          - string "true"/"false" → bool
          - string "#ff0000" kept as-is (color handling done in connector)
        """
        clean, _ = self.validate(tool_name, kwargs, context)

        tool_spec = self._registry.get_tool(tool_name)
        if tool_spec is None:
            return clean

        # Gather all param definitions for type info
        all_params: Dict[str, Any] = {}
        all_params.update(tool_spec.shared_params)
        all_params.update(tool_spec.required_params)
        if context and context in tool_spec.context_params:
            all_params.update(tool_spec.context_params[context])

        coerced: Dict[str, Any] = {}
        for key, value in clean.items():
            param_def = all_params.get(key)
            if isinstance(param_def, dict):
                coerced[key] = self._coerce_value(value, param_def)
            else:
                coerced[key] = value

        return coerced

    @staticmethod
    def _coerce_value(value: Any, param_def: Dict[str, Any]) -> Any:
        """Attempt type coercion based on spec definition."""
        expected_type = param_def.get("type", "string")

        if value is None:
            return value

        try:
            if expected_type in ("integer", "int"):
                if isinstance(value, str) and value.isdigit():
                    return int(value)
                if isinstance(value, (int, float)):
                    return int(value)

            elif expected_type in ("boolean", "bool"):
                if isinstance(value, str):
                    if value.lower() in ("true", "1", "yes"):
                        return True
                    if value.lower() in ("false", "0", "no"):
                        return False

            elif expected_type == "number":
                if isinstance(value, str):
                    return float(value)

            elif expected_type == "array":
                if isinstance(value, str):
                    # Try to parse JSON-like list
                    import json
                    try:
                        parsed = json.loads(value)
                        if isinstance(parsed, list):
                            return parsed
                    except json.JSONDecodeError:
                        pass
        except (ValueError, TypeError):
            pass

        return value

    def check_dependencies(
        self,
        tool_name: str,
        kwargs: Dict[str, Any],
        context: Optional[str] = None,
    ) -> list:
        """Check if dependency conditions are met for conditional params.

        Returns list of warnings for params that are provided but their
        dependency is not met (e.g. allowed_role_ids without is_private=True).
        """
        tool_spec = self._registry.get_tool(tool_name)
        if tool_spec is None:
            return []

        deps = tool_spec.get_dependencies(context)
        warnings = []

        for param_name, condition in deps.items():
            if param_name not in kwargs:
                continue
            # Check if the condition is met
            for dep_param, dep_value in condition.items():
                actual = kwargs.get(dep_param)
                if actual != dep_value:
                    warnings.append(
                        f"Param '{param_name}' requires '{dep_param}={dep_value}' "
                        f"but got '{dep_param}={actual}'. Param will be ignored."
                    )

        return warnings

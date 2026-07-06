"""SkillValidator — validates tool invocation parameters.

Checks required params are present, performs basic type coercion,
and validates enum values before tool execution.
"""

from __future__ import annotations

import logging
from typing import Any

from app.skills.loader import SkillParameter, SkillTool
from app.skills.registry import SkillRegistry

logger = logging.getLogger(__name__)

# Type coercion mappings
TYPE_COERCIONS: dict[str, type] = {
    "str": str,
    "string": str,
    "int": int,
    "integer": int,
    "float": float,
    "number": float,
    "bool": bool,
    "boolean": bool,
    "list": list,
    "array": list,
    "dict": dict,
    "object": dict,
}


class SkillValidator:
    """Validates tool invocation parameters before execution.

    Checks:
    - All required parameters are present
    - Parameter types can be coerced to expected types
    - Unknown parameters are flagged as warnings
    """

    def validate_params(
        self, tool_name: str, params: dict[str, Any], registry: SkillRegistry
    ) -> tuple[bool, list[str]]:
        """Validate parameters for a tool invocation.

        Args:
            tool_name: Full MCP tool name (e.g., discord.channels.create).
            params: Dict of parameter name -> value to validate.
            registry: SkillRegistry to look up tool definitions.

        Returns:
            Tuple of (is_valid: bool, errors: list[str]).
            If is_valid is True, errors will be empty.
        """
        errors: list[str] = []

        # Look up tool definition
        tool = registry.get_tool(tool_name)
        if tool is None:
            errors.append(f"Unknown tool: {tool_name}")
            return False, errors

        # Check required parameters
        for param_def in tool.parameters:
            if param_def.required and param_def.name not in params:
                errors.append(f"Missing required parameter: {param_def.name}")

        # Validate provided parameters
        param_names = {p.name for p in tool.parameters}
        for key, value in params.items():
            # Check for unknown parameters
            if key not in param_names:
                errors.append(f"Unknown parameter: {key}")
                continue

            # Find parameter definition
            param_def = self._find_param(tool, key)
            if param_def is None:
                continue

            # Type validation
            type_error = self._validate_type(key, value, param_def)
            if type_error:
                errors.append(type_error)

        is_valid = len(errors) == 0
        if not is_valid:
            logger.warning("Validation failed for %s: %s", tool_name, errors)
        else:
            logger.debug("Validation passed for %s with %d params", tool_name, len(params))

        return is_valid, errors

    def coerce_params(
        self, tool_name: str, params: dict[str, Any], registry: SkillRegistry
    ) -> dict[str, Any]:
        """Attempt to coerce parameters to their expected types.

        Args:
            tool_name: Full MCP tool name.
            params: Raw parameter dict.
            registry: SkillRegistry for lookup.

        Returns:
            New dict with coerced values (original preserved on failure).
        """
        tool = registry.get_tool(tool_name)
        if tool is None:
            return params

        coerced: dict[str, Any] = {}
        for key, value in params.items():
            param_def = self._find_param(tool, key)
            if param_def is None:
                coerced[key] = value
                continue

            coerced[key] = self._coerce_value(value, param_def.type)

        return coerced

    @staticmethod
    def _find_param(tool: SkillTool, name: str) -> SkillParameter | None:
        """Find a parameter definition by name.

        Args:
            tool: SkillTool to search.
            name: Parameter name.

        Returns:
            SkillParameter or None.
        """
        for param in tool.parameters:
            if param.name == name:
                return param
        return None

    @staticmethod
    def _validate_type(name: str, value: Any, param_def: SkillParameter) -> str | None:
        """Validate value type against parameter definition.

        Args:
            name: Parameter name.
            value: Value to validate.
            param_def: Parameter definition.

        Returns:
            Error string or None if valid.
        """
        expected_type = TYPE_COERCIONS.get(param_def.type.lower())
        if expected_type is None:
            return None  # Unknown type, skip validation

        # None is allowed for optional params
        if value is None and not param_def.required:
            return None

        # Try coercion
        try:
            if expected_type == bool:
                # Special handling for bool — don't coerce strings to bool normally
                if not isinstance(value, bool) and not isinstance(value, int):
                    if isinstance(value, str) and value.lower() in ("true", "false", "1", "0"):
                        pass  # Valid bool string
                    else:
                        return f"Parameter '{name}' expected bool, got {type(value).__name__}"
            else:
                expected_type(value)
        except (ValueError, TypeError):
            return f"Parameter '{name}' expected {param_def.type}, got {type(value).__name__}: {value!r}"

        return None

    @staticmethod
    def _coerce_value(value: Any, type_str: str) -> Any:
        """Attempt to coerce a value to the expected type.

        Args:
            value: Raw value.
            type_str: Expected type string.

        Returns:
            Coerced value or original on failure.
        """
        target_type = TYPE_COERCIONS.get(type_str.lower())
        if target_type is None:
            return value

        if value is None:
            return value

        try:
            if target_type == bool:
                if isinstance(value, str):
                    return value.lower() in ("true", "1", "yes")
                return bool(value)
            return target_type(value)
        except (ValueError, TypeError):
            return value

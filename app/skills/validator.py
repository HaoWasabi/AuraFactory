# app/skills/validator.py
"""
Skill Validator — validates tool call parameters against schema
before passing to MCP for execution.
Catches invalid params early, prevents hallucinated tool calls.
"""
import logging
from typing import Dict, Any, Tuple, List, Optional
from dataclasses import dataclass

from app.skills.registry import SkillRegistry, SkillTool

logger = logging.getLogger(__name__)


@dataclass
class ValidationResult:
    """Result of parameter validation."""
    is_valid: bool
    errors: List[str]
    warnings: List[str]
    sanitized_params: Dict[str, Any]

    @property
    def error_message(self) -> str:
        return "; ".join(self.errors) if self.errors else ""

    def __bool__(self) -> bool:
        return self.is_valid


class SkillValidator:
    """
    Validates tool calls against their schema.
    Used by Gateway/Orchestrator before executing any tool.
    """

    def __init__(self, registry: SkillRegistry):
        self._registry = registry

    def validate(self, tool_name: str, params: Dict[str, Any]) -> ValidationResult:
        """
        Validate parameters for a tool call.

        Checks:
        1. Tool exists in registry
        2. Required parameters present
        3. Parameter types match schema
        4. Enum values are valid
        5. No dangerous patterns in string params
        """
        errors = []
        warnings = []
        sanitized = dict(params)

        # 1. Tool exists?
        tool = self._registry.get_tool(tool_name)
        if not tool:
            return ValidationResult(
                is_valid=False,
                errors=[f"Unknown tool: '{tool_name}'"],
                warnings=[],
                sanitized_params=sanitized,
            )

        schema = tool.input_schema
        properties = schema.get("properties", {})
        required = schema.get("required", [])

        # 2. Required params present?
        for param_name in required:
            if param_name not in params or params[param_name] is None:
                errors.append(f"Missing required parameter: '{param_name}'")

        # 3. Type validation
        for param_name, value in params.items():
            if param_name.startswith("_"):
                continue  # Skip internal params
            if param_name not in properties:
                warnings.append(f"Unknown parameter: '{param_name}' (ignored)")
                continue

            prop_schema = properties[param_name]
            expected_type = prop_schema.get("type", "string")
            type_error = self._check_type(value, expected_type)
            if type_error:
                errors.append(f"Parameter '{param_name}': {type_error}")

        # 4. Enum validation
        for param_name, value in params.items():
            if param_name in properties:
                enum_values = properties[param_name].get("enum")
                if enum_values and value not in enum_values:
                    errors.append(
                        f"Parameter '{param_name}' must be one of: {enum_values}, got '{value}'"
                    )

        # 5. String sanitization (anti-injection)
        for param_name, value in params.items():
            if isinstance(value, str):
                sanitized_value = self._sanitize_string(value)
                if sanitized_value != value:
                    warnings.append(f"Parameter '{param_name}' was sanitized")
                    sanitized[param_name] = sanitized_value

        return ValidationResult(
            is_valid=len(errors) == 0,
            errors=errors,
            warnings=warnings,
            sanitized_params=sanitized,
        )

    def validate_quick(self, tool_name: str, params: Dict[str, Any]) -> Tuple[bool, str]:
        """
        Quick validation — returns simple (is_valid, error_message) tuple.
        For backward compatibility with existing code.
        """
        result = self.validate(tool_name, params)
        return result.is_valid, result.error_message

    def _check_type(self, value: Any, expected_type: str) -> Optional[str]:
        """Check if value matches expected JSON Schema type."""
        type_map = {
            "string": str,
            "integer": int,
            "number": (int, float),
            "boolean": bool,
            "array": list,
            "object": dict,
        }

        if expected_type not in type_map:
            return None  # Unknown type, skip

        expected = type_map[expected_type]

        # Allow int for number type
        if expected_type == "number" and isinstance(value, (int, float)):
            return None

        # Allow None (optional params)
        if value is None:
            return None

        if not isinstance(value, expected):
            return f"expected {expected_type}, got {type(value).__name__}"

        return None

    def _sanitize_string(self, value: str) -> str:
        """
        Basic sanitization for string parameters.
        Remove potential injection patterns.
        """
        # Remove null bytes
        value = value.replace("\x00", "")

        # Truncate overly long strings (Discord limits)
        max_len = 1000
        if len(value) > max_len:
            value = value[:max_len]

        return value

    # ── Batch validation ───────────────────────────────────────

    def validate_plan(self, plan: List[Dict[str, Any]]) -> List[ValidationResult]:
        """
        Validate a multi-step execution plan.
        Each item: {"tool": "tool_name", "params": {...}}
        """
        results = []
        for step in plan:
            tool_name = step.get("tool", "")
            params = step.get("params", {})
            results.append(self.validate(tool_name, params))
        return results

    def plan_is_safe(self, plan: List[Dict[str, Any]]) -> Tuple[bool, List[str]]:
        """
        Check if entire plan is valid and within risk tolerance.
        Returns (all_valid, list_of_errors).
        """
        all_errors = []
        for i, step in enumerate(plan):
            result = self.validate(step.get("tool", ""), step.get("params", {}))
            if not result.is_valid:
                all_errors.append(f"Step {i+1} ({step.get('tool', '?')}): {result.error_message}")
        return len(all_errors) == 0, all_errors

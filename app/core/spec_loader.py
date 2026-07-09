"""Spec Loader — Reads tools_spec.yaml and provides structured access.

This is the central registry. All other components (graph, schema generator,
runtime filter, MCP tool definitions) derive from this single source of truth.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

import yaml

logger = logging.getLogger(__name__)

# Default spec path (relative to project root)
_DEFAULT_SPEC_PATH = Path(__file__).parent.parent.parent / "tools_spec.yaml"


class ToolSpec:
    """Parsed representation of a single tool from the spec."""

    def __init__(self, name: str, data: Dict[str, Any]) -> None:
        self.name = name
        self.description: str = data.get("description", "")
        self.required_params: Dict[str, Any] = data.get("required_params", {}) or {}
        self.context_params: Dict[str, Dict[str, Any]] = data.get("context_params", {}) or {}
        self.shared_params: Dict[str, Any] = data.get("shared_params", {}) or {}
        self.required_permissions: List[str] = data.get("required_permissions", [])
        self.risk_level: str = data.get("risk_level", "medium")
        self.constraints: List[str] = data.get("constraints", [])
        self.graph_edges: List[Dict[str, str]] = data.get("graph_edges", [])

    @property
    def module(self) -> str:
        """Extract module name from tool name (e.g. 'channels' from 'discord.channels.create')."""
        parts = self.name.split(".")
        return parts[1] if len(parts) >= 3 else ""

    @property
    def action(self) -> str:
        """Extract action name (e.g. 'create' from 'discord.channels.create')."""
        parts = self.name.split(".")
        return parts[2] if len(parts) >= 3 else ""

    def get_allowed_params(self, context: Optional[str] = None) -> Set[str]:
        """Get all allowed param names for a given context.

        Returns:
            Set of param names that are valid for this tool + context.
        """
        allowed = set(self.required_params.keys())
        allowed.update(self.shared_params.keys())
        if context and context in self.context_params:
            allowed.update(self.context_params[context].keys())
        return allowed

    def get_context_keys(self) -> List[str]:
        """Get all valid context values (e.g. ['text', 'voice', 'stage', 'forum', 'news'])."""
        return list(self.context_params.keys())

    def get_dependencies(self, context: Optional[str] = None) -> Dict[str, Dict[str, Any]]:
        """Get params that have depends_on conditions.

        Returns:
            {param_name: {depends_on_param: required_value}}
        """
        deps = {}
        all_params = {**self.shared_params}
        if context and context in self.context_params:
            all_params.update(self.context_params[context])

        for param_name, param_def in all_params.items():
            if isinstance(param_def, dict) and "depends_on" in param_def:
                deps[param_name] = param_def["depends_on"]
        return deps


class SpecRegistry:
    """Central registry loaded from tools_spec.yaml.

    Usage:
        registry = SpecRegistry.load()
        tool = registry.get_tool("discord.channels.create")
        allowed = tool.get_allowed_params(context="voice")
    """

    def __init__(self, raw: Dict[str, Any]) -> None:
        self._raw = raw
        self._tools: Dict[str, ToolSpec] = {}
        self._metadata: Dict[str, Any] = raw.get("metadata", {})
        self._global_edges: List[Dict[str, str]] = raw.get("graph_global_edges", [])
        self._parse_tools()

    def _parse_tools(self) -> None:
        """Parse all tool entries from raw YAML."""
        for key, value in self._raw.items():
            if key.startswith("discord.") and isinstance(value, dict):
                self._tools[key] = ToolSpec(key, value)
        logger.info("SpecRegistry loaded %d tools", len(self._tools))

    @classmethod
    def load(cls, path: Optional[Path] = None) -> "SpecRegistry":
        """Load spec from YAML file.

        Args:
            path: Path to tools_spec.yaml. Uses default if None.

        Returns:
            Populated SpecRegistry instance.
        """
        spec_path = path or _DEFAULT_SPEC_PATH
        if not spec_path.exists():
            raise FileNotFoundError(f"tools_spec.yaml not found at {spec_path}")

        with open(spec_path, "r", encoding="utf-8") as f:
            raw = yaml.safe_load(f)

        return cls(raw)

    # ------------------------------------------------------------------
    # Lookup methods
    # ------------------------------------------------------------------

    def get_tool(self, name: str) -> Optional[ToolSpec]:
        """Get a tool spec by fully-qualified name."""
        return self._tools.get(name)

    def get_all_tools(self) -> Dict[str, ToolSpec]:
        """Get all registered tools."""
        return self._tools.copy()

    def get_tools_by_module(self, module: str) -> List[ToolSpec]:
        """Get all tools for a module (e.g. 'channels')."""
        return [t for t in self._tools.values() if t.module == module]

    def get_modules(self) -> List[str]:
        """Get list of all modules from metadata."""
        return self._metadata.get("modules", [])

    def get_global_edges(self) -> List[Dict[str, str]]:
        """Get cross-module graph edges."""
        return self._global_edges

    # ------------------------------------------------------------------
    # Schema generation (for MCP / LLM)
    # ------------------------------------------------------------------

    def generate_tool_definition(self, tool_name: str) -> Optional[Dict[str, Any]]:
        """Generate MCP-compatible ToolDefinition dict for a single tool.

        Returns JSON Schema format that can be injected into LLM context.
        """
        tool = self.get_tool(tool_name)
        if tool is None:
            return None

        properties: Dict[str, Any] = {"guild_id": {"type": "string", "description": "Target guild ID"}}
        required: List[str] = ["guild_id"]

        # Required params
        for param_name, param_def in tool.required_params.items():
            if isinstance(param_def, dict):
                prop = self._param_to_json_schema(param_def)
                properties[param_name] = prop
                required.append(param_name)

        # Shared params (optional)
        for param_name, param_def in tool.shared_params.items():
            if isinstance(param_def, dict):
                properties[param_name] = self._param_to_json_schema(param_def)

        # Context params — flattened with descriptions noting context
        for ctx_name, ctx_params in tool.context_params.items():
            for param_name, param_def in ctx_params.items():
                if param_name not in properties and isinstance(param_def, dict):
                    schema = self._param_to_json_schema(param_def)
                    schema["description"] = schema.get("description", "") + f" [applies to: {ctx_name}]"
                    properties[param_name] = schema

        return {
            "name": tool_name,
            "description": tool.description,
            "parameters": {
                "type": "object",
                "properties": properties,
                "required": required,
            },
            "risk_level": tool.risk_level,
        }

    def generate_all_definitions(self) -> List[Dict[str, Any]]:
        """Generate all tool definitions for MCP registration."""
        definitions = []
        for tool_name in self._tools:
            defn = self.generate_tool_definition(tool_name)
            if defn:
                definitions.append(defn)
        return definitions

    @staticmethod
    def _param_to_json_schema(param_def: Dict[str, Any]) -> Dict[str, Any]:
        """Convert a spec param definition to JSON Schema property."""
        schema: Dict[str, Any] = {}

        p_type = param_def.get("type", "string")
        type_map = {
            "string": "string",
            "integer": "integer",
            "int": "integer",
            "boolean": "boolean",
            "bool": "boolean",
            "number": "number",
            "array": "array",
            "object": "object",
        }
        schema["type"] = type_map.get(p_type, "string")

        if "description" in param_def:
            schema["description"] = param_def["description"]
        if "enum" in param_def:
            schema["enum"] = param_def["enum"]
        if "default" in param_def:
            schema["default"] = param_def["default"]
        if "items" in param_def:
            items = param_def["items"]
            if isinstance(items, str):
                schema["items"] = {"type": type_map.get(items, items)}
            elif isinstance(items, dict):
                schema["items"] = items
        if "properties" in param_def:
            schema["properties"] = param_def["properties"]

        return schema

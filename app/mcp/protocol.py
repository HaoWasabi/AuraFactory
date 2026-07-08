"""MCP Protocol data structures."""
from __future__ import annotations
from dataclasses import dataclass, field
from enum import IntEnum
from typing import Any, Dict, List, Optional
import uuid


class RiskLevel(IntEnum):
    LOW = 1
    MEDIUM = 2
    HIGH = 3
    CRITICAL = 4


@dataclass
class ToolDefinition:
    """Definition of a tool available via MCP."""
    name: str                          # e.g. 'discord.channels.create'
    description: str
    parameters: Dict[str, Any] = field(default_factory=dict)  # JSON Schema for params
    risk: RiskLevel = RiskLevel.MEDIUM
    category: str = ""                 # e.g. 'setup', 'moderation'
    risk_level: str = ""               # Compat alias: "low"/"medium"/"high"/"critical"

    def __post_init__(self):
        """Convert risk_level string to RiskLevel enum if provided."""
        if self.risk_level and not isinstance(self.risk, RiskLevel):
            self.risk = self._parse_risk(self.risk_level)
        elif self.risk_level:
            self.risk = self._parse_risk(self.risk_level)

    @staticmethod
    def _parse_risk(level: str) -> RiskLevel:
        mapping = {"low": RiskLevel.LOW, "medium": RiskLevel.MEDIUM, "high": RiskLevel.HIGH, "critical": RiskLevel.CRITICAL}
        return mapping.get(level.lower(), RiskLevel.MEDIUM)

    def to_llm_schema(self) -> Dict[str, Any]:
        """Convert to format suitable for LLM function calling."""
        return {
            "name": self.name,
            "description": self.description,
            "parameters": self.parameters,
        }

    def to_compact_schema(self) -> Dict[str, Any]:
        """Compact schema for planner prompt — only name, description, required params.

        Reduces token usage significantly vs full JSON Schema.
        """
        props = self.parameters.get("properties", {})
        required = self.parameters.get("required", [])
        # Build compact param list: "name(type): description"
        param_lines = []
        for pname, pdef in props.items():
            if pname == "guild_id":
                continue  # always injected — skip from prompt
            ptype = pdef.get("type", "any")
            pdesc = pdef.get("description", "")
            req_marker = "*" if pname in required else ""
            # Truncate long descriptions
            if len(pdesc) > 80:
                pdesc = pdesc[:77] + "..."
            param_lines.append(f"  {pname}{req_marker}({ptype}): {pdesc}")
        params_str = "\n".join(param_lines) if param_lines else "  (no extra params)"
        return {
            "name": self.name,
            "description": self.description[:120] + ("..." if len(self.description) > 120 else ""),
            "params": params_str,
        }


@dataclass
class MCPRequest:
    """A request to invoke a tool."""
    method: str                        # tool name
    params: Dict[str, Any] = field(default_factory=dict)
    request_id: str = field(default_factory=lambda: str(uuid.uuid4()))


@dataclass
class MCPResponse:
    """Response from a tool invocation."""
    result: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    request_id: str = ""

    @property
    def success(self) -> bool:
        return self.error is None

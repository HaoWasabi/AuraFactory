"""
MCP Protocol — Data classes for the Model Context Protocol layer.

Defines the core types used across the MCP system:
- ToolDefinition: metadata for a registered tool
- MCPRequest / MCPResponse: request/response envelope
- RiskLevel: enum for tool risk classification
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from enum import IntEnum
from typing import Any, Optional


class RiskLevel(IntEnum):
    """Risk classification for MCP tools.

    Higher values = more dangerous operations.
    Agents are filtered to only access tools at or below their clearance.
    """

    LOW = 1
    MEDIUM = 2
    HIGH = 3
    CRITICAL = 4

    @classmethod
    def from_string(cls, value: str) -> "RiskLevel":
        """Parse a risk level from string (case-insensitive)."""
        mapping = {
            "low": cls.LOW,
            "medium": cls.MEDIUM,
            "high": cls.HIGH,
            "critical": cls.CRITICAL,
        }
        normalized = value.strip().lower()
        if normalized not in mapping:
            raise ValueError(
                f"Invalid risk level '{value}'. "
                f"Must be one of: {list(mapping.keys())}"
            )
        return mapping[normalized]

    def __str__(self) -> str:
        return self.name.lower()


@dataclass(frozen=True)
class ToolDefinition:
    """Metadata describing a single MCP tool.

    Attributes:
        name: Fully-qualified tool name (e.g. 'discord.channels.create').
        description: Human-readable description for the LLM.
        parameters: JSON-Schema-style dict describing accepted params.
        risk_level: Risk classification (low|medium|high|critical).
    """

    name: str
    description: str
    parameters: dict = field(default_factory=dict)
    risk_level: str = "low"

    @property
    def risk(self) -> RiskLevel:
        """Return the parsed RiskLevel enum value."""
        return RiskLevel.from_string(self.risk_level)

    def to_dict(self) -> dict:
        """Serialize to a plain dict (for LLM tool manifests)."""
        return {
            "name": self.name,
            "description": self.description,
            "parameters": self.parameters,
            "risk_level": self.risk_level,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "ToolDefinition":
        """Deserialize from a plain dict."""
        return cls(
            name=data["name"],
            description=data["description"],
            parameters=data.get("parameters", {}),
            risk_level=data.get("risk_level", "low"),
        )


@dataclass
class MCPRequest:
    """Incoming request to an MCP server.

    Attributes:
        method: The tool name to invoke (e.g. 'discord.channels.create').
        params: Parameters to pass to the tool handler.
        request_id: Unique identifier for tracing; auto-generated if omitted.
    """

    method: str
    params: dict = field(default_factory=dict)
    request_id: str = field(default_factory=lambda: str(uuid.uuid4()))

    def to_dict(self) -> dict:
        return {
            "method": self.method,
            "params": self.params,
            "request_id": self.request_id,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "MCPRequest":
        return cls(
            method=data["method"],
            params=data.get("params", {}),
            request_id=data.get("request_id", str(uuid.uuid4())),
        )


@dataclass
class MCPResponse:
    """Response from an MCP server after handling a request.

    Attributes:
        result: The return value from the tool (None on error).
        error: Error message if the tool failed; None on success.
        request_id: Echoed from the corresponding MCPRequest.
    """

    result: Any = None
    error: Optional[str] = None
    request_id: str = ""

    @property
    def success(self) -> bool:
        """True if no error occurred."""
        return self.error is None

    def to_dict(self) -> dict:
        return {
            "result": self.result,
            "error": self.error,
            "request_id": self.request_id,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "MCPResponse":
        return cls(
            result=data.get("result"),
            error=data.get("error"),
            request_id=data.get("request_id", ""),
        )

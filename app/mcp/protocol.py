# app/mcp/protocol.py
"""
MCP Protocol Types — JSON-RPC 2.0 based.
Defines the message format for tool calls between client ↔ server.
Follows Model Context Protocol spec.
"""
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional
from enum import Enum


# ============================================================
# Core Protocol Types
# ============================================================

@dataclass
class ToolDefinition:
    """MCP tool definition — exposed by servers."""
    name: str
    description: str
    input_schema: Dict[str, Any]  # JSON Schema for parameters
    server_name: str = ""         # Which server provides this tool


@dataclass
class ToolCallRequest:
    """Client → Server: execute a tool."""
    id: str                       # Request ID (for response matching)
    method: str = "tools/call"
    tool_name: str = ""
    arguments: Dict[str, Any] = field(default_factory=dict)
    # Context passed alongside
    trace_id: str = ""
    guild_id: Optional[int] = None


@dataclass
class ToolCallResponse:
    """Server → Client: tool execution result."""
    id: str                       # Matches request ID
    success: bool = True
    result: Dict[str, Any] = field(default_factory=dict)
    error: Optional[str] = None
    execution_time_ms: float = 0.0


@dataclass
class ListToolsRequest:
    """Client → Server: list available tools."""
    id: str
    method: str = "tools/list"


@dataclass
class ListToolsResponse:
    """Server → Client: available tools."""
    id: str
    tools: List[ToolDefinition] = field(default_factory=list)


# ============================================================
# Server Info
# ============================================================

@dataclass
class ServerInfo:
    """Metadata about an MCP server."""
    name: str
    version: str = "1.0.0"
    description: str = ""
    tool_count: int = 0


class TransportType(str, Enum):
    """MCP transport types."""
    IN_PROCESS = "in_process"   # Phase 1: direct function call
    STDIO = "stdio"             # Phase 2: subprocess communication
    SSE = "sse"                 # Phase 2: HTTP Server-Sent Events

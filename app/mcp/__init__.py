"""
MCP Layer — Model Context Protocol implementation for AuraFactory.

Phase 1: In-process tool routing (direct async function calls).
No stdio/SSE transport — servers are called directly via MCPServer.handle_request().

Exports:
    MCPClient: Aggregator that routes tool calls to registered servers.
    MCPServer: Abstract base class for implementing tool servers.
    MCPRequest: Request envelope for tool invocations.
    MCPResponse: Response envelope with result or error.
    ToolDefinition: Metadata describing a single tool.
    RiskLevel: Enum for tool risk classification.
"""

from app.mcp.client import MCPClient
from app.mcp.protocol import MCPRequest, MCPResponse, RiskLevel, ToolDefinition
from app.mcp.server import MCPServer

__all__ = [
    "MCPClient",
    "MCPServer",
    "MCPRequest",
    "MCPResponse",
    "ToolDefinition",
    "RiskLevel",
]

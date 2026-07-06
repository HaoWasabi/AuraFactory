# app/mcp/__init__.py
"""
MCP (Model Context Protocol) Layer.
Unified tool calling interface for all AuraFactory tools.

Usage:
    from app.mcp import MCPClient, MCPServer
    from app.mcp.protocol import ToolDefinition, ToolCallRequest, ToolCallResponse
"""
from app.mcp.client import MCPClient
from app.mcp.server import MCPServer
from app.mcp.protocol import (
    ToolDefinition,
    ToolCallRequest,
    ToolCallResponse,
    ServerInfo,
    TransportType,
)

__all__ = [
    "MCPClient",
    "MCPServer",
    "ToolDefinition",
    "ToolCallRequest",
    "ToolCallResponse",
    "ServerInfo",
    "TransportType",
]

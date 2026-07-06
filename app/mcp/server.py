# app/mcp/server.py
"""
MCP Server Base — abstract class for all MCP tool servers.
Each server exposes a set of tools via the MCP protocol.
Phase 1: In-process (direct call). Phase 2: stdio/SSE transport.
"""
import time
import logging
from abc import ABC, abstractmethod
from typing import Dict, Any, List, Optional

from app.mcp.protocol import (
    ToolDefinition,
    ToolCallRequest,
    ToolCallResponse,
    ServerInfo,
)

logger = logging.getLogger(__name__)


class MCPServer(ABC):
    """
    Abstract MCP Server.
    Subclass this to create a tool server (Discord, Memory, etc.).
    """

    @property
    @abstractmethod
    def info(self) -> ServerInfo:
        """Server metadata."""
        ...

    @abstractmethod
    def list_tools(self) -> List[ToolDefinition]:
        """List all tools this server provides."""
        ...

    @abstractmethod
    async def call_tool(self, request: ToolCallRequest) -> ToolCallResponse:
        """Execute a tool call."""
        ...

    async def handle_request(self, request: ToolCallRequest) -> ToolCallResponse:
        """
        Main entry point — wraps call_tool with error handling + timing.
        """
        start = time.time()
        try:
            response = await self.call_tool(request)
            response.execution_time_ms = (time.time() - start) * 1000
            return response
        except Exception as e:
            logger.error(f"[{self.info.name}] Tool error: {request.tool_name} — {e}")
            return ToolCallResponse(
                id=request.id,
                success=False,
                error=str(e),
                execution_time_ms=(time.time() - start) * 1000,
            )

    def get_tool(self, name: str) -> Optional[ToolDefinition]:
        """Get a specific tool definition by name."""
        for tool in self.list_tools():
            if tool.name == name:
                return tool
        return None

    def has_tool(self, name: str) -> bool:
        """Check if this server provides a tool."""
        return any(t.name == name for t in self.list_tools())

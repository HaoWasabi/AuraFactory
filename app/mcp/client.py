# app/mcp/client.py
"""
MCP Client — unified interface for calling tools across all servers.
Orchestrator and agents use this to discover and execute tools.
Phase 1: In-process dispatch. Phase 2: route to remote servers.
"""
import logging
from typing import Dict, Any, List, Optional
from uuid import uuid4

from app.mcp.protocol import (
    ToolDefinition,
    ToolCallRequest,
    ToolCallResponse,
    ServerInfo,
)
from app.mcp.server import MCPServer

logger = logging.getLogger(__name__)


class MCPClient:
    """
    Central MCP client — routes tool calls to the correct server.
    All agent tool interactions go through this.
    """

    def __init__(self):
        self._servers: Dict[str, MCPServer] = {}
        self._tool_index: Dict[str, str] = {}  # tool_name → server_name

    def register_server(self, server: MCPServer) -> None:
        """Register an MCP server and index its tools."""
        name = server.info.name
        self._servers[name] = server

        # Index tools for fast lookup
        for tool in server.list_tools():
            self._tool_index[tool.name] = name
            tool.server_name = name

        logger.info(
            f"MCP: Registered server '{name}' with {len(server.list_tools())} tools"
        )

    def unregister_server(self, name: str) -> None:
        """Remove a server and its tools from the index."""
        if name in self._servers:
            server = self._servers[name]
            for tool in server.list_tools():
                self._tool_index.pop(tool.name, None)
            del self._servers[name]

    async def call_tool(
        self,
        tool_name: str,
        arguments: Dict[str, Any],
        trace_id: str = "",
        guild_id: Optional[int] = None,
        **kwargs,
    ) -> ToolCallResponse:
        """
        Call a tool by name. Routes to the correct server automatically.
        This is THE main API that agents use.
        """
        server_name = self._tool_index.get(tool_name)
        if not server_name:
            return ToolCallResponse(
                id=str(uuid4())[:8],
                success=False,
                error=f"Tool not found: '{tool_name}'. Available: {self.list_tool_names()[:20]}",
            )

        server = self._servers[server_name]
        request = ToolCallRequest(
            id=str(uuid4())[:8],
            tool_name=tool_name,
            arguments=arguments,
            trace_id=trace_id,
            guild_id=guild_id,
        )

        # Pass extra kwargs (like guild object)
        if kwargs:
            request.arguments["_context"] = kwargs

        return await server.handle_request(request)

    def list_tools(self, server_name: Optional[str] = None) -> List[ToolDefinition]:
        """List all available tools, optionally filtered by server."""
        if server_name:
            server = self._servers.get(server_name)
            return server.list_tools() if server else []

        all_tools = []
        for server in self._servers.values():
            all_tools.extend(server.list_tools())
        return all_tools

    def list_tool_names(self) -> List[str]:
        """List all tool names."""
        return list(self._tool_index.keys())

    def list_servers(self) -> List[ServerInfo]:
        """List all registered servers."""
        return [s.info for s in self._servers.values()]

    def get_tool_definition(self, name: str) -> Optional[ToolDefinition]:
        """Get a specific tool definition."""
        server_name = self._tool_index.get(name)
        if server_name:
            return self._servers[server_name].get_tool(name)
        return None

    def to_llm_format(self, server_name: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        Convert tools to LLM function-calling format.
        Ready to pass to LLM generate_with_tools().
        """
        tools = self.list_tools(server_name)
        return [
            {
                "name": t.name,
                "description": t.description,
                "parameters": t.input_schema,
            }
            for t in tools
        ]

    @property
    def server_count(self) -> int:
        return len(self._servers)

    @property
    def tool_count(self) -> int:
        return len(self._tool_index)

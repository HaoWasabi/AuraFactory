"""MCP Client — aggregates MCP servers and routes tool calls."""
from __future__ import annotations
from typing import Any, Dict, List, Optional

from .protocol import MCPRequest, MCPResponse, RiskLevel, ToolDefinition


class MCPServer:
    """Base MCP server that tools register handlers on."""

    def __init__(self) -> None:
        self._tools: Dict[str, ToolDefinition] = {}
        self._handlers: Dict[str, Any] = {}  # tool_name → async callable

    def register_tool(self, tool_def: ToolDefinition, handler) -> None:
        """Register a tool definition and its async handler."""
        self._tools[tool_def.name] = tool_def
        self._handlers[tool_def.name] = handler

    def list_tools(self) -> List[ToolDefinition]:
        """Return all registered tool definitions."""
        return list(self._tools.values())

    async def handle_request(self, request: MCPRequest) -> MCPResponse:
        """Dispatch a request to the appropriate handler."""
        handler = self._handlers.get(request.method)
        if not handler:
            return MCPResponse(
                error=f"Unknown tool: {request.method}",
                request_id=request.request_id,
            )
        try:
            result = await handler(**request.params)
            return MCPResponse(result=result, request_id=request.request_id)
        except Exception as e:
            return MCPResponse(error=str(e), request_id=request.request_id)

    def get_server_name(self) -> str:
        """Return the canonical name of this server (e.g. 'discord')."""
        raise NotImplementedError


class MCPClient:
    """Aggregates multiple MCP servers and routes calls to the correct one."""

    def __init__(self) -> None:
        self._servers: Dict[str, MCPServer] = {}       # server_name → server
        self._tool_index: Dict[str, str] = {}          # tool_name → server_name

    # ------------------------------------------------------------------
    # Registration
    # ------------------------------------------------------------------

    def register_server(self, server: MCPServer) -> None:
        """Register a server and index all its tools for routing."""
        name = server.get_server_name()
        self._servers[name] = server
        self._reindex_server(name, server)

    def reindex(self) -> None:
        """Re-index all tools from all registered servers.
        
        Call this after a server has registered new tools dynamically
        (e.g. after DiscordMCPServer.set_bot() is called).
        """
        for name, server in self._servers.items():
            self._reindex_server(name, server)

    def _reindex_server(self, name: str, server: MCPServer) -> None:
        """Index all tools from a specific server."""
        for tool in server.list_tools():
            self._tool_index[tool.name] = name

    # ------------------------------------------------------------------
    # Tool invocation
    # ------------------------------------------------------------------

    async def call_tool(self, method: str, params: Optional[Dict[str, Any]] = None) -> MCPResponse:
        """Route a tool call to the correct server and return its response."""
        server_name = self._tool_index.get(method)
        if server_name is None:
            return MCPResponse(error=f"No server registered for tool: {method}")

        server = self._servers[server_name]
        request = MCPRequest(method=method, params=params or {})
        return await server.handle_request(request)

    # ------------------------------------------------------------------
    # Discovery / filtering
    # ------------------------------------------------------------------

    def list_all_tools(self) -> List[ToolDefinition]:
        """Return every tool across all registered servers."""
        tools: List[ToolDefinition] = []
        for server in self._servers.values():
            tools.extend(server.list_tools())
        return tools

    def get_tools_by_risk(self, max_risk: RiskLevel) -> List[ToolDefinition]:
        """Return tools whose risk level is at or below *max_risk*."""
        return [t for t in self.list_all_tools() if t.risk <= max_risk]

    def get_tools_for_intent(self, intent: str) -> List[ToolDefinition]:
        """Return tools whose category matches the given intent keyword."""
        intent_lower = intent.lower()
        return [
            t for t in self.list_all_tools()
            if intent_lower in t.category.lower()
        ]

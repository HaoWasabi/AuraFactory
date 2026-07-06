"""
MCP Client — Aggregates multiple MCP servers and routes tool calls.

Phase 1: Pure in-process routing. The client keeps a registry of servers
and dispatches requests to the server that owns the requested tool.
"""

from __future__ import annotations

import logging
from typing import Dict, List, Optional

from app.mcp.protocol import MCPRequest, MCPResponse, RiskLevel, ToolDefinition
from app.mcp.server import MCPServer

logger = logging.getLogger(__name__)


class MCPClient:
    """Client-side MCP aggregator.

    Registers MCP servers, discovers tools across all of them,
    and routes tool calls to the appropriate server.
    """

    def __init__(self) -> None:
        self._servers: Dict[str, MCPServer] = {}
        # Reverse index: tool_name -> server_name for fast routing
        self._tool_index: Dict[str, str] = {}

    # ------------------------------------------------------------------
    # Server Registration
    # ------------------------------------------------------------------

    def register_server(self, server: MCPServer) -> None:
        """Register an MCP server and index its tools.

        Args:
            server: An initialized MCPServer instance.

        Raises:
            ValueError: If a server with the same name is already registered,
                        or if tool names collide across servers.
        """
        name = server.get_server_name()
        if name in self._servers:
            raise ValueError(f"Server '{name}' already registered")

        # Check for tool name collisions
        for tool_def in server.list_tools():
            if tool_def.name in self._tool_index:
                existing_server = self._tool_index[tool_def.name]
                raise ValueError(
                    f"Tool '{tool_def.name}' conflicts: already registered "
                    f"on server '{existing_server}'"
                )

        # Register
        self._servers[name] = server
        for tool_def in server.list_tools():
            self._tool_index[tool_def.name] = name

        logger.info(
            "Registered MCP server '%s' with %d tools",
            name,
            len(server.list_tools()),
        )

    def unregister_server(self, server_name: str) -> None:
        """Remove a server and its tools from the registry."""
        server = self._servers.pop(server_name, None)
        if server is None:
            return
        for tool_def in server.list_tools():
            self._tool_index.pop(tool_def.name, None)
        logger.info("Unregistered MCP server '%s'", server_name)

    # ------------------------------------------------------------------
    # Tool Invocation
    # ------------------------------------------------------------------

    async def call_tool(
        self, method: str, params: dict, request_id: Optional[str] = None
    ) -> MCPResponse:
        """Invoke a tool by name, routing to the correct server.

        Args:
            method: Fully-qualified tool name (e.g. 'discord.channels.create').
            params: Parameters to pass to the tool.
            request_id: Optional tracing ID (auto-generated if omitted).

        Returns:
            MCPResponse from the handling server.
        """
        request = MCPRequest(method=method, params=params)
        if request_id:
            request.request_id = request_id

        server_name = self._tool_index.get(method)
        if server_name is None:
            return MCPResponse(
                error=(
                    f"No server registered for tool '{method}'. "
                    f"Available tools: {list(self._tool_index.keys())[:20]}..."
                ),
                request_id=request.request_id,
            )

        server = self._servers[server_name]
        return await server.handle_request(request)

    # ------------------------------------------------------------------
    # Tool Discovery
    # ------------------------------------------------------------------

    def list_all_tools(self) -> List[ToolDefinition]:
        """Return all tool definitions from all registered servers."""
        tools: List[ToolDefinition] = []
        for server in self._servers.values():
            tools.extend(server.list_tools())
        return tools

    def get_tools_by_risk(self, max_risk: RiskLevel) -> List[ToolDefinition]:
        """Return tools at or below the given risk level.

        Args:
            max_risk: Maximum allowed RiskLevel (inclusive).

        Returns:
            List of ToolDefinitions whose risk <= max_risk.
        """
        return [
            tool
            for tool in self.list_all_tools()
            if tool.risk <= max_risk
        ]

    def get_tools_for_agent(
        self, agent_role: str, skill_registry: Optional[object] = None
    ) -> List[ToolDefinition]:
        """Return tools available to a specific agent role.

        The filtering logic uses the skill_registry (if provided) to
        determine which tools the agent is authorized to call based on
        its role and skill assignments.

        Args:
            agent_role: The agent's role identifier (e.g. 'moderator', 'admin').
            skill_registry: Optional SkillRegistry instance for role-based filtering.

        Returns:
            Filtered list of ToolDefinitions.
        """
        # Default risk ceilings per role
        role_risk_map: Dict[str, RiskLevel] = {
            "observer": RiskLevel.LOW,
            "helper": RiskLevel.MEDIUM,
            "moderator": RiskLevel.HIGH,
            "admin": RiskLevel.CRITICAL,
        }

        max_risk = role_risk_map.get(agent_role, RiskLevel.LOW)

        # If a skill_registry is provided, further filter by allowed skills
        if skill_registry is not None and hasattr(skill_registry, "get_tools_for_role"):
            allowed_tool_names: set = set(
                skill_registry.get_tools_for_role(agent_role)
            )
            return [
                tool
                for tool in self.list_all_tools()
                if tool.risk <= max_risk and tool.name in allowed_tool_names
            ]

        return self.get_tools_by_risk(max_risk)

    def get_server(self, server_name: str) -> Optional[MCPServer]:
        """Get a registered server by name."""
        return self._servers.get(server_name)

    @property
    def server_names(self) -> List[str]:
        """List all registered server names."""
        return list(self._servers.keys())

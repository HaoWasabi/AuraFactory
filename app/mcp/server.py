"""
MCP Server — Abstract base class for all MCP tool servers.

Each server exposes a set of tools under a namespace (e.g. 'discord', 'memory').
Phase 1: in-process direct function calls via handle_request().
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from typing import Any, Callable, Coroutine, Dict, List

from app.mcp.protocol import MCPRequest, MCPResponse, ToolDefinition

logger = logging.getLogger(__name__)

# Type alias for async tool handlers
ToolHandler = Callable[..., Coroutine[Any, Any, Any]]


class MCPServer(ABC):
    """Abstract base for MCP servers.

    Subclasses register tools in __init__ and implement get_server_name().
    The server dispatches incoming MCPRequests to the correct handler.
    """

    def __init__(self) -> None:
        self._tools: Dict[str, ToolDefinition] = {}
        self._handlers: Dict[str, ToolHandler] = {}

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def register_tool(self, tool_def: ToolDefinition, handler: ToolHandler) -> None:
        """Register a tool with its definition and async handler.

        Args:
            tool_def: The tool's metadata (name, description, params, risk).
            handler: An async callable that implements the tool logic.

        Raises:
            ValueError: If a tool with the same name is already registered.
        """
        if tool_def.name in self._tools:
            raise ValueError(
                f"Tool '{tool_def.name}' already registered on "
                f"server '{self.get_server_name()}'"
            )
        self._tools[tool_def.name] = tool_def
        self._handlers[tool_def.name] = handler
        logger.debug(
            "Registered tool '%s' on server '%s' (risk=%s)",
            tool_def.name,
            self.get_server_name(),
            tool_def.risk_level,
        )

    async def handle_request(self, request: MCPRequest) -> MCPResponse:
        """Route an MCPRequest to the registered handler and return the response.

        Phase 1: direct in-process invocation (no stdio/SSE transport).

        Args:
            request: The incoming MCP request.

        Returns:
            MCPResponse with either a result or an error.
        """
        handler = self._handlers.get(request.method)
        if handler is None:
            available = list(self._tools.keys())
            return MCPResponse(
                error=(
                    f"Unknown tool '{request.method}' on server "
                    f"'{self.get_server_name()}'. Available: {available}"
                ),
                request_id=request.request_id,
            )

        try:
            logger.info(
                "Executing tool '%s' (request_id=%s)",
                request.method,
                request.request_id,
            )
            result = await handler(**request.params)
            return MCPResponse(result=result, request_id=request.request_id)
        except PermissionError as exc:
            logger.warning(
                "Permission denied for tool '%s': %s",
                request.method,
                exc,
            )
            return MCPResponse(
                error=f"PermissionError: {exc}",
                request_id=request.request_id,
            )
        except ValueError as exc:
            logger.warning(
                "Validation error for tool '%s': %s",
                request.method,
                exc,
            )
            return MCPResponse(
                error=f"ValidationError: {exc}",
                request_id=request.request_id,
            )
        except Exception as exc:
            logger.exception(
                "Unhandled error in tool '%s' (request_id=%s)",
                request.method,
                request.request_id,
            )
            return MCPResponse(
                error=f"{type(exc).__name__}: {exc}",
                request_id=request.request_id,
            )

    def list_tools(self) -> List[ToolDefinition]:
        """Return all tool definitions registered on this server."""
        return list(self._tools.values())

    def has_tool(self, method: str) -> bool:
        """Check whether a tool name is registered."""
        return method in self._tools

    # ------------------------------------------------------------------
    # Abstract
    # ------------------------------------------------------------------

    @abstractmethod
    def get_server_name(self) -> str:
        """Return the unique name of this server (e.g. 'discord', 'memory')."""
        ...

"""
Base Connector — Abstract base class for all connectors.

Every connector (Discord, future Slack, etc.) inherits from this
and implements the execute() method for unified dispatching.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from typing import Any, Dict, List

from app.mcp.protocol import ToolDefinition

logger = logging.getLogger(__name__)


class BaseConnector(ABC):
    """Abstract base class for service connectors.

    Subclasses must implement:
    - execute(): Dispatch a tool call by action name.
    - get_tool_definitions(): Return all tools this connector exposes.
    """

    @abstractmethod
    async def execute(self, action: str, **params: Any) -> Dict[str, Any]:
        """Execute a named action with the given parameters.

        Args:
            action: The action name (e.g. 'create', 'delete', 'list').
            **params: Action-specific parameters.

        Returns:
            Dict with the action result.

        Raises:
            ValueError: If parameters are invalid.
            PermissionError: If the bot lacks required permissions.
        """
        ...

    @abstractmethod
    def get_tool_definitions(self) -> List[ToolDefinition]:
        """Return tool definitions for all actions this connector supports.

        Returns:
            List of ToolDefinition instances.
        """
        ...

    def get_connector_name(self) -> str:
        """Return the connector's name (defaults to class name)."""
        return self.__class__.__name__

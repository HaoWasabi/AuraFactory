"""Base Connector — Base class for all connectors.

Every connector (Discord, future Slack, etc.) inherits from this.
Provides default execute() dispatcher that routes by action name to methods.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List

from app.mcp.protocol import ToolDefinition

logger = logging.getLogger(__name__)


class BaseConnector:
    """Base class for service connectors.

    Provides a default execute() that dispatches to same-named methods.
    Subclasses can override execute() for custom routing.
    """

    async def execute(self, action: str, **params: Any) -> Dict[str, Any]:
        """Execute a named action by dispatching to the corresponding method.

        Looks for a method matching `action` on the connector instance.

        Args:
            action: The action name (e.g. 'create', 'delete', 'list').
            **params: Action-specific parameters.

        Returns:
            Dict with the action result.

        Raises:
            ValueError: If action method not found.
            PermissionError: If the bot lacks required permissions.
        """
        method = getattr(self, action, None)
        if method is None or not callable(method):
            raise ValueError(
                f"Action '{action}' not found on {self.__class__.__name__}. "
                f"Available: {self._list_actions()}"
            )
        return await method(**params)

    def get_tool_definitions(self) -> List[ToolDefinition]:
        """Return tool definitions for all public actions.

        Default implementation auto-generates from public async methods.
        Subclasses can override for custom definitions.
        """
        import inspect

        tools = []
        for name in dir(self):
            if name.startswith("_"):
                continue
            attr = getattr(self, name)
            if inspect.iscoroutinefunction(attr) and name != "execute":
                doc = attr.__doc__ or f"{name} action"
                first_line = doc.strip().split("\n")[0]
                tools.append(
                    ToolDefinition(
                        name=f"{self.get_connector_name()}.{name}",
                        description=first_line,
                        parameters={},
                    )
                )
        return tools

    def get_connector_name(self) -> str:
        """Return the connector's name (defaults to class name lowercase)."""
        name = self.__class__.__name__
        # Strip 'Connector' suffix for cleaner tool names
        if name.endswith("Connector"):
            name = name[: -len("Connector")]
        return name.lower()

    def _list_actions(self) -> List[str]:
        """List available action names (public async methods)."""
        import inspect
        return [
            name
            for name in dir(self)
            if not name.startswith("_")
            and inspect.iscoroutinefunction(getattr(self, name, None))
            and name != "execute"
        ]

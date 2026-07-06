# app/connectors/base.py
"""
ConnectorBase ABC — interface for all external connectors.
Each connector wraps a set of related API operations (e.g. Discord, GitHub).
"""
from abc import ABC, abstractmethod
from typing import Dict, Any, List, Optional
import logging
logger = logging.getLogger(__name__)


class ConnectorBase(ABC):
    """
    Abstract base for external service connectors.
    A connector wraps tools for a specific external service.
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """Connector identifier (e.g. 'discord', 'github')."""
        ...

    @property
    @abstractmethod
    def tools(self) -> List[Dict[str, Any]]:
        """List of tool definitions this connector provides."""
        ...

    @abstractmethod
    async def execute(self, tool_name: str, parameters: Dict[str, Any], **kwargs) -> Dict[str, Any]:
        """
        Execute a tool by name with given parameters.
        Returns a dict with at least 'status' and 'data' keys.
        """
        ...

    async def health_check(self) -> bool:
        """Check if the connector's external service is reachable."""
        return True

    def get_tool(self, tool_name: str) -> Optional[Dict[str, Any]]:
        """Get a specific tool definition by name."""
        for tool in self.tools:
            if tool["name"] == tool_name:
                return tool
        return None

    def list_tool_names(self) -> List[str]:
        """List all tool names this connector provides."""
        return [t["name"] for t in self.tools]

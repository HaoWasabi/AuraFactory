# app/connectors/discord/connector.py
"""
DiscordConnector — unified access to all Discord API tools.
Dispatches tool execution to the correct sub-module.
"""
import importlib
import logging
from typing import Dict, Any, List

from app.connectors.base import ConnectorBase

logger = logging.getLogger(__name__)


# Map tool prefixes to module names
MODULE_MAP = {
    "discord_channel": "channels",
    "discord_category": "categories",
    "discord_role": "roles",
    "discord_member": "members",
    "discord_permission": "permissions",
    "discord_webhook": "webhooks",
    "discord_backup": "backup",
    "discord_template": "templates",
    "discord_thread": "threads",
    "discord_emoji": "emojis",
    "discord_invite": "invites",
    "discord_guild": "guild",
    "discord_feature": "features",
    "discord_onboarding": "onboarding",
    "discord_automod": "automod",
}


class DiscordConnector(ConnectorBase):
    """Unified Discord connector dispatching to sub-modules."""

    def __init__(self, guild=None):
        self._guild = guild
        self._modules: Dict[str, Any] = {}

    @property
    def name(self) -> str:
        return "discord"

    @property
    def tools(self) -> List[Dict[str, Any]]:
        """Aggregate tool definitions from all sub-modules."""
        all_tools = []
        for module_name in MODULE_MAP.values():
            module = self._load_module(module_name)
            if hasattr(module, "TOOLS"):
                all_tools.extend(module.TOOLS)
        return all_tools

    async def execute(self, tool_name: str, parameters: Dict[str, Any], **kwargs) -> Dict[str, Any]:
        """Dispatch a tool call to the correct module."""
        guild = kwargs.get("guild", self._guild)

        # Find the correct module
        module = self._find_module(tool_name)
        if not module:
            return {
                "status": "error",
                "error": f"Unknown tool: {tool_name}",
            }

        # Find the handler function
        handler = getattr(module, tool_name, None)
        if not handler:
            return {
                "status": "error",
                "error": f"Handler not found: {tool_name} in module",
            }

        try:
            result = await handler(guild=guild, **parameters)
            return {"status": "success", "data": result}
        except Exception as e:
            logger.error(f"Discord tool execution failed: {tool_name} - {e}")
            return {
                "status": "error",
                "error": str(e),
            }

    def _find_module(self, tool_name: str):
        """Find which module handles a given tool name."""
        for prefix, module_name in MODULE_MAP.items():
            if tool_name.startswith(prefix):
                return self._load_module(module_name)
        # Fallback: try all modules
        for module_name in MODULE_MAP.values():
            module = self._load_module(module_name)
            if hasattr(module, tool_name):
                return module
        return None

    def _load_module(self, module_name: str):
        """Lazy-load a sub-module."""
        if module_name not in self._modules:
            try:
                self._modules[module_name] = importlib.import_module(
                    f"app.connectors.discord.{module_name}"
                )
            except ImportError as e:
                logger.warning(f"Could not load discord module '{module_name}': {e}")
                return None
        return self._modules[module_name]

    async def health_check(self) -> bool:
        """Check if Discord connection is alive."""
        return self._guild is not None

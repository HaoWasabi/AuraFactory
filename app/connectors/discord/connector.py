"""
Discord Connector Facade — Aggregates all sub-connectors and provides unified dispatch.

This is the main entry point for all Discord operations.
The DiscordMCPServer uses this to register tools and route requests.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List

import nextcord

from app.connectors.discord.automod import AutomodConnector
from app.connectors.discord.backup import BackupConnector
from app.connectors.discord.categories import CategoriesConnector
from app.connectors.discord.channels import ChannelsConnector
from app.connectors.discord.emojis import EmojisConnector
from app.connectors.discord.features import FeaturesConnector
from app.connectors.discord.guild import GuildConnector
from app.connectors.discord.invites import InvitesConnector
from app.connectors.discord.members import MembersConnector
from app.connectors.discord.onboarding import OnboardingConnector
from app.connectors.discord.permissions import PermissionsConnector
from app.connectors.discord.roles import RolesConnector
from app.connectors.discord.templates import TemplatesConnector
from app.connectors.discord.threads import ThreadsConnector
from app.connectors.discord.webhooks import WebhooksConnector
from app.mcp.protocol import ToolDefinition

logger = logging.getLogger(__name__)


class DiscordConnector:
    """Facade that aggregates all Discord sub-connectors.

    Provides unified tool dispatch and tool definition collection.
    Tool names follow the pattern: discord.{module}.{action}
    """

    def __init__(self, bot: nextcord.Bot) -> None:
        self._bot = bot

        # Initialize all sub-connectors
        self._connectors: Dict[str, Any] = {
            "channels": ChannelsConnector(bot),
            "categories": CategoriesConnector(bot),
            "roles": RolesConnector(bot),
            "permissions": PermissionsConnector(bot),
            "members": MembersConnector(bot),
            "webhooks": WebhooksConnector(bot),
            "emojis": EmojisConnector(bot),
            "invites": InvitesConnector(bot),
            "threads": ThreadsConnector(bot),
            "guild": GuildConnector(bot),
            "onboarding": OnboardingConnector(bot),
            "backup": BackupConnector(bot),
            "automod": AutomodConnector(bot),
            "features": FeaturesConnector(bot),
            "templates": TemplatesConnector(bot),
        }

        logger.info(
            "DiscordConnector initialized with %d sub-connectors",
            len(self._connectors),
        )

    # ------------------------------------------------------------------
    # Unified Dispatch
    # ------------------------------------------------------------------

    async def execute(
        self,
        tool_name: str,
        guild: nextcord.Guild,
        **params: Any,
    ) -> Dict[str, Any]:
        """Execute a tool by its fully-qualified name.

        Parses the tool name (discord.{module}.{action}) and routes
        to the correct sub-connector.

        Args:
            tool_name: Full tool name (e.g. 'discord.channels.create').
            guild: The target guild.
            **params: Parameters to pass to the action.

        Returns:
            Dict result from the sub-connector action.

        Raises:
            ValueError: If tool_name is malformed or module not found.
        """
        parts = tool_name.split(".")
        if len(parts) != 3 or parts[0] != "discord":
            raise ValueError(
                f"Invalid tool name '{tool_name}'. "
                f"Expected format: 'discord.{{module}}.{{action}}'"
            )

        module_name = parts[1]
        action_name = parts[2]

        connector = self._connectors.get(module_name)
        if connector is None:
            raise ValueError(
                f"Unknown module '{module_name}'. "
                f"Available: {list(self._connectors.keys())}"
            )

        return await connector.execute(action=action_name, guild=guild, **params)

    # ------------------------------------------------------------------
    # Tool Discovery
    # ------------------------------------------------------------------

    def get_all_tool_definitions(self) -> List[ToolDefinition]:
        """Collect tool definitions from all sub-connectors.

        Returns:
            Complete list of ToolDefinitions across all modules.
        """
        all_tools: List[ToolDefinition] = []
        for connector in self._connectors.values():
            all_tools.extend(connector.get_tool_definitions())
        return all_tools

    def get_tool_definitions_for_module(self, module: str) -> List[ToolDefinition]:
        """Get tool definitions for a specific module.

        Args:
            module: Module name (e.g. 'channels', 'roles').

        Returns:
            List of ToolDefinitions for that module.
        """
        connector = self._connectors.get(module)
        if connector is None:
            raise ValueError(f"Unknown module '{module}'")
        return connector.get_tool_definitions()

    @property
    def modules(self) -> List[str]:
        """List all available module names."""
        return list(self._connectors.keys())

    @property
    def tool_count(self) -> int:
        """Total number of registered tools across all modules."""
        return sum(
            len(c.get_tool_definitions()) for c in self._connectors.values()
        )

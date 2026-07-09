"""Discord Connector Facade — Unified dispatcher for all sub-connectors.

Routes tool calls: discord.{module}.{action} → SubConnector.execute(action, guild, **kwargs)
This is the single entry point for MCP server and UnifiedAgent.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List

import nextcord

from app.connectors.discord.channels import ChannelsConnector
from app.connectors.discord.categories import CategoriesConnector
from app.connectors.discord.roles import RolesConnector
from app.connectors.discord.members import MembersConnector
from app.connectors.discord.guild import GuildConnector
from app.connectors.discord.webhooks import WebhooksConnector
from app.connectors.discord.threads import ThreadsConnector
from app.connectors.discord.invites import InvitesConnector
from app.connectors.discord.automod import AutomodConnector
from app.connectors.discord.backup import BackupConnector
from app.connectors.discord.features import FeaturesConnector
from app.connectors.discord.audit import AuditConnector
from app.connectors.discord.safety import SafetyConnector
from app.connectors.discord.templates import TemplatesConnector

logger = logging.getLogger(__name__)


class DiscordConnector:
    """Facade that dispatches discord.{module}.{action} calls.

    Usage:
        connector = DiscordConnector(bot)
        result = await connector.execute("discord.channels.create", guild, name="test", type="text")
    """

    def __init__(self, bot: nextcord.Bot) -> None:
        self._bot = bot
        self._connectors: Dict[str, Any] = {
            "channels": ChannelsConnector(bot),
            "categories": CategoriesConnector(bot),
            "roles": RolesConnector(bot),
            "members": MembersConnector(bot),
            "guild": GuildConnector(bot),
            "webhooks": WebhooksConnector(bot),
            "threads": ThreadsConnector(bot),
            "invites": InvitesConnector(bot),
            "automod": AutomodConnector(bot),
            "backup": BackupConnector(bot),
            "features": FeaturesConnector(bot),
            "audit": AuditConnector(bot),
            "safety": SafetyConnector(bot),
            "templates": TemplatesConnector(bot),
        }
        logger.info("DiscordConnector initialized: %d modules", len(self._connectors))

    async def execute(self, tool_name: str, guild: nextcord.Guild, **kwargs) -> Dict[str, Any]:
        """Route tool_name to correct sub-connector.

        Args:
            tool_name: Full name like 'discord.channels.create'
            guild: Target guild instance
            **kwargs: All params — spread directly into action method

        Returns:
            Action result dict.

        Raises:
            ValueError: If tool_name format is invalid or module not found.
        """
        parts = tool_name.split(".")
        if len(parts) != 3 or parts[0] != "discord":
            raise ValueError(
                f"Invalid tool name '{tool_name}'. Expected: 'discord.{{module}}.{{action}}'"
            )

        module_name = parts[1]
        action_name = parts[2]

        connector = self._connectors.get(module_name)
        if connector is None:
            raise ValueError(
                f"Unknown module '{module_name}'. Available: {list(self._connectors.keys())}"
            )

        return await connector.execute(action=action_name, guild=guild, **kwargs)

    @property
    def modules(self) -> List[str]:
        """All available module names."""
        return list(self._connectors.keys())

    @property
    def module_count(self) -> int:
        return len(self._connectors)

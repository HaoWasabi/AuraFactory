"""Discord Integrations Connector — SPEC v2 new module (schema §4).

Lists and removes bots/apps/webhooks connected to the server.

Actions: list, remove
"""

from __future__ import annotations

import logging
from typing import Any, Dict

import nextcord

from app.connectors.base import BaseConnector
from app.connectors.discord._permissions import check_bot_permissions

logger = logging.getLogger(__name__)


class IntegrationsConnector(BaseConnector):
    """Manages Discord guild integrations (bots/apps)."""

    def __init__(self, bot: nextcord.Bot) -> None:
        self._bot = bot

    async def list(self, guild: nextcord.Guild, **kwargs) -> Dict[str, Any]:
        """List all integrations (bots/apps) in the server."""
        perm_error = check_bot_permissions(guild, "discord.integrations.list")
        if perm_error:
            raise PermissionError(perm_error)

        try:
            integrations = await guild.integrations()
            result = []
            for integ in integrations:
                result.append({
                    "id": str(integ.id),
                    "name": integ.name,
                    "type": integ.type,
                    "enabled": integ.enabled,
                    "account": str(getattr(integ, "account", None)),
                })
            return {"integrations": result, "count": len(result)}
        except nextcord.errors.Forbidden:
            raise PermissionError("Bot lacks 'Manage Guild' permission.")
        except nextcord.errors.HTTPException as exc:
            raise RuntimeError(f"Failed to list integrations: {exc}")

    async def remove(self, guild: nextcord.Guild, integration_id: int, **kwargs) -> Dict[str, Any]:
        """Remove an integration from the server.

        Safety: Cannot remove the bot itself.
        """
        perm_error = check_bot_permissions(guild, "discord.integrations.remove")
        if perm_error:
            raise PermissionError(perm_error)

        # Safety check — cannot self-remove
        if int(integration_id) == self._bot.user.id:
            raise ValueError("Cannot remove the bot's own integration.")

        try:
            integrations = await guild.integrations()
            target = None
            for integ in integrations:
                if integ.id == int(integration_id):
                    target = integ
                    break

            if target is None:
                raise ValueError(f"Integration '{integration_id}' not found.")

            await target.delete()
            logger.info("Removed integration '%s' (id=%s) from guild '%s'", target.name, integration_id, guild.name)
            return {"id": str(integration_id), "name": target.name, "removed": True}
        except nextcord.errors.Forbidden:
            raise PermissionError("Bot lacks 'Manage Guild' permission.")
        except nextcord.errors.HTTPException as exc:
            raise RuntimeError(f"Failed to remove integration: {exc}")

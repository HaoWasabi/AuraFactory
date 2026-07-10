"""Discord Onboarding Connector — kwargs pattern. Actions: get, setup"""
from __future__ import annotations

import logging
from typing import Any, Dict, List

import nextcord

from app.connectors.base import BaseConnector

logger = logging.getLogger(__name__)


class OnboardingConnector(BaseConnector):
    def __init__(self, bot: nextcord.Bot) -> None:
        self._bot = bot

    async def execute(self, action: str, guild: nextcord.Guild, **kwargs) -> Dict[str, Any]:
        actions = {"get": self.get, "setup": self.setup}
        handler = actions.get(action)
        if handler is None:
            raise ValueError(f"Unknown action '{action}'")
        return await handler(guild, **kwargs)

    async def get(self, guild: nextcord.Guild, **kwargs) -> Dict[str, Any]:
        """Fetch the guild onboarding configuration via REST API.

        Returns:
            Raw onboarding data dict from Discord API.

        Raises:
            PermissionError: If bot lacks permission.
            RuntimeError: If API request fails.
        """
        try:
            route = nextcord.http.Route(
                "GET", "/guilds/{guild_id}/onboarding", guild_id=guild.id
            )
            data = await self._bot.http.request(route)
            return data
        except nextcord.Forbidden as e:
            raise PermissionError(f"Missing permission to get onboarding: {e}") from e
        except nextcord.HTTPException as e:
            raise RuntimeError(f"Failed to get onboarding config: {e}") from e

    async def setup(self, guild: nextcord.Guild, **kwargs) -> Dict[str, Any]:
        """Configure guild onboarding via REST API.

        Expected kwargs:
            prompts: List[dict] — each prompt has {type, title, options: [{channel_ids, role_ids, title, description}]}
            default_channel_ids: List[int]
            enabled: bool

        Returns:
            {success: True, enabled: bool}

        Raises:
            ValueError: If required kwargs are missing or invalid.
            PermissionError: If bot lacks permission.
            RuntimeError: If API request fails.
        """
        prompts: List[dict] | None = kwargs.get("prompts")
        default_channel_ids: List[int] | None = kwargs.get("default_channel_ids")
        enabled: bool | None = kwargs.get("enabled")

        if prompts is None:
            raise ValueError("'prompts' is required for onboarding setup")
        if default_channel_ids is None:
            raise ValueError("'default_channel_ids' is required for onboarding setup")
        if enabled is None:
            raise ValueError("'enabled' is required for onboarding setup")

        payload: Dict[str, Any] = {
            "prompts": prompts,
            "default_channel_ids": default_channel_ids,
            "enabled": enabled,
        }

        try:
            route = nextcord.http.Route(
                "PUT", "/guilds/{guild_id}/onboarding", guild_id=guild.id
            )
            await self._bot.http.request(route, json=payload)
            return {"success": True, "enabled": enabled}
        except nextcord.Forbidden as e:
            raise PermissionError(f"Missing permission to setup onboarding: {e}") from e
        except nextcord.HTTPException as e:
            raise RuntimeError(f"Failed to setup onboarding: {e}") from e

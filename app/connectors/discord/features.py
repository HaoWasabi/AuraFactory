"""
Discord Features Connector — Guild feature toggles.

Actions: enable, disable, list
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List

import nextcord

from app.connectors.base import BaseConnector
from app.mcp.protocol import ToolDefinition

logger = logging.getLogger(__name__)

# Known guild features that can be toggled (community features)
KNOWN_FEATURES = {
    "COMMUNITY": "Community server features",
    "WELCOME_SCREEN_ENABLED": "Welcome screen for new members",
    "NEWS": "Announcement channels",
    "DISCOVERABLE": "Server discovery listing",
    "INVITES_DISABLED": "Disable invite links",
    "RAID_ALERTS_DISABLED": "Disable raid alerts",
}


class FeaturesConnector(BaseConnector):
    """Manages Discord guild feature toggles."""

    def __init__(self, bot: nextcord.Bot) -> None:
        self._bot = bot

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------

    async def enable(
        self,
        guild: nextcord.Guild,
        feature_name: str,
    ) -> Dict[str, Any]:
        """Enable a guild feature.

        Note: Not all features can be toggled via the API. Some require
        Discord partnership or specific prerequisites.

        Args:
            guild: The target guild.
            feature_name: The feature to enable (e.g. 'COMMUNITY').

        Returns:
            Dict confirming the action.
        """
        if not feature_name or not feature_name.strip():
            raise ValueError("Feature name cannot be empty")

        feature_name = feature_name.upper()

        try:
            # For COMMUNITY feature, special handling is needed:
            # Discord requires rules_channel_id, public_updates_channel_id,
            # explicit_content_filter >= 1, and verification_level >= 1.
            # nextcord's Guild.edit() does not accept 'features', so use raw HTTP.
            if feature_name == "COMMUNITY":
                current_features = list(guild.features)
                if "COMMUNITY" not in current_features:
                    current_features.append("COMMUNITY")
                rules_ch = guild.rules_channel or (guild.text_channels[0] if guild.text_channels else None)
                updates_ch = guild.public_updates_channel or rules_ch
                if rules_ch is None:
                    raise ValueError("No text channels available to assign as rules channel for Community.")
                await guild._state.http.edit_guild(
                    guild.id,
                    reason=None,
                    features=current_features,
                    rules_channel_id=str(rules_ch.id),
                    public_updates_channel_id=str(updates_ch.id),
                    explicit_content_filter=max(guild.explicit_content_filter.value, 2),
                    verification_level=max(guild.verification_level.value, 1),
                )
            else:
                # Generic feature toggle via raw HTTP
                current_features = list(guild.features)
                if feature_name not in current_features:
                    current_features.append(feature_name)
                await guild._state.http.edit_guild(
                    guild.id, reason=None, features=current_features
                )

            logger.info("Enabled feature '%s' in guild '%s'", feature_name, guild.name)
            return {
                "feature": feature_name,
                "enabled": True,
                "guild_id": str(guild.id),
            }
        except nextcord.errors.Forbidden:
            raise PermissionError("manage_guild")
        except nextcord.errors.HTTPException as exc:
            raise RuntimeError(f"Failed to enable feature '{feature_name}': {exc}")

    async def disable(
        self,
        guild: nextcord.Guild,
        feature_name: str,
    ) -> Dict[str, Any]:
        """Disable a guild feature.

        Args:
            guild: The target guild.
            feature_name: The feature to disable.

        Returns:
            Dict confirming the action.
        """
        if not feature_name or not feature_name.strip():
            raise ValueError("Feature name cannot be empty")

        feature_name = feature_name.upper()

        try:
            if feature_name == "COMMUNITY":
                current_features = list(guild.features)
                if "COMMUNITY" in current_features:
                    current_features.remove("COMMUNITY")
                await guild._state.http.edit_guild(
                    guild.id, reason=None, features=current_features
                )
            else:
                current_features = list(guild.features)
                if feature_name in current_features:
                    current_features.remove(feature_name)
                await guild._state.http.edit_guild(
                    guild.id, reason=None, features=current_features
                )

            logger.info("Disabled feature '%s' in guild '%s'", feature_name, guild.name)
            return {
                "feature": feature_name,
                "disabled": True,
                "guild_id": str(guild.id),
            }
        except nextcord.errors.Forbidden:
            raise PermissionError("manage_guild")
        except nextcord.errors.HTTPException as exc:
            raise RuntimeError(f"Failed to disable feature '{feature_name}': {exc}")

    async def list(
        self,
        guild: nextcord.Guild,
    ) -> Dict[str, Any]:
        """List all enabled features for the guild.

        Args:
            guild: The target guild.

        Returns:
            Dict with feature list.
        """
        features = []
        for feature in guild.features:
            features.append({
                "name": feature,
                "description": KNOWN_FEATURES.get(feature, "Unknown feature"),
            })
        return {
            "features": features,
            "count": len(features),
            "guild_id": str(guild.id),
        }

    # ------------------------------------------------------------------
    # BaseConnector interface
    # ------------------------------------------------------------------

    async def execute(self, action: str, **params: Any) -> Dict[str, Any]:
        """Dispatch to the appropriate action method."""
        actions = {
            "enable": self.enable,
            "disable": self.disable,
            "list": self.list,
        }
        handler = actions.get(action)
        if handler is None:
            raise ValueError(
                f"Unknown action '{action}' for FeaturesConnector. "
                f"Available: {list(actions.keys())}"
            )
        return await handler(**params)

    def get_tool_definitions(self) -> List[ToolDefinition]:
        """Return tool definitions for feature operations."""
        return [
            ToolDefinition(
                name="discord.features.enable",
                description="Enable a guild feature (e.g. COMMUNITY, WELCOME_SCREEN_ENABLED).",
                parameters={
                    "type": "object",
                    "properties": {
                        "guild_id": {"type": "string", "description": "Target guild ID."},
                        "feature_name": {"type": "string", "description": "Feature name to enable."},
                    },
                    "required": ["guild_id", "feature_name"],
                },
                risk_level="high",
            ),
            ToolDefinition(
                name="discord.features.disable",
                description="Disable a guild feature.",
                parameters={
                    "type": "object",
                    "properties": {
                        "guild_id": {"type": "string", "description": "Target guild ID."},
                        "feature_name": {"type": "string", "description": "Feature name to disable."},
                    },
                    "required": ["guild_id", "feature_name"],
                },
                risk_level="high",
            ),
            ToolDefinition(
                name="discord.features.list",
                description="List all enabled features for the guild.",
                parameters={
                    "type": "object",
                    "properties": {
                        "guild_id": {"type": "string", "description": "Target guild ID."},
                    },
                    "required": ["guild_id"],
                },
                risk_level="low",
            ),
        ]

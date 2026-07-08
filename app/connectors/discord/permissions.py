"""
Discord Permissions Connector — Channel and role permission overrides.

Actions: set_channel_perms, set_role_perms, sync
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List

import nextcord

from app.connectors.base import BaseConnector
from app.mcp.protocol import ToolDefinition

logger = logging.getLogger(__name__)


class PermissionsConnector(BaseConnector):
    """Manages Discord permission overrides."""

    def __init__(self, bot: nextcord.Bot) -> None:
        self._bot = bot

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------

    async def set_channel_perms(
        self,
        guild: nextcord.Guild,
        channel_id: int,
        target_id: int,
        target_type: str = "role",
        **perms: Any,
    ) -> Dict[str, Any]:
        """Set permission overrides for a channel.

        Args:
            guild: The target guild.
            channel_id: Channel to modify.
            target_id: Role or member ID to set overrides for.
            target_type: 'role' or 'member'.
            **perms: Permission overrides (permission_name=True/False/None).

        Returns:
            Dict confirming the update.
        """
        channel = guild.get_channel(int(channel_id))
        if channel is None:
            raise ValueError(f"Channel '{channel_id}' not found in guild")

        if target_type == "role":
            target = guild.get_role(int(target_id))
            if target is None:
                raise ValueError(f"Role '{target_id}' not found in guild")
        elif target_type == "member":
            target = guild.get_member(int(target_id))
            if target is None:
                raise ValueError(f"Member '{target_id}' not found in guild")
        else:
            raise ValueError(f"target_type must be 'role' or 'member', got '{target_type}'")

        if not perms:
            raise ValueError("No permission overrides provided")

        # Validate permission names early — wrong names cause nextcord TypeError
        _VALID_PERMS = {
            "view_channel", "send_messages", "send_messages_in_threads",
            "create_public_threads", "create_private_threads", "embed_links",
            "attach_files", "add_reactions", "use_external_emojis",
            "use_external_stickers", "mention_everyone", "manage_messages",
            "manage_threads", "read_message_history", "send_tts_messages",
            "use_application_commands", "connect", "speak", "mute_members",
            "deafen_members", "move_members", "use_voice_activation",
            "priority_speaker", "manage_channels", "manage_roles",
            "manage_webhooks", "kick_members", "ban_members", "administrator",
            "manage_guild", "view_audit_log", "view_guild_insights",
        }
        bad = [k for k in perms if k not in _VALID_PERMS]
        if bad:
            raise ValueError(
                f"Invalid permission name(s): {bad}. "
                f"Use exact nextcord names e.g. 'view_channel', 'send_messages'."
            )

        try:
            overwrite = nextcord.PermissionOverwrite(**perms)
            await channel.set_permissions(target, overwrite=overwrite)
            logger.info(
                "Set channel perms on '%s' for %s '%s': %s",
                channel.name,
                target_type,
                target_id,
                list(perms.keys()),
            )
            return {
                "channel_id": str(channel_id),
                "target_id": str(target_id),
                "target_type": target_type,
                "permissions_set": perms,
            }
        except nextcord.errors.Forbidden:
            raise PermissionError("manage_permissions")
        except nextcord.errors.HTTPException as exc:
            raise RuntimeError(f"Failed to set channel permissions: {exc}")

    async def set_role_perms(
        self,
        guild: nextcord.Guild,
        role_id: int,
        **perms: Any,
    ) -> Dict[str, Any]:
        """Set base permissions for a role.

        Args:
            guild: The target guild.
            role_id: Role to modify.
            **perms: Permission values (permission_name=True/False).

        Returns:
            Dict confirming the update.
        """
        role = guild.get_role(int(role_id))
        if role is None:
            raise ValueError(f"Role '{role_id}' not found in guild")

        if not perms:
            raise ValueError("No permissions provided")

        # Validate permission names early — wrong names cause nextcord TypeError
        _VALID_PERMS = {
            "view_channel", "send_messages", "send_messages_in_threads",
            "create_public_threads", "create_private_threads", "embed_links",
            "attach_files", "add_reactions", "use_external_emojis",
            "use_external_stickers", "mention_everyone", "manage_messages",
            "manage_threads", "read_message_history", "send_tts_messages",
            "use_application_commands", "connect", "speak", "mute_members",
            "deafen_members", "move_members", "use_voice_activation",
            "priority_speaker", "manage_channels", "manage_roles",
            "manage_webhooks", "kick_members", "ban_members", "administrator",
            "manage_guild", "view_audit_log", "view_guild_insights",
        }
        bad = [k for k in perms if k not in _VALID_PERMS]
        if bad:
            raise ValueError(
                f"Invalid permission name(s): {bad}. "
                f"Use exact nextcord names e.g. 'view_channel', 'send_messages'."
            )

        try:
            new_perms = nextcord.Permissions(**perms)
            await role.edit(permissions=new_perms)
            logger.info(
                "Set role perms for '%s' (id=%s): %s",
                role.name,
                role_id,
                list(perms.keys()),
            )
            return {
                "role_id": str(role_id),
                "role_name": role.name,
                "permissions_set": perms,
            }
        except nextcord.errors.Forbidden:
            raise PermissionError("manage_roles")
        except nextcord.errors.HTTPException as exc:
            raise RuntimeError(f"Failed to set role permissions: {exc}")

    async def sync(
        self,
        guild: nextcord.Guild,
        channel_id: int,
        category_id: int,
    ) -> Dict[str, Any]:
        """Sync a channel's permissions with its parent category.

        Args:
            guild: The target guild.
            channel_id: Channel to sync.
            category_id: Category to sync from.

        Returns:
            Dict confirming the sync.
        """
        channel = guild.get_channel(int(channel_id))
        if channel is None:
            raise ValueError(f"Channel '{channel_id}' not found in guild")

        category = guild.get_channel(int(category_id))
        if category is None or not isinstance(category, nextcord.CategoryChannel):
            raise ValueError(f"Category '{category_id}' not found in guild")

        try:
            # Move channel under category with sync_permissions=True
            await channel.edit(category=category, sync_permissions=True)
            logger.info(
                "Synced permissions for channel '%s' with category '%s'",
                channel.name,
                category.name,
            )
            return {
                "channel_id": str(channel_id),
                "category_id": str(category_id),
                "synced": True,
            }
        except nextcord.errors.Forbidden:
            raise PermissionError("manage_channels")
        except nextcord.errors.HTTPException as exc:
            raise RuntimeError(f"Failed to sync permissions: {exc}")

    # ------------------------------------------------------------------
    # BaseConnector interface
    # ------------------------------------------------------------------

    async def execute(self, action: str, **params: Any) -> Dict[str, Any]:
        """Dispatch to the appropriate action method."""
        actions = {
            "set_channel_perms": self.set_channel_perms,
            "set_role_perms": self.set_role_perms,
            "sync": self.sync,
        }
        handler = actions.get(action)
        if handler is None:
            raise ValueError(
                f"Unknown action '{action}' for PermissionsConnector. "
                f"Available: {list(actions.keys())}"
            )
        return await handler(**params)

    def get_tool_definitions(self) -> List[ToolDefinition]:
        """Return tool definitions for permission operations."""
        _PERM_NAMES_DESC = (
            "Permission names (all boolean): "
            "view_channel, send_messages, send_messages_in_threads, create_public_threads, "
            "create_private_threads, embed_links, attach_files, add_reactions, "
            "use_external_emojis, use_external_stickers, mention_everyone, "
            "manage_messages, manage_threads, read_message_history, send_tts_messages, "
            "use_application_commands, connect, speak, mute_members, deafen_members, "
            "move_members, use_voice_activation, priority_speaker, "
            "manage_channels, manage_roles, manage_webhooks. "
            "Use EXACT names — wrong names cause a runtime TypeError."
        )
        return [
            ToolDefinition(
                name="discord.permissions.set_channel_perms",
                description=(
                    "Set permission overrides for a specific role or member on a channel. "
                    "Pass permission names as extra boolean fields alongside the required params. "
                    "Example: view_channel=false, send_messages=false. " + _PERM_NAMES_DESC
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "guild_id": {"type": "string", "description": "Target guild ID."},
                        "channel_id": {"type": "string", "description": "Channel ID."},
                        "target_id": {"type": "string", "description": "Role or member ID."},
                        "target_type": {
                            "type": "string",
                            "enum": ["role", "member"],
                            "description": "Whether target_id is a role or member.",
                        },
                        "view_channel": {"type": "boolean"},
                        "send_messages": {"type": "boolean"},
                        "read_message_history": {"type": "boolean"},
                        "manage_messages": {"type": "boolean"},
                        "manage_channels": {"type": "boolean"},
                        "connect": {"type": "boolean"},
                        "speak": {"type": "boolean"},
                        "mute_members": {"type": "boolean"},
                        "move_members": {"type": "boolean"},
                        "use_application_commands": {"type": "boolean"},
                        "mention_everyone": {"type": "boolean"},
                        "embed_links": {"type": "boolean"},
                        "attach_files": {"type": "boolean"},
                        "add_reactions": {"type": "boolean"},
                    },
                    "required": ["guild_id", "channel_id", "target_id", "target_type"],
                    "additionalProperties": True,
                },
                risk_level="high",
            ),
            ToolDefinition(
                name="discord.permissions.set_role_perms",
                description=(
                    "Set base permissions for a role (applies server-wide). "
                    "Pass permission names as extra boolean fields. " + _PERM_NAMES_DESC
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "guild_id": {"type": "string", "description": "Target guild ID."},
                        "role_id": {"type": "string", "description": "Role ID."},
                        "view_channel": {"type": "boolean"},
                        "send_messages": {"type": "boolean"},
                        "read_message_history": {"type": "boolean"},
                        "manage_messages": {"type": "boolean"},
                        "manage_channels": {"type": "boolean"},
                        "manage_roles": {"type": "boolean"},
                        "kick_members": {"type": "boolean"},
                        "ban_members": {"type": "boolean"},
                        "administrator": {"type": "boolean"},
                        "connect": {"type": "boolean"},
                        "speak": {"type": "boolean"},
                        "mention_everyone": {"type": "boolean"},
                        "use_application_commands": {"type": "boolean"},
                    },
                    "required": ["guild_id", "role_id"],
                    "additionalProperties": True,
                },
                risk_level="high",
            ),
            ToolDefinition(
                name="discord.permissions.sync",
                description=(
                    "Sync a channel's permission overrides with its parent category. "
                    "Use this after moving a channel to a new category to inherit the "
                    "category's permission overrides."
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "guild_id": {"type": "string", "description": "Target guild ID."},
                        "channel_id": {"type": "string", "description": "Channel ID to sync."},
                        "category_id": {"type": "string", "description": "Category ID to sync from."},
                    },
                    "required": ["guild_id", "channel_id", "category_id"],
                },
                risk_level="medium",
            ),
        ]

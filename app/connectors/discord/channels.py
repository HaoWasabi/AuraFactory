"""
Discord Channels Connector — Advanced Channel CRUD operations.

Supported channel types: text, voice, stage, forum, news/announcement
Supports fine-grained permission overwrites (private channels, role/user access,
advanced permission flags), slowmode, NSFW, user limits, bitrate, and more.

Actions: create, delete, rename, move, edit, list
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

import nextcord

from app.connectors.base import BaseConnector
from app.mcp.protocol import ToolDefinition

logger = logging.getLogger(__name__)


class ChannelsConnector(BaseConnector):
    """Manages Discord guild channels with full type and permission support."""

    def __init__(self, bot: nextcord.Bot) -> None:
        self._bot = bot

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _build_overwrites(
        guild: nextcord.Guild,
        is_private: bool = False,
        allowed_role_ids: Optional[List[int]] = None,
        allowed_user_ids: Optional[List[int]] = None,
        advanced_permissions: Optional[Dict[str, bool]] = None,
    ) -> Optional[Dict[Any, nextcord.PermissionOverwrite]]:
        """Build a permission overwrite map.

        Logic:
        - If is_private=True: hide from @everyone, grant view to listed roles/users.
        - If advanced_permissions provided: apply custom flags on top of view_channel.
        - If neither is set: return None (inherit from category / guild default).

        Args:
            guild: Target guild.
            is_private: Whether the channel should be hidden from @everyone.
            allowed_role_ids: Role IDs that may access a private channel.
            allowed_user_ids: User IDs that may access a private channel.
            advanced_permissions: Dict of PermissionOverwrite flag -> bool,
                e.g. {"send_messages": False, "attach_files": True}.

        Returns:
            Overwrite dict or None if no permission customisation needed.
        """
        allowed_role_ids = allowed_role_ids or []
        allowed_user_ids = allowed_user_ids or []

        if not is_private and not advanced_permissions:
            return None

        overwrites: Dict[Any, nextcord.PermissionOverwrite] = {}

        # Build the custom overwrite object from advanced_permissions flags
        custom_overwrite = nextcord.PermissionOverwrite()
        if advanced_permissions:
            for perm, val in advanced_permissions.items():
                if hasattr(custom_overwrite, perm):
                    setattr(custom_overwrite, perm, val)

        if is_private:
            # Hide from everyone by default
            overwrites[guild.default_role] = nextcord.PermissionOverwrite(view_channel=False)
            # Grant access to allowed roles
            for r_id in allowed_role_ids:
                role = guild.get_role(int(r_id))
                if role:
                    if advanced_permissions:
                        setattr(custom_overwrite, "view_channel", True)
                        overwrites[role] = custom_overwrite
                    else:
                        overwrites[role] = nextcord.PermissionOverwrite(view_channel=True)
            # Grant access to allowed users
            for u_id in allowed_user_ids:
                member = guild.get_member(int(u_id))
                if member:
                    if advanced_permissions:
                        setattr(custom_overwrite, "view_channel", True)
                        overwrites[member] = custom_overwrite
                    else:
                        overwrites[member] = nextcord.PermissionOverwrite(view_channel=True)
        else:
            # Public channel with custom flags applied to @everyone
            overwrites[guild.default_role] = custom_overwrite

        # Always ensure the bot itself retains management access
        overwrites[guild.me] = nextcord.PermissionOverwrite(
            view_channel=True, manage_channels=True
        )
        return overwrites

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------

    async def create(
        self,
        guild: nextcord.Guild,
        name: str,
        type: str = "text",
        category_id: Optional[int] = None,
        topic: Optional[str] = None,
        # Voice / Stage specific
        bitrate: Optional[int] = None,
        user_limit: Optional[int] = None,
        # Text / Forum specific
        slowmode_delay: Optional[int] = None,
        nsfw: Optional[bool] = None,
        # Permission helpers
        is_private: bool = False,
        allowed_role_ids: Optional[List[int]] = None,
        allowed_user_ids: Optional[List[int]] = None,
        advanced_permissions: Optional[Dict[str, bool]] = None,
        sync_permissions: bool = False,
        position: Optional[int] = None,
    ) -> Dict[str, Any]:
        """Create a new channel in the guild.

        Supports: text, voice, stage, forum, news (announcement).

        Args:
            guild: Target guild.
            name: Channel name.
            type: One of 'text', 'voice', 'stage', 'forum', 'news'/'announcement'.
            category_id: Parent category ID (optional).
            topic: Channel topic / description (text, forum, stage).
            bitrate: Audio bitrate in bps for voice/stage channels (e.g. 64000).
            user_limit: Max users for voice channels (0 = unlimited).
            slowmode_delay: Seconds between messages for text/forum (0–21600).
            nsfw: Mark channel as age-restricted.
            is_private: If True, hide from @everyone and restrict to allowed_role/user_ids.
            allowed_role_ids: Role IDs to grant access when is_private=True.
            allowed_user_ids: Member IDs to grant access when is_private=True.
            advanced_permissions: Custom permission flags dict, e.g.
                {"send_messages": False, "attach_files": True}.
            sync_permissions: Sync permissions with parent category after creation.
            position: Channel position in the sidebar.

        Returns:
            Dict with created channel info.
        """
        if not name or not name.strip():
            raise ValueError("Channel name cannot be empty")

        # Resolve parent category
        category: Optional[nextcord.CategoryChannel] = None
        if category_id is not None:
            raw = guild.get_channel(int(category_id))
            if raw is None or not isinstance(raw, nextcord.CategoryChannel):
                raise ValueError(f"Category '{category_id}' not found or is not a category")
            category = raw

        c_type = type.lower().strip()

        # Build permission overwrites
        overwrites = self._build_overwrites(
            guild,
            is_private=is_private,
            allowed_role_ids=allowed_role_ids,
            allowed_user_ids=allowed_user_ids,
            advanced_permissions=advanced_permissions,
        )

        # Shared kwargs that apply to most channel types
        shared: Dict[str, Any] = {}
        if category:
            shared["category"] = category
        if overwrites:
            shared["overwrites"] = overwrites
        if position is not None:
            shared["position"] = int(position)

        try:
            channel: nextcord.abc.GuildChannel

            if c_type == "text":
                if topic:
                    shared["topic"] = topic
                if nsfw is not None:
                    shared["nsfw"] = nsfw
                if slowmode_delay is not None:
                    shared["slowmode_delay"] = int(slowmode_delay)
                channel = await guild.create_text_channel(name=name, **shared)

            elif c_type == "voice":
                if bitrate is not None:
                    shared["bitrate"] = int(bitrate)
                if user_limit is not None:
                    shared["user_limit"] = int(user_limit)
                channel = await guild.create_voice_channel(name=name, **shared)

            elif c_type == "stage":
                if "COMMUNITY" not in guild.features:
                    from app.connectors.discord.exceptions import CommunityRequiredError
                    raise CommunityRequiredError(
                        feature_needed="COMMUNITY",
                        blocked_action="create_stage_channel",
                        channel_name=name,
                    )
                if bitrate is not None:
                    shared["bitrate"] = int(bitrate)
                if user_limit is not None:
                    shared["user_limit"] = int(user_limit)
                channel = await guild.create_stage_channel(name=name, **shared)
                # Optionally open a stage instance
                try:
                    await channel.create_instance(topic=topic or "Welcome!")
                except Exception:
                    pass  # Non-fatal — bot may lack Stage Moderator perms

            elif c_type == "forum":
                if slowmode_delay is not None:
                    shared["slowmode_delay"] = int(slowmode_delay)
                if nsfw is not None:
                    shared["nsfw"] = nsfw
                if topic:
                    shared["topic"] = topic
                channel = await guild.create_forum_channel(name=name, **shared)

            elif c_type in ("news", "announcement"):
                if "COMMUNITY" not in guild.features:
                    raise ValueError(
                        "Announcement channels require the server's 'Community' feature to be enabled."
                    )
                if topic:
                    shared["topic"] = topic
                if nsfw is not None:
                    shared["nsfw"] = nsfw
                channel = await guild.create_news_channel(name=name, **shared)

            else:
                raise ValueError(
                    f"Unsupported channel type '{type}'. "
                    f"Valid types: text, voice, stage, forum, news, announcement."
                )

            # Sync permissions with category if requested and no custom overwrites
            if sync_permissions and category and not overwrites:
                await channel.edit(sync_permissions=True)

            logger.info(
                "Created %s channel '%s' (id=%s) in guild '%s'",
                c_type, channel.name, channel.id, guild.name,
            )
            return {
                "id": str(channel.id),
                "name": channel.name,
                "type": c_type,
                "category_id": str(channel.category_id) if channel.category_id else None,
                "is_private": is_private,
            }

        except nextcord.errors.Forbidden:
            raise PermissionError("manage_channels")
        except nextcord.errors.HTTPException as exc:
            raise RuntimeError(f"Failed to create channel: {exc}")

    async def delete(
        self,
        guild: nextcord.Guild,
        channel_id: int,
        reason: str = "AI Agent Request",
    ) -> Dict[str, Any]:
        """Delete a channel by ID.

        Args:
            guild: Target guild.
            channel_id: ID of the channel to delete.
            reason: Audit log reason.

        Returns:
            Dict confirming deletion.
        """
        channel = guild.get_channel(int(channel_id))
        if channel is None:
            raise ValueError(f"Channel '{channel_id}' not found in guild")

        try:
            name = channel.name
            await channel.delete(reason=reason)
            logger.info("Deleted channel '%s' (id=%s) from guild '%s'", name, channel_id, guild.name)
            return {"deleted": True, "channel_id": str(channel_id), "name": name}
        except nextcord.errors.Forbidden:
            raise PermissionError("manage_channels")
        except nextcord.errors.HTTPException as exc:
            raise RuntimeError(f"Failed to delete channel: {exc}")

    async def rename(
        self,
        guild: nextcord.Guild,
        channel_id: int,
        new_name: str,
    ) -> Dict[str, Any]:
        """Rename a channel.

        Args:
            guild: Target guild.
            channel_id: ID of the channel to rename.
            new_name: The new channel name.

        Returns:
            Dict with old and new names.
        """
        if not new_name or not new_name.strip():
            raise ValueError("New channel name cannot be empty")

        channel = guild.get_channel(int(channel_id))
        if channel is None:
            raise ValueError(f"Channel '{channel_id}' not found in guild")

        try:
            old_name = channel.name
            await channel.edit(name=new_name)
            logger.info("Renamed channel '%s' -> '%s' (id=%s)", old_name, new_name, channel_id)
            return {
                "channel_id": str(channel_id),
                "old_name": old_name,
                "new_name": new_name,
            }
        except nextcord.errors.Forbidden:
            raise PermissionError("manage_channels")
        except nextcord.errors.HTTPException as exc:
            raise RuntimeError(f"Failed to rename channel: {exc}")

    async def move(
        self,
        guild: nextcord.Guild,
        channel_id: int,
        category_id: int,
        position: Optional[int] = None,
        sync_permissions: bool = False,
    ) -> Dict[str, Any]:
        """Move a channel to a different category.

        Args:
            guild: Target guild.
            channel_id: ID of the channel to move.
            category_id: Destination category ID.
            position: Optional position within the category.
            sync_permissions: Sync permissions with the new category.

        Returns:
            Dict confirming the move.
        """
        channel = guild.get_channel(int(channel_id))
        if channel is None:
            raise ValueError(f"Channel '{channel_id}' not found in guild")

        category = guild.get_channel(int(category_id))
        if category is None or not isinstance(category, nextcord.CategoryChannel):
            raise ValueError(f"Category '{category_id}' not found")

        try:
            kwargs: Dict[str, Any] = {"category": category}
            if position is not None:
                kwargs["position"] = int(position)
            if sync_permissions:
                kwargs["sync_permissions"] = True
            await channel.edit(**kwargs)
            logger.info("Moved channel '%s' to category '%s'", channel.name, category.name)
            return {
                "channel_id": str(channel_id),
                "new_category_id": str(category_id),
                "position": position,
                "synced_permissions": sync_permissions,
            }
        except nextcord.errors.Forbidden:
            raise PermissionError("manage_channels")
        except nextcord.errors.HTTPException as exc:
            raise RuntimeError(f"Failed to move channel: {exc}")

    async def edit(
        self,
        guild: nextcord.Guild,
        channel_id: int,
        name: Optional[str] = None,
        topic: Optional[str] = None,
        nsfw: Optional[bool] = None,
        slowmode_delay: Optional[int] = None,
        bitrate: Optional[int] = None,
        user_limit: Optional[int] = None,
        position: Optional[int] = None,
        sync_permissions: bool = False,
        update_permissions: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Edit channel properties.

        Args:
            guild: Target guild.
            channel_id: ID of the channel to edit.
            name: New channel name.
            topic: New topic / description.
            nsfw: Toggle age-restriction.
            slowmode_delay: Seconds between messages (0–21600).
            bitrate: Audio bitrate for voice/stage (bps).
            user_limit: Max users for voice (0 = unlimited).
            position: Sidebar position.
            sync_permissions: Sync overwrites with parent category.
            update_permissions: Granularly update overwrites for a role/user.
                Format: {"target_id": 123456, "permissions": {"send_messages": False}}.

        Returns:
            Dict with updated fields list.
        """
        channel = guild.get_channel(int(channel_id))
        if channel is None:
            raise ValueError(f"Channel '{channel_id}' not found in guild")

        # Build the edit payload — only include non-None values
        payload: Dict[str, Any] = {}
        candidates = {
            "name": name,
            "topic": topic,
            "nsfw": nsfw,
            "slowmode_delay": slowmode_delay,
            "bitrate": bitrate,
            "user_limit": user_limit,
            "position": position,
        }
        for key, val in candidates.items():
            if val is not None and hasattr(channel, key):
                payload[key] = val

        try:
            # Handle sync_permissions with parent category
            if sync_permissions and channel.category:
                payload["sync_permissions"] = True

            # Handle granular permission update for a specific role/user
            if update_permissions:
                target_id = update_permissions.get("target_id")
                perm_flags = update_permissions.get("permissions", {})
                target = guild.get_role(int(target_id)) or guild.get_member(int(target_id))
                if target and perm_flags:
                    overwrite = channel.overwrites_for(target)
                    for flag, val in perm_flags.items():
                        if hasattr(overwrite, flag):
                            setattr(overwrite, flag, val)
                    await channel.set_permissions(target, overwrite=overwrite)

            if payload:
                await channel.edit(**payload)

            updated_fields = list(payload.keys())
            if update_permissions:
                updated_fields.append("permissions")

            if not updated_fields:
                raise ValueError("No valid edit parameters provided for this channel type")

            logger.info("Edited channel '%s' (id=%s): %s", channel.name, channel_id, updated_fields)
            return {
                "channel_id": str(channel_id),
                "updated_fields": updated_fields,
            }
        except nextcord.errors.Forbidden:
            raise PermissionError("manage_channels")
        except nextcord.errors.HTTPException as exc:
            raise RuntimeError(f"Failed to edit channel: {exc}")

    async def list(
        self,
        guild: nextcord.Guild,
        type_filter: Optional[str] = None,
    ) -> Dict[str, Any]:
        """List all channels in the guild with optional type filter.

        Args:
            guild: Target guild.
            type_filter: Optional channel type to filter by
                ('text', 'voice', 'stage', 'forum', 'news', 'category').

        Returns:
            Dict with channel list and count.
        """
        # Map user-friendly type names to nextcord ChannelType values
        type_map = {
            "text": nextcord.ChannelType.text,
            "voice": nextcord.ChannelType.voice,
            "stage": nextcord.ChannelType.stage_voice,
            "forum": nextcord.ChannelType.forum,
            "news": nextcord.ChannelType.news,
            "announcement": nextcord.ChannelType.news,
            "category": nextcord.ChannelType.category,
        }

        target_type = type_map.get(type_filter.lower()) if type_filter else None

        channels = []
        for ch in guild.channels:
            if target_type and ch.type != target_type:
                continue
            channels.append({
                "id": str(ch.id),
                "name": ch.name,
                "type": str(ch.type).replace("ChannelType.", ""),
                "category_id": str(ch.category_id) if ch.category_id else None,
                "position": ch.position,
            })

        channels.sort(key=lambda c: (c["category_id"] or "", c["position"]))
        return {"channels": channels, "count": len(channels)}

    # ------------------------------------------------------------------
    # BaseConnector interface
    # ------------------------------------------------------------------

    async def execute(self, action: str, **params: Any) -> Dict[str, Any]:
        """Dispatch to the appropriate action method."""
        actions = {
            "create": self.create,
            "delete": self.delete,
            "rename": self.rename,
            "move": self.move,
            "edit": self.edit,
            "list": self.list,
        }
        handler = actions.get(action)
        if handler is None:
            raise ValueError(
                f"Unknown action '{action}' for ChannelsConnector. "
                f"Available: {list(actions.keys())}"
            )
        return await handler(**params)

    def get_tool_definitions(self) -> List[ToolDefinition]:
        """Return tool definitions for all channel operations."""
        return [
            ToolDefinition(
                name="discord.channels.create",
                description=(
                    "Create a new channel in the guild. Supports types: text, voice, stage, forum, news/announcement. "
                    "Can configure privacy (is_private), permission overwrites (allowed_role_ids, allowed_user_ids, "
                    "advanced_permissions), slowmode, NSFW, bitrate, user_limit, and position."
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "guild_id": {"type": "string", "description": "Target guild ID."},
                        "name": {"type": "string", "description": "Channel name."},
                        "type": {
                            "type": "string",
                            "enum": ["text", "voice", "stage", "forum", "news", "announcement"],
                            "description": "Channel type. Default: 'text'.",
                        },
                        "category_id": {"type": "string", "description": "Parent category ID (optional)."},
                        "topic": {"type": "string", "description": "Channel topic/description (text, forum, stage)."},
                        "bitrate": {"type": "integer", "description": "Audio bitrate in bps for voice/stage (e.g. 64000)."},
                        "user_limit": {"type": "integer", "description": "Max users for voice channels (0 = unlimited)."},
                        "slowmode_delay": {"type": "integer", "description": "Seconds between messages for text/forum (0–21600)."},
                        "nsfw": {"type": "boolean", "description": "Mark as age-restricted."},
                        "is_private": {"type": "boolean", "description": "Hide from @everyone. Use with allowed_role_ids/allowed_user_ids."},
                        "allowed_role_ids": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Role IDs that can see this channel when is_private=true.",
                        },
                        "allowed_user_ids": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Member IDs that can see this channel when is_private=true.",
                        },
                        "advanced_permissions": {
                            "type": "object",
                            "description": "Custom permission flags, e.g. {\"send_messages\": false, \"attach_files\": true}.",
                            "additionalProperties": {"type": "boolean"},
                        },
                        "sync_permissions": {"type": "boolean", "description": "Sync permissions with parent category after creation."},
                        "position": {"type": "integer", "description": "Sidebar position."},
                    },
                    "required": ["guild_id", "name"],
                },
                risk_level="medium",
            ),
            ToolDefinition(
                name="discord.channels.delete",
                description="Permanently delete a channel from the guild. This action is irreversible.",
                parameters={
                    "type": "object",
                    "properties": {
                        "guild_id": {"type": "string", "description": "Target guild ID."},
                        "channel_id": {"type": "string", "description": "Channel ID to delete."},
                        "reason": {"type": "string", "description": "Audit log reason (optional)."},
                    },
                    "required": ["guild_id", "channel_id"],
                },
                risk_level="high",
            ),
            ToolDefinition(
                name="discord.channels.rename",
                description="Rename an existing channel.",
                parameters={
                    "type": "object",
                    "properties": {
                        "guild_id": {"type": "string", "description": "Target guild ID."},
                        "channel_id": {"type": "string", "description": "Channel ID to rename."},
                        "new_name": {"type": "string", "description": "The new channel name."},
                    },
                    "required": ["guild_id", "channel_id", "new_name"],
                },
                risk_level="medium",
            ),
            ToolDefinition(
                name="discord.channels.move",
                description="Move a channel to a different category, with optional position and permission sync.",
                parameters={
                    "type": "object",
                    "properties": {
                        "guild_id": {"type": "string", "description": "Target guild ID."},
                        "channel_id": {"type": "string", "description": "Channel ID to move."},
                        "category_id": {"type": "string", "description": "Destination category ID."},
                        "position": {"type": "integer", "description": "Position within category (optional)."},
                        "sync_permissions": {"type": "boolean", "description": "Sync permissions with the new category."},
                    },
                    "required": ["guild_id", "channel_id", "category_id"],
                },
                risk_level="medium",
            ),
            ToolDefinition(
                name="discord.channels.edit",
                description=(
                    "Edit channel properties: name, topic, nsfw, slowmode_delay, bitrate, user_limit, position. "
                    "Can also sync permissions with parent category or update granular permission overwrites "
                    "for a specific role or user via update_permissions."
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "guild_id": {"type": "string", "description": "Target guild ID."},
                        "channel_id": {"type": "string", "description": "Channel ID to edit."},
                        "name": {"type": "string", "description": "New channel name."},
                        "topic": {"type": "string", "description": "New channel topic."},
                        "nsfw": {"type": "boolean", "description": "Toggle age-restriction."},
                        "slowmode_delay": {"type": "integer", "description": "Seconds between messages (0–21600)."},
                        "bitrate": {"type": "integer", "description": "Audio bitrate for voice/stage in bps."},
                        "user_limit": {"type": "integer", "description": "Max users for voice channel (0 = unlimited)."},
                        "position": {"type": "integer", "description": "Sidebar position."},
                        "sync_permissions": {"type": "boolean", "description": "Sync overwrites with parent category."},
                        "update_permissions": {
                            "type": "object",
                            "description": (
                                "Granularly update overwrites for one role or user. "
                                "Format: {\"target_id\": \"<role_or_member_id>\", "
                                "\"permissions\": {\"send_messages\": false, \"attach_files\": true}}"
                            ),
                            "properties": {
                                "target_id": {"type": "string"},
                                "permissions": {
                                    "type": "object",
                                    "additionalProperties": {"type": "boolean"},
                                },
                            },
                            "required": ["target_id", "permissions"],
                        },
                    },
                    "required": ["guild_id", "channel_id"],
                },
                risk_level="medium",
            ),
            ToolDefinition(
                name="discord.channels.list",
                description="List all channels in the guild. Optionally filter by type (text, voice, stage, forum, news, category).",
                parameters={
                    "type": "object",
                    "properties": {
                        "guild_id": {"type": "string", "description": "Target guild ID."},
                        "type_filter": {
                            "type": "string",
                            "enum": ["text", "voice", "stage", "forum", "news", "announcement", "category"],
                            "description": "Optional: filter results to this channel type.",
                        },
                    },
                    "required": ["guild_id"],
                },
                risk_level="low",
            ),
        ]

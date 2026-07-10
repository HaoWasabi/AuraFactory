"""Discord Channels Connector — kwargs pattern.

All optional params flow through **kwargs and are spread into Nextcord.
KwargsFilter (from core) handles validation BEFORE this code runs.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

import nextcord

from app.connectors.base import BaseConnector, build_overwrites, channel_to_dict
from app.connectors.discord.exceptions import CommunityRequiredError

logger = logging.getLogger(__name__)


class ChannelsConnector(BaseConnector):
    """Channel CRUD with **kwargs — code stays minimal and clean."""

    def __init__(self, bot: nextcord.Bot) -> None:
        self._bot = bot

    async def execute(self, action: str, guild: nextcord.Guild, **kwargs) -> Dict[str, Any]:
        actions = {
            "create": self.create,
            "rename": self.rename,
            "edit": self.edit,
            "delete": self.delete,
            "move": self.move,
            "list": self.list,
        }
        handler = actions.get(action)
        if handler is None:
            raise ValueError(f"Unknown action '{action}'. Available: {list(actions.keys())}")
        return await handler(guild, **kwargs)

    # ------------------------------------------------------------------
    # CREATE
    # ------------------------------------------------------------------

    async def create(self, guild: nextcord.Guild, name: str, type: str = "text", **kwargs) -> Dict[str, Any]:
        """Create a channel. All optional params via **kwargs.

        Handled kwargs: category_id, position, topic, slowmode_delay, nsfw,
            bitrate, user_limit, rtc_region, is_private, allowed_role_ids,
            allowed_user_ids, advanced_permissions, reason
        """
        if not name or not name.strip():
            raise ValueError("Channel name cannot be empty")

        c_type = type.lower().strip()

        # Extract permission params → build overwrites
        is_private = kwargs.pop("is_private", False)
        allowed_role_ids = kwargs.pop("allowed_role_ids", None)
        allowed_user_ids = kwargs.pop("allowed_user_ids", None)
        advanced_permissions = kwargs.pop("advanced_permissions", None)

        overwrites = build_overwrites(
            guild, is_private=is_private,
            allowed_role_ids=allowed_role_ids,
            allowed_user_ids=allowed_user_ids,
            advanced_permissions=advanced_permissions,
        )

        # Extract category
        category_id = kwargs.pop("category_id", None)
        category: Optional[nextcord.CategoryChannel] = None
        if category_id is not None:
            raw = guild.get_channel(int(category_id))
            if isinstance(raw, nextcord.CategoryChannel):
                category = raw

        # Build shared creation kwargs
        create_kwargs: Dict[str, Any] = {}
        if category:
            create_kwargs["category"] = category
        if overwrites:
            create_kwargs["overwrites"] = overwrites

        position = kwargs.pop("position", None)
        if position is not None:
            create_kwargs["position"] = int(position)

        reason = kwargs.pop("reason", None)
        if reason:
            create_kwargs["reason"] = reason

        try:
            channel: nextcord.abc.GuildChannel

            if c_type == "text":
                # Spread remaining kwargs (topic, slowmode_delay, nsfw)
                channel = await guild.create_text_channel(name=name, **create_kwargs, **kwargs)

            elif c_type == "voice":
                kwargs.pop("topic", None)  # voice doesn't support topic
                channel = await guild.create_voice_channel(name=name, **create_kwargs, **kwargs)

            elif c_type == "stage":
                if "COMMUNITY" not in guild.features:
                    raise CommunityRequiredError(
                        feature_needed="COMMUNITY",
                        blocked_action="create_stage_channel",
                        channel_name=name,
                    )
                topic = kwargs.pop("topic", None)
                channel = await guild.create_stage_channel(name=name, **create_kwargs, **kwargs)
                try:
                    await channel.create_instance(topic=topic or "Welcome!")
                except Exception:
                    pass

            elif c_type == "forum":
                if "COMMUNITY" not in guild.features:
                    raise CommunityRequiredError(
                        feature_needed="COMMUNITY",
                        blocked_action="create_forum_channel",
                        channel_name=name,
                    )
                channel = await guild.create_forum_channel(name=name, **create_kwargs, **kwargs)

            elif c_type in ("news", "announcement"):
                if "COMMUNITY" not in guild.features:
                    raise CommunityRequiredError(
                        feature_needed="COMMUNITY",
                        blocked_action="create_news_channel",
                        channel_name=name,
                    )
                channel = await guild.create_news_channel(name=name, **create_kwargs, **kwargs)

            else:
                raise ValueError(f"Unsupported type '{type}'. Valid: text, voice, stage, forum, news")

            # Sync permissions with category if public
            if category and not overwrites:
                try:
                    await channel.edit(sync_permissions=True)
                except Exception:
                    pass

            logger.info("Created %s channel '%s' (id=%s)", c_type, channel.name, channel.id)
            result = channel_to_dict(channel)
            result["is_private"] = is_private
            return result

        except nextcord.Forbidden:
            raise PermissionError("manage_channels")
        except nextcord.HTTPException as exc:
            raise RuntimeError(f"Failed to create channel: {exc}")

    # ------------------------------------------------------------------
    # EDIT
    # ------------------------------------------------------------------

    # ------------------------------------------------------------------
    # RENAME
    # ------------------------------------------------------------------

    async def rename(self, guild: nextcord.Guild, channel_id: int, name: str, **kwargs) -> Dict[str, Any]:
        """Rename a channel (convenience wrapper over edit)."""
        if not name or not name.strip():
            raise ValueError("Channel name cannot be empty")

        channel = guild.get_channel(int(channel_id))
        if channel is None:
            raise ValueError(f"Channel '{channel_id}' not found")

        reason = kwargs.pop("reason", None)

        try:
            old_name = channel.name
            await channel.edit(name=name.strip(), reason=reason)
            logger.info("Renamed channel '%s' → '%s' (id=%s)", old_name, name, channel_id)
            return {"id": str(channel_id), "old_name": old_name, "new_name": channel.name}
        except nextcord.Forbidden:
            raise PermissionError("manage_channels")
        except nextcord.HTTPException as exc:
            raise RuntimeError(f"Failed to rename channel: {exc}")

    # ------------------------------------------------------------------
    # EDIT (original)
    # ------------------------------------------------------------------

    async def edit(self, guild: nextcord.Guild, channel_id: int, **kwargs) -> Dict[str, Any]:
        """Edit channel. Only provided kwargs are changed.

        Handled kwargs: name, topic, slowmode_delay, nsfw, bitrate, user_limit,
            rtc_region, position, category_id, sync_permissions, update_permissions, reason
        """
        channel = guild.get_channel(int(channel_id))
        if channel is None:
            raise ValueError(f"Channel '{channel_id}' not found")

        # Handle special params that need pre-processing
        sync_permissions = kwargs.pop("sync_permissions", False)
        update_permissions = kwargs.pop("update_permissions", None)
        reason = kwargs.pop("reason", None)

        # Handle category move
        new_cat_id = kwargs.pop("category_id", None)
        if new_cat_id is not None:
            cat = guild.get_channel(int(new_cat_id))
            if isinstance(cat, nextcord.CategoryChannel):
                kwargs["category"] = cat

        try:
            # Granular permission update for a specific role/user
            if update_permissions:
                target_id = update_permissions.get("target_id")
                perm_flags = update_permissions.get("permissions", {})
                target = guild.get_role(int(target_id)) or guild.get_member(int(target_id))
                if target and perm_flags:
                    overwrite = channel.overwrites_for(target)
                    for flag, val in perm_flags.items():
                        if hasattr(overwrite, flag):
                            setattr(overwrite, flag, val)
                    await channel.set_permissions(target, overwrite=overwrite, reason=reason)

            # Sync with parent category
            if sync_permissions and channel.category:
                kwargs["sync_permissions"] = True

            # Apply edits — spread remaining kwargs directly
            if kwargs:
                await channel.edit(reason=reason, **kwargs)

            updated_fields = list(kwargs.keys())
            if update_permissions:
                updated_fields.append("permissions")

            logger.info("Edited channel '%s' (id=%s): %s", channel.name, channel_id, updated_fields)
            return {
                "id": str(channel_id),
                "name": channel.name,
                "updated_fields": updated_fields,
            }

        except nextcord.Forbidden:
            raise PermissionError("manage_channels")
        except nextcord.HTTPException as exc:
            raise RuntimeError(f"Failed to edit channel: {exc}")

    # ------------------------------------------------------------------
    # DELETE
    # ------------------------------------------------------------------

    async def delete(self, guild: nextcord.Guild, channel_id: int, **kwargs) -> Dict[str, Any]:
        """Delete a channel permanently."""
        channel = guild.get_channel(int(channel_id))
        if channel is None:
            raise ValueError(f"Channel '{channel_id}' not found")

        reason = kwargs.pop("reason", None)

        try:
            name = channel.name
            await channel.delete(reason=reason)
            logger.info("Deleted channel '%s' (id=%s)", name, channel_id)
            return {"deleted": True, "id": str(channel_id), "name": name}
        except nextcord.Forbidden:
            raise PermissionError("manage_channels")
        except nextcord.HTTPException as exc:
            raise RuntimeError(f"Failed to delete channel: {exc}")

    # ------------------------------------------------------------------
    # MOVE
    # ------------------------------------------------------------------

    async def move(self, guild: nextcord.Guild, channel_id: int, **kwargs) -> Dict[str, Any]:
        """Move channel to different category/position."""
        channel = guild.get_channel(int(channel_id))
        if channel is None:
            raise ValueError(f"Channel '{channel_id}' not found")

        edit_kwargs: Dict[str, Any] = {}

        cat_id = kwargs.pop("category_id", None)
        if cat_id is not None:
            cat = guild.get_channel(int(cat_id))
            if isinstance(cat, nextcord.CategoryChannel):
                edit_kwargs["category"] = cat

        position = kwargs.pop("position", None)
        if position is not None:
            edit_kwargs["position"] = int(position)

        sync = kwargs.pop("sync_permissions", False)
        if sync:
            edit_kwargs["sync_permissions"] = True

        if not edit_kwargs:
            raise ValueError("No move parameters provided (category_id or position)")

        try:
            await channel.edit(**edit_kwargs)
            logger.info("Moved channel '%s' (id=%s)", channel.name, channel_id)
            return channel_to_dict(channel)
        except nextcord.Forbidden:
            raise PermissionError("manage_channels")
        except nextcord.HTTPException as exc:
            raise RuntimeError(f"Failed to move channel: {exc}")

    # ------------------------------------------------------------------
    # LIST
    # ------------------------------------------------------------------

    async def list(self, guild: nextcord.Guild, **kwargs) -> Dict[str, Any]:
        """List channels, optionally filtered by category or type."""
        filter_cat = kwargs.get("category_id")
        filter_type = kwargs.get("type", "all")

        channels = []
        for ch in guild.channels:
            # Skip categories themselves
            if isinstance(ch, nextcord.CategoryChannel):
                continue

            # Filter by category
            if filter_cat is not None and ch.category_id != int(filter_cat):
                continue

            # Filter by type
            if filter_type != "all":
                type_map = {
                    "text": nextcord.ChannelType.text,
                    "voice": nextcord.ChannelType.voice,
                    "stage": nextcord.ChannelType.stage_voice,
                    "forum": nextcord.ChannelType.forum,
                    "news": nextcord.ChannelType.news,
                }
                expected = type_map.get(filter_type)
                if expected and ch.type != expected:
                    continue

            channels.append(channel_to_dict(ch))

        return {"channels": channels, "count": len(channels)}

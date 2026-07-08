"""Discord Channels Connector — SPEC v2 rewrite.

Uses **kwargs pattern with validation whitelist guard rails.
Supported channel types: text, voice, stage, forum, news/announcement.

Actions: create, edit, delete, move, rename, list
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

import nextcord

from app.connectors.base import BaseConnector
from app.connectors.discord._helpers import build_overwrites
from app.connectors.discord._permissions import check_bot_permissions
from app.connectors.discord._validation import (
    check_community_required,
    validate_kwargs,
)

logger = logging.getLogger(__name__)


class ChannelsConnector(BaseConnector):
    """Manages Discord guild channels with **kwargs pattern + validation."""

    def __init__(self, bot: nextcord.Bot) -> None:
        self._bot = bot

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------

    async def create(self, guild: nextcord.Guild, name: str, type: str = "text", **kwargs) -> Dict[str, Any]:
        """Create a new channel in the guild.

        LLM passes any relevant params via **kwargs — only whitelisted params
        for the given channel type are accepted. Others are silently dropped.

        Required: name, type
        Optional (varies by type): topic, slowmode_delay, nsfw, bitrate, user_limit,
            rtc_region, category_id, position, is_private, allowed_role_ids,
            allowed_user_ids, advanced_permissions, reason
        """
        if not name or not name.strip():
            raise ValueError("Channel name cannot be empty")

        # Layer 1: Bot permission check
        perm_error = check_bot_permissions(guild, "discord.channels.create")
        if perm_error:
            raise PermissionError(perm_error)

        c_type = type.lower().strip()

        # Validate kwargs against whitelist for this channel type
        clean = validate_kwargs("discord.channels.create", kwargs, context=c_type)

        # Extract and resolve category
        category_id = clean.pop("category_id", None)
        category: Optional[nextcord.CategoryChannel] = None
        if category_id is not None:
            raw = guild.get_channel(int(category_id))
            if raw is None or not isinstance(raw, nextcord.CategoryChannel):
                raise ValueError(f"Category '{category_id}' not found or is not a category")
            category = raw

        # Extract permission-related kwargs and build overwrites
        is_private = clean.pop("is_private", False)
        allowed_role_ids = clean.pop("allowed_role_ids", None)
        allowed_user_ids = clean.pop("allowed_user_ids", None)
        advanced_permissions = clean.pop("advanced_permissions", None)

        overwrites = build_overwrites(
            guild,
            is_private=is_private,
            allowed_role_ids=allowed_role_ids,
            allowed_user_ids=allowed_user_ids,
            advanced_permissions=advanced_permissions,
        )

        # Build shared creation kwargs
        shared: Dict[str, Any] = {}
        if category:
            shared["category"] = category
        if overwrites:
            shared["overwrites"] = overwrites

        position = clean.pop("position", None)
        if position is not None:
            shared["position"] = int(position)

        reason = clean.pop("reason", None)
        if reason:
            shared["reason"] = reason

        try:
            channel: nextcord.abc.GuildChannel

            if c_type == "text":
                # Spread remaining clean kwargs (topic, slowmode_delay, nsfw)
                channel = await guild.create_text_channel(name=name, **shared, **clean)

            elif c_type == "voice":
                # voice doesn't accept 'topic' — already filtered by whitelist
                channel = await guild.create_voice_channel(name=name, **shared, **clean)

            elif c_type == "stage":
                err = check_community_required(guild)
                if err:
                    raise ValueError(err)
                topic = clean.pop("topic", None)
                channel = await guild.create_stage_channel(name=name, **shared, **clean)
                # Open stage instance (non-fatal)
                try:
                    await channel.create_instance(topic=topic or "Welcome!")
                except Exception:
                    pass

            elif c_type == "forum":
                channel = await guild.create_forum_channel(name=name, **shared, **clean)

            elif c_type in ("news", "announcement"):
                err = check_community_required(guild)
                if err:
                    raise ValueError(err)
                channel = await guild.create_news_channel(name=name, **shared, **clean)

            else:
                raise ValueError(
                    f"Unsupported channel type '{type}'. "
                    "Valid: text, voice, stage, forum, news, announcement."
                )

            # Sync permissions with category if public and no custom overwrites
            if category and not overwrites:
                try:
                    await channel.edit(sync_permissions=True)
                except Exception:
                    pass

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
            raise PermissionError("Bot lacks 'Manage Channels' permission.")
        except nextcord.errors.HTTPException as exc:
            raise RuntimeError(f"Failed to create channel: {exc}")

    async def edit(self, guild: nextcord.Guild, channel_id: int, **kwargs) -> Dict[str, Any]:
        """Edit channel properties. Only provided params are updated.

        Optional kwargs (varies by type): name, topic, slowmode_delay, nsfw,
            bitrate, user_limit, rtc_region, position, category_id,
            sync_permissions, update_permissions, reason
        """
        perm_error = check_bot_permissions(guild, "discord.channels.edit")
        if perm_error:
            raise PermissionError(perm_error)

        channel = guild.get_channel(int(channel_id))
        if channel is None:
            raise ValueError(f"Channel '{channel_id}' not found in guild")

        # Determine channel type for context-aware validation
        type_map = {
            nextcord.ChannelType.text: "text",
            nextcord.ChannelType.voice: "voice",
            nextcord.ChannelType.stage_voice: "stage",
            nextcord.ChannelType.forum: "forum",
            nextcord.ChannelType.news: "news",
        }
        ctx = type_map.get(channel.type, "text")

        clean = validate_kwargs("discord.channels.edit", kwargs, context=ctx)

        # Handle sync_permissions
        sync_permissions = clean.pop("sync_permissions", False)

        # Handle granular permission update
        update_permissions = clean.pop("update_permissions", None)

        # Handle category move
        new_category_id = clean.pop("category_id", None)
        if new_category_id is not None:
            cat = guild.get_channel(int(new_category_id))
            if isinstance(cat, nextcord.CategoryChannel):
                clean["category"] = cat

        reason = clean.pop("reason", None)

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
                clean["sync_permissions"] = True

            # Apply edits
            if clean:
                await channel.edit(reason=reason, **clean)

            updated_fields = list(clean.keys())
            if update_permissions:
                updated_fields.append("permissions")

            if not updated_fields:
                raise ValueError("No valid edit parameters provided for this channel type")

            logger.info("Edited channel '%s' (id=%s): %s", channel.name, channel_id, updated_fields)
            return {
                "id": str(channel_id),
                "name": channel.name,
                "updated_fields": updated_fields,
            }

        except nextcord.errors.Forbidden:
            raise PermissionError("Bot lacks permission to edit this channel.")
        except nextcord.errors.HTTPException as exc:
            raise RuntimeError(f"Failed to edit channel: {exc}")

    async def delete(self, guild: nextcord.Guild, channel_id: int, **kwargs) -> Dict[str, Any]:
        """Delete a channel by ID.

        Optional kwargs: reason
        """
        perm_error = check_bot_permissions(guild, "discord.channels.delete")
        if perm_error:
            raise PermissionError(perm_error)

        clean = validate_kwargs("discord.channels.delete", kwargs)

        channel = guild.get_channel(int(channel_id))
        if channel is None:
            raise ValueError(f"Channel '{channel_id}' not found in guild")

        try:
            name = channel.name
            await channel.delete(reason=clean.get("reason", "AI Agent Request"))
            logger.info("Deleted channel '%s' (id=%s)", name, channel_id)
            return {"id": str(channel_id), "name": name, "deleted": True}
        except nextcord.errors.Forbidden:
            raise PermissionError("Bot lacks 'Manage Channels' permission.")
        except nextcord.errors.HTTPException as exc:
            raise RuntimeError(f"Failed to delete channel: {exc}")

    async def move(self, guild: nextcord.Guild, channel_id: int, category_id: int, **kwargs) -> Dict[str, Any]:
        """Move a channel to a different category.

        Optional kwargs: position, sync_permissions
        """
        perm_error = check_bot_permissions(guild, "discord.channels.move")
        if perm_error:
            raise PermissionError(perm_error)

        clean = validate_kwargs("discord.channels.move", kwargs)

        channel = guild.get_channel(int(channel_id))
        if channel is None:
            raise ValueError(f"Channel '{channel_id}' not found in guild")

        category = guild.get_channel(int(category_id))
        if category is None or not isinstance(category, nextcord.CategoryChannel):
            raise ValueError(f"Category '{category_id}' not found")

        try:
            edit_kwargs: Dict[str, Any] = {"category": category}
            if "position" in clean:
                edit_kwargs["position"] = int(clean["position"])
            if clean.get("sync_permissions"):
                edit_kwargs["sync_permissions"] = True

            await channel.edit(**edit_kwargs)
            logger.info("Moved channel '%s' to category '%s'", channel.name, category.name)
            return {
                "id": str(channel_id),
                "name": channel.name,
                "new_category_id": str(category_id),
                "new_category_name": category.name,
            }
        except nextcord.errors.Forbidden:
            raise PermissionError("Bot lacks permission to move this channel.")
        except nextcord.errors.HTTPException as exc:
            raise RuntimeError(f"Failed to move channel: {exc}")

    async def list(self, guild: nextcord.Guild, type_filter: Optional[str] = None, **kwargs) -> Dict[str, Any]:
        """List all channels in the guild with optional type filter.

        Optional: type_filter ('text', 'voice', 'stage', 'forum', 'news', 'category')
        """
        type_map = {
            "text": nextcord.ChannelType.text,
            "voice": nextcord.ChannelType.voice,
            "stage": nextcord.ChannelType.stage_voice,
            "forum": nextcord.ChannelType.forum,
            "news": nextcord.ChannelType.news,
            "announcement": nextcord.ChannelType.news,
            "category": nextcord.ChannelType.category,
        }

        channels = guild.channels
        if type_filter:
            target_type = type_map.get(type_filter.lower().strip())
            if target_type:
                channels = [ch for ch in channels if ch.type == target_type]

        result = []
        for ch in sorted(channels, key=lambda c: (c.position, c.name)):
            info = {
                "id": str(ch.id),
                "name": ch.name,
                "type": str(ch.type).split(".")[-1],
                "position": ch.position,
            }
            if hasattr(ch, "category_id") and ch.category_id:
                info["category_id"] = str(ch.category_id)
            result.append(info)

        return {"channels": result, "count": len(result)}

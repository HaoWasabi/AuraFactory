"""GuildCrawler — extracts guild structure into GuildKnowledge.

Uses nextcord Guild objects to crawl channels, roles, categories,
and member count into a structured snapshot.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from app.knowledge.models import GuildKnowledge

logger = logging.getLogger(__name__)


class GuildCrawler:
    """Crawls a Discord guild to extract structural knowledge.

    Uses the nextcord Guild object to enumerate channels, roles,
    categories, and metadata into a GuildKnowledge snapshot.
    """

    def __init__(self, bot: Any) -> None:
        """Initialize with bot instance.

        Args:
            bot: Nextcord Bot instance for API access.
        """
        self._bot = bot
        logger.info("GuildCrawler initialized")

    async def crawl(self, guild: Any) -> GuildKnowledge:
        """Crawl a guild and return structured knowledge.

        Extracts:
        - All text and voice channels with metadata
        - All roles with permissions
        - All categories with child channels
        - Member count
        - Guild rules (if available)

        Args:
            guild: Nextcord Guild object.

        Returns:
            Populated GuildKnowledge dataclass.
        """
        logger.info("Crawling guild '%s' (ID: %d)", guild.name, guild.id)

        channels = self._crawl_channels(guild)
        roles = self._crawl_roles(guild)
        categories = self._crawl_categories(guild)
        rules = self._extract_rules(guild)
        member_count = guild.member_count or len(guild.members)

        knowledge = GuildKnowledge(
            guild_id=guild.id,
            guild_name=guild.name,
            channels=channels,
            roles=roles,
            categories=categories,
            member_count=member_count,
            rules=rules,
            crawled_at=datetime.now(timezone.utc),
        )

        logger.info(
            "Crawled guild '%s': %d channels, %d roles, %d categories, %d members",
            guild.name,
            len(channels),
            len(roles),
            len(categories),
            member_count,
        )
        return knowledge

    def _crawl_channels(self, guild: Any) -> list[dict[str, Any]]:
        """Extract all channels from guild.

        Args:
            guild: Nextcord Guild object.

        Returns:
            List of channel info dicts.
        """
        channels: list[dict[str, Any]] = []

        for channel in guild.channels:
            # Skip category channels — handled separately
            if hasattr(channel, "type") and str(channel.type) == "category":
                continue

            channel_data: dict[str, Any] = {
                "id": channel.id,
                "name": channel.name,
                "type": str(channel.type),
                "position": getattr(channel, "position", 0),
                "category_id": getattr(channel, "category_id", None),
            }

            # Add topic for text channels
            if hasattr(channel, "topic") and channel.topic:
                channel_data["topic"] = channel.topic

            # Add bitrate for voice channels
            if hasattr(channel, "bitrate"):
                channel_data["bitrate"] = channel.bitrate

            # Add user limit for voice channels
            if hasattr(channel, "user_limit") and channel.user_limit:
                channel_data["user_limit"] = channel.user_limit

            # Add NSFW flag
            if hasattr(channel, "nsfw"):
                channel_data["nsfw"] = channel.nsfw

            # Add slowmode
            if hasattr(channel, "slowmode_delay") and channel.slowmode_delay:
                channel_data["slowmode_delay"] = channel.slowmode_delay

            channels.append(channel_data)

        # Sort by position
        channels.sort(key=lambda c: c.get("position", 0))
        return channels

    def _crawl_roles(self, guild: Any) -> list[dict[str, Any]]:
        """Extract all roles from guild.

        Args:
            guild: Nextcord Guild object.

        Returns:
            List of role info dicts.
        """
        roles: list[dict[str, Any]] = []

        for role in guild.roles:
            role_data: dict[str, Any] = {
                "id": role.id,
                "name": role.name,
                "color": role.color.value if hasattr(role.color, "value") else int(role.color),
                "position": role.position,
                "permissions": role.permissions.value
                if hasattr(role.permissions, "value")
                else int(role.permissions),
                "mentionable": role.mentionable,
                "managed": role.managed,
                "hoist": role.hoist,
            }
            roles.append(role_data)

        # Sort by position descending (highest role first)
        roles.sort(key=lambda r: r.get("position", 0), reverse=True)
        return roles

    def _crawl_categories(self, guild: Any) -> list[dict[str, Any]]:
        """Extract all categories from guild.

        Args:
            guild: Nextcord Guild object.

        Returns:
            List of category info dicts with child channel IDs.
        """
        categories: list[dict[str, Any]] = []

        for category in guild.categories:
            channel_ids = [ch.id for ch in category.channels] if hasattr(category, "channels") else []

            category_data: dict[str, Any] = {
                "id": category.id,
                "name": category.name,
                "position": getattr(category, "position", 0),
                "channel_ids": channel_ids,
            }
            categories.append(category_data)

        categories.sort(key=lambda c: c.get("position", 0))
        return categories

    def _extract_rules(self, guild: Any) -> list[str]:
        """Extract guild rules if available.

        Checks guild.rules_channel for pinned rules content.

        Args:
            guild: Nextcord Guild object.

        Returns:
            List of rule strings (empty if none found).
        """
        rules: list[str] = []

        # Check guild description
        if hasattr(guild, "description") and guild.description:
            rules.append(f"Description: {guild.description}")

        # Check rules channel reference
        if hasattr(guild, "rules_channel") and guild.rules_channel:
            rules.append(f"Rules channel: #{guild.rules_channel.name}")

        # Check community features
        if hasattr(guild, "features") and guild.features:
            features_str = ", ".join(guild.features)
            rules.append(f"Features: {features_str}")

        return rules

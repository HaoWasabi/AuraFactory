# app/knowledge/crawler.py
"""
Server Crawler — extracts server structure from Discord guild object.
Uses nextcord guild/channel/role API to build ServerKnowledge.
"""
import logging
from typing import Optional
from datetime import datetime

import nextcord

from app.knowledge.models import (
    ServerKnowledge,
    ChannelInfo,
    RoleInfo,
    PinnedMessage,
    ScheduledEvent,
)

logger = logging.getLogger(__name__)


class ServerCrawler:
    """
    Crawls a Discord guild and produces a ServerKnowledge snapshot.

    Crawl scope (MVP):
    - Channel names + descriptions + categories
    - Role names + colors + member counts
    - Pinned messages (top 5 per text channel)
    - Scheduled events
    - Server rules (from channel named "rules")

    Does NOT crawl:
    - Message history
    - Member activity
    - Voice channel usage
    """

    MAX_PINS_PER_CHANNEL = 5
    RULES_CHANNEL_NAMES = ("rules", "quy-tac", "noi-quy", "quy-dinh")

    async def crawl(self, guild: nextcord.Guild) -> ServerKnowledge:
        """
        Full crawl of a guild. Returns complete ServerKnowledge.
        Call this on bot join or admin request.
        """
        logger.info(f"Starting full crawl for guild: {guild.name} ({guild.id})")

        knowledge = ServerKnowledge(
            guild_id=guild.id,
            guild_name=guild.name,
            description=guild.description or "",
            member_count=guild.member_count or len(guild.members),
            last_crawled=datetime.utcnow().isoformat(),
        )

        # Crawl categories
        knowledge.categories = [cat.name for cat in guild.categories]

        # Crawl channels
        knowledge.channels = self._crawl_channels(guild)

        # Crawl roles
        knowledge.roles = self._crawl_roles(guild)

        # Crawl pinned messages
        knowledge.pinned_messages = await self._crawl_pinned_messages(guild)

        # Crawl scheduled events
        knowledge.events = await self._crawl_events(guild)

        # Extract rules
        knowledge.rules_text = await self._extract_rules(guild)

        logger.info(
            f"Crawl complete for {guild.name}: "
            f"{len(knowledge.channels)} channels, "
            f"{len(knowledge.roles)} roles, "
            f"{len(knowledge.pinned_messages)} pinned messages"
        )

        return knowledge

    async def incremental_update(
        self, knowledge: ServerKnowledge, guild: nextcord.Guild, event_type: str
    ) -> ServerKnowledge:
        """
        Incremental update based on a Discord event.
        Only re-crawls the affected section.
        """
        if event_type in ("channel_create", "channel_update", "channel_delete"):
            knowledge.channels = self._crawl_channels(guild)
            knowledge.categories = [cat.name for cat in guild.categories]
        elif event_type in ("role_create", "role_update", "role_delete"):
            knowledge.roles = self._crawl_roles(guild)
        elif event_type == "pins_update":
            knowledge.pinned_messages = await self._crawl_pinned_messages(guild)
        elif event_type == "scheduled_event_create":
            knowledge.events = await self._crawl_events(guild)

        knowledge.last_crawled = datetime.utcnow().isoformat()
        return knowledge

    def _crawl_channels(self, guild: nextcord.Guild) -> list:
        """Extract all channels with metadata."""
        channels = []
        for ch in guild.channels:
            if isinstance(ch, nextcord.CategoryChannel):
                continue  # Skip categories, they're tracked separately

            ch_type = "text"
            if isinstance(ch, nextcord.VoiceChannel):
                ch_type = "voice"
            elif isinstance(ch, nextcord.StageChannel):
                ch_type = "stage"
            elif isinstance(ch, nextcord.ForumChannel):
                ch_type = "forum"

            channels.append(ChannelInfo(
                id=ch.id,
                name=ch.name,
                type=ch_type,
                category=ch.category.name if ch.category else None,
                description=getattr(ch, "topic", None) or "",
                position=ch.position,
            ))

        return sorted(channels, key=lambda c: c.position)

    def _crawl_roles(self, guild: nextcord.Guild) -> list:
        """Extract all roles with metadata."""
        roles = []
        for role in guild.roles:
            if role.name == "@everyone":
                continue

            roles.append(RoleInfo(
                id=role.id,
                name=role.name,
                color=str(role.color) if role.color else "",
                member_count=len(role.members) if hasattr(role, "members") else 0,
                is_admin=role.permissions.administrator,
                position=role.position,
            ))

        return sorted(roles, key=lambda r: r.position, reverse=True)

    async def _crawl_pinned_messages(self, guild: nextcord.Guild) -> list:
        """Extract pinned messages from text channels (top N per channel)."""
        pinned = []

        for ch in guild.text_channels:
            try:
                pins = await ch.pins()
                for pin in pins[:self.MAX_PINS_PER_CHANNEL]:
                    content = pin.content or ""
                    # Also capture embed descriptions
                    if pin.embeds:
                        for embed in pin.embeds:
                            if embed.description:
                                content += f"\n{embed.description}"

                    if content.strip():
                        pinned.append(PinnedMessage(
                            channel_name=ch.name,
                            content=content[:500],  # Limit length
                            author=pin.author.display_name if pin.author else "Unknown",
                            pinned_at=pin.created_at.isoformat() if pin.created_at else None,
                        ))
            except (nextcord.Forbidden, nextcord.HTTPException) as e:
                logger.debug(f"Cannot read pins in #{ch.name}: {e}")
                continue

        return pinned

    async def _crawl_events(self, guild: nextcord.Guild) -> list:
        """Extract scheduled events."""
        events = []
        try:
            scheduled = await guild.fetch_scheduled_events()
            for evt in scheduled:
                events.append(ScheduledEvent(
                    name=evt.name,
                    description=evt.description or "",
                    start_time=evt.start_time.isoformat() if evt.start_time else None,
                    end_time=evt.end_time.isoformat() if evt.end_time else None,
                    location=getattr(evt, "location", "") or "",
                ))
        except (nextcord.Forbidden, nextcord.HTTPException) as e:
            logger.debug(f"Cannot fetch events: {e}")

        return events

    async def _extract_rules(self, guild: nextcord.Guild) -> str:
        """Try to find and extract server rules from a rules channel."""
        for ch in guild.text_channels:
            if ch.name.lower() in self.RULES_CHANNEL_NAMES:
                try:
                    pins = await ch.pins()
                    if pins:
                        # Use first pinned message as rules
                        return pins[0].content[:1000] if pins[0].content else ""

                    # Fallback: last few messages in rules channel
                    messages = []
                    async for msg in ch.history(limit=5):
                        if msg.content:
                            messages.append(msg.content)

                    return "\n".join(reversed(messages))[:1000]
                except (nextcord.Forbidden, nextcord.HTTPException):
                    continue

        return ""

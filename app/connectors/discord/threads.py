"""Discord Threads Connector — kwargs pattern. Actions: create, archive, delete"""

from __future__ import annotations
import logging
from typing import Any, Dict
import nextcord
from app.connectors.base import BaseConnector

logger = logging.getLogger(__name__)


class ThreadsConnector(BaseConnector):
    def __init__(self, bot: nextcord.Bot) -> None:
        self._bot = bot

    async def execute(self, action: str, guild: nextcord.Guild, **kwargs) -> Dict[str, Any]:
        actions = {"create": self.create, "archive": self.archive, "delete": self.delete}
        handler = actions.get(action)
        if handler is None:
            raise ValueError(f"Unknown action '{action}'")
        return await handler(guild, **kwargs)

    async def create(self, guild: nextcord.Guild, channel_id: int, name: str, **kwargs) -> Dict[str, Any]:
        """Create thread. kwargs: message_id, auto_archive, type"""
        channel = guild.get_channel(int(channel_id))
        if not isinstance(channel, nextcord.TextChannel):
            raise ValueError(f"Text channel '{channel_id}' not found")

        message_id = kwargs.pop("message_id", None)
        auto_archive = kwargs.pop("auto_archive", 1440)
        thread_type = kwargs.pop("type", "public")

        try:
            if message_id:
                msg = await channel.fetch_message(int(message_id))
                thread = await msg.create_thread(name=name, auto_archive_duration=int(auto_archive))
            else:
                t_type = nextcord.ChannelType.private_thread if thread_type == "private" else nextcord.ChannelType.public_thread
                thread = await channel.create_thread(name=name, auto_archive_duration=int(auto_archive), type=t_type)

            logger.info("Created thread '%s' (id=%s)", name, thread.id)
            return {"id": str(thread.id), "name": thread.name, "parent_id": str(channel_id)}
        except nextcord.Forbidden:
            raise PermissionError("create_public_threads")
        except nextcord.NotFound:
            raise ValueError(f"Message '{message_id}' not found")
        except nextcord.HTTPException as exc:
            raise RuntimeError(f"Failed: {exc}")

    async def archive(self, guild: nextcord.Guild, thread_id: int, **kwargs) -> Dict[str, Any]:
        """Archive a thread."""
        thread = guild.get_thread(int(thread_id))
        if thread is None:
            raise ValueError(f"Thread '{thread_id}' not found")
        try:
            await thread.edit(archived=True)
            return {"archived": True, "id": str(thread_id), "name": thread.name}
        except nextcord.Forbidden:
            raise PermissionError("manage_threads")

    async def delete(self, guild: nextcord.Guild, thread_id: int, **kwargs) -> Dict[str, Any]:
        """Delete a thread."""
        thread = guild.get_thread(int(thread_id))
        if thread is None:
            raise ValueError(f"Thread '{thread_id}' not found")
        try:
            name = thread.name
            await thread.delete()
            return {"deleted": True, "id": str(thread_id), "name": name}
        except nextcord.Forbidden:
            raise PermissionError("manage_threads")

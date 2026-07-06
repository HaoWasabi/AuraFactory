"""
Discord Threads Connector — Thread management operations.

Actions: create, archive, delete
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

import nextcord

from app.connectors.base import BaseConnector
from app.mcp.protocol import ToolDefinition

logger = logging.getLogger(__name__)


class ThreadsConnector(BaseConnector):
    """Manages Discord threads."""

    def __init__(self, bot: nextcord.Bot) -> None:
        self._bot = bot

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------

    async def create(
        self,
        guild: nextcord.Guild,
        channel_id: int,
        name: str,
        message_id: Optional[int] = None,
        auto_archive: int = 1440,
    ) -> Dict[str, Any]:
        """Create a new thread.

        Args:
            guild: The target guild.
            channel_id: Parent channel ID.
            name: Thread name.
            message_id: Optional message ID to create thread from.
            auto_archive: Auto-archive duration in minutes (60, 1440, 4320, 10080).

        Returns:
            Dict with thread info.
        """
        if not name or not name.strip():
            raise ValueError("Thread name cannot be empty")

        channel = guild.get_channel(int(channel_id))
        if channel is None:
            raise ValueError(f"Channel '{channel_id}' not found in guild")
        if not isinstance(channel, nextcord.TextChannel):
            raise ValueError(f"Channel '{channel_id}' is not a text channel")

        try:
            if message_id is not None:
                message = await channel.fetch_message(int(message_id))
                thread = await message.create_thread(
                    name=name,
                    auto_archive_duration=auto_archive,
                )
            else:
                thread = await channel.create_thread(
                    name=name,
                    auto_archive_duration=auto_archive,
                    type=nextcord.ChannelType.public_thread,
                )

            logger.info(
                "Created thread '%s' (id=%s) in channel '%s'",
                name,
                thread.id,
                channel.name,
            )
            return {
                "id": str(thread.id),
                "name": thread.name,
                "parent_id": str(channel_id),
                "auto_archive_duration": auto_archive,
            }
        except nextcord.errors.Forbidden:
            raise PermissionError("create_public_threads")
        except nextcord.errors.NotFound:
            raise ValueError(f"Message '{message_id}' not found in channel")
        except nextcord.errors.HTTPException as exc:
            raise RuntimeError(f"Failed to create thread: {exc}")

    async def archive(
        self,
        guild: nextcord.Guild,
        thread_id: int,
    ) -> Dict[str, Any]:
        """Archive a thread.

        Args:
            guild: The target guild.
            thread_id: ID of the thread to archive.

        Returns:
            Dict confirming the archive.
        """
        thread = guild.get_thread(int(thread_id))
        if thread is None:
            raise ValueError(f"Thread '{thread_id}' not found in guild")

        try:
            await thread.edit(archived=True)
            logger.info("Archived thread '%s' (id=%s)", thread.name, thread_id)
            return {
                "archived": True,
                "thread_id": str(thread_id),
                "name": thread.name,
            }
        except nextcord.errors.Forbidden:
            raise PermissionError("manage_threads")
        except nextcord.errors.HTTPException as exc:
            raise RuntimeError(f"Failed to archive thread: {exc}")

    async def delete(
        self,
        guild: nextcord.Guild,
        thread_id: int,
    ) -> Dict[str, Any]:
        """Delete a thread.

        Args:
            guild: The target guild.
            thread_id: ID of the thread to delete.

        Returns:
            Dict confirming deletion.
        """
        thread = guild.get_thread(int(thread_id))
        if thread is None:
            raise ValueError(f"Thread '{thread_id}' not found in guild")

        try:
            name = thread.name
            await thread.delete()
            logger.info("Deleted thread '%s' (id=%s)", name, thread_id)
            return {"deleted": True, "thread_id": str(thread_id), "name": name}
        except nextcord.errors.Forbidden:
            raise PermissionError("manage_threads")
        except nextcord.errors.HTTPException as exc:
            raise RuntimeError(f"Failed to delete thread: {exc}")

    # ------------------------------------------------------------------
    # BaseConnector interface
    # ------------------------------------------------------------------

    async def execute(self, action: str, **params: Any) -> Dict[str, Any]:
        """Dispatch to the appropriate action method."""
        actions = {
            "create": self.create,
            "archive": self.archive,
            "delete": self.delete,
        }
        handler = actions.get(action)
        if handler is None:
            raise ValueError(
                f"Unknown action '{action}' for ThreadsConnector. "
                f"Available: {list(actions.keys())}"
            )
        return await handler(**params)

    def get_tool_definitions(self) -> List[ToolDefinition]:
        """Return tool definitions for thread operations."""
        return [
            ToolDefinition(
                name="discord.threads.create",
                description="Create a new thread in a text channel.",
                parameters={
                    "type": "object",
                    "properties": {
                        "guild_id": {"type": "string", "description": "Target guild ID."},
                        "channel_id": {"type": "string", "description": "Parent channel ID."},
                        "name": {"type": "string", "description": "Thread name."},
                        "message_id": {"type": "string", "description": "Message ID to create thread from (optional)."},
                        "auto_archive": {"type": "integer", "description": "Auto-archive in minutes (60/1440/4320/10080)."},
                    },
                    "required": ["guild_id", "channel_id", "name"],
                },
                risk_level="low",
            ),
            ToolDefinition(
                name="discord.threads.archive",
                description="Archive a thread (can be unarchived later).",
                parameters={
                    "type": "object",
                    "properties": {
                        "guild_id": {"type": "string", "description": "Target guild ID."},
                        "thread_id": {"type": "string", "description": "Thread ID to archive."},
                    },
                    "required": ["guild_id", "thread_id"],
                },
                risk_level="low",
            ),
            ToolDefinition(
                name="discord.threads.delete",
                description="Delete a thread. Irreversible.",
                parameters={
                    "type": "object",
                    "properties": {
                        "guild_id": {"type": "string", "description": "Target guild ID."},
                        "thread_id": {"type": "string", "description": "Thread ID to delete."},
                    },
                    "required": ["guild_id", "thread_id"],
                },
                risk_level="medium",
            ),
        ]

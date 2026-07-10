"""Discord Events Connector — kwargs pattern. Actions: create, edit, delete, list"""

from __future__ import annotations
import logging
from datetime import datetime
from typing import Any, Dict
import nextcord
from app.connectors.base import BaseConnector

logger = logging.getLogger(__name__)

_ENTITY_TYPE_MAP = {
    1: nextcord.ScheduledEventEntityType.stage_instance,
    2: nextcord.ScheduledEventEntityType.voice,
    3: nextcord.ScheduledEventEntityType.external,
}


class EventsConnector(BaseConnector):
    def __init__(self, bot: nextcord.Bot) -> None:
        self._bot = bot

    async def execute(self, action: str, guild: nextcord.Guild, **kwargs) -> Dict[str, Any]:
        actions = {"create": self.create, "edit": self.edit, "delete": self.delete, "list": self.list}
        handler = actions.get(action)
        if handler is None:
            raise ValueError(f"Unknown action '{action}'")
        return await handler(guild, **kwargs)

    async def create(self, guild: nextcord.Guild, name: str, entity_type: int, scheduled_start_time: str, **kwargs) -> Dict[str, Any]:
        """Create scheduled event. kwargs: channel_id, location, description, scheduled_end_time, image"""
        entity_enum = _ENTITY_TYPE_MAP.get(int(entity_type))
        if entity_enum is None:
            raise ValueError(f"Invalid entity_type {entity_type}. Valid: {list(_ENTITY_TYPE_MAP.keys())}")

        start_time = datetime.fromisoformat(scheduled_start_time)

        # Validation for EXTERNAL events
        if int(entity_type) == 3:
            if "location" not in kwargs:
                raise ValueError("EXTERNAL events require 'location'")
            if "scheduled_end_time" not in kwargs:
                raise ValueError("EXTERNAL events require 'scheduled_end_time'")

        params: Dict[str, Any] = {
            "name": name,
            "entity_type": entity_enum,
            "scheduled_start_time": start_time,
        }

        # Channel for VOICE/STAGE
        if int(entity_type) in (1, 2):
            channel_id = kwargs.pop("channel_id", None)
            if channel_id is None:
                raise ValueError("VOICE/STAGE events require 'channel_id'")
            channel = guild.get_channel(int(channel_id))
            if channel is None:
                raise ValueError(f"Channel '{channel_id}' not found")
            params["channel"] = channel

        # Optional params
        if "description" in kwargs:
            params["description"] = kwargs.pop("description")
        if "scheduled_end_time" in kwargs:
            params["scheduled_end_time"] = datetime.fromisoformat(kwargs.pop("scheduled_end_time"))
        if "location" in kwargs:
            params["entity_metadata"] = nextcord.EntityMetadata(location=kwargs.pop("location"))
        if "image" in kwargs:
            params["image"] = kwargs.pop("image")

        try:
            event = await guild.create_scheduled_event(**params)
            logger.info("Created scheduled event '%s' (id=%s)", name, event.id)
            return {
                "id": str(event.id),
                "name": event.name,
                "entity_type": str(event.entity_type),
                "start_time": event.scheduled_start_time.isoformat(),
                "status": str(event.status),
            }
        except nextcord.Forbidden:
            raise PermissionError("manage_events")
        except nextcord.HTTPException as exc:
            raise RuntimeError(f"Failed: {exc}")

    async def edit(self, guild: nextcord.Guild, event_id: int, **kwargs) -> Dict[str, Any]:
        """Edit scheduled event. kwargs: name, description, scheduled_start_time, scheduled_end_time, status, location, channel_id"""
        try:
            event = await guild.fetch_scheduled_event(int(event_id))
        except nextcord.NotFound:
            raise ValueError(f"Event '{event_id}' not found")
        except nextcord.Forbidden:
            raise PermissionError("manage_events")

        params: Dict[str, Any] = {}

        if "name" in kwargs:
            params["name"] = kwargs.pop("name")
        if "description" in kwargs:
            params["description"] = kwargs.pop("description")
        if "scheduled_start_time" in kwargs:
            params["scheduled_start_time"] = datetime.fromisoformat(kwargs.pop("scheduled_start_time"))
        if "scheduled_end_time" in kwargs:
            params["scheduled_end_time"] = datetime.fromisoformat(kwargs.pop("scheduled_end_time"))
        if "status" in kwargs:
            params["status"] = nextcord.ScheduledEventStatus(int(kwargs.pop("status")))
        if "location" in kwargs:
            params["entity_metadata"] = nextcord.EntityMetadata(location=kwargs.pop("location"))
        if "channel_id" in kwargs:
            channel = guild.get_channel(int(kwargs.pop("channel_id")))
            if channel is None:
                raise ValueError("Channel not found")
            params["channel"] = channel

        try:
            edited = await event.edit(**params)
            logger.info("Edited scheduled event '%s' (id=%s)", edited.name, edited.id)
            return {
                "id": str(edited.id),
                "name": edited.name,
                "entity_type": str(edited.entity_type),
                "start_time": edited.scheduled_start_time.isoformat(),
                "status": str(edited.status),
            }
        except nextcord.Forbidden:
            raise PermissionError("manage_events")
        except nextcord.HTTPException as exc:
            raise RuntimeError(f"Failed: {exc}")

    async def delete(self, guild: nextcord.Guild, event_id: int, **kwargs) -> Dict[str, Any]:
        """Delete a scheduled event."""
        try:
            event = await guild.fetch_scheduled_event(int(event_id))
        except nextcord.NotFound:
            raise ValueError(f"Event '{event_id}' not found")
        except nextcord.Forbidden:
            raise PermissionError("manage_events")

        name = event.name
        try:
            await event.delete()
            return {"deleted": True, "id": str(event_id), "name": name}
        except nextcord.Forbidden:
            raise PermissionError("manage_events")
        except nextcord.HTTPException as exc:
            raise RuntimeError(f"Failed: {exc}")

    async def list(self, guild: nextcord.Guild, **kwargs) -> Dict[str, Any]:
        """List all scheduled events."""
        try:
            events = await guild.fetch_scheduled_events()
            return {
                "events": [
                    {
                        "id": str(e.id),
                        "name": e.name,
                        "entity_type": str(e.entity_type),
                        "start_time": e.scheduled_start_time.isoformat(),
                        "status": str(e.status),
                    }
                    for e in events
                ],
                "count": len(events),
            }
        except nextcord.Forbidden:
            raise PermissionError("manage_events")

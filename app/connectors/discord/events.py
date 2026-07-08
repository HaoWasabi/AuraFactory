"""Discord Events Connector — SPEC v2 new module (schema §10).

Scheduled Events management: create, edit, cancel, list.

Actions: create, edit, cancel, list
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Dict, Optional

import nextcord

from app.connectors.base import BaseConnector
from app.connectors.discord._helpers import download_image_bytes
from app.connectors.discord._permissions import check_bot_permissions
from app.connectors.discord._validation import validate_kwargs

logger = logging.getLogger(__name__)

# Entity type mapping
_ENTITY_TYPE_MAP = {
    "stage": nextcord.ScheduledEventEntityType.stage_instance,
    "voice": nextcord.ScheduledEventEntityType.voice,
    "external": nextcord.ScheduledEventEntityType.external,
}


class EventsConnector(BaseConnector):
    """Manages Discord Scheduled Events."""

    def __init__(self, bot: nextcord.Bot) -> None:
        self._bot = bot

    async def create(self, guild: nextcord.Guild, name: str, start_time: str, **kwargs) -> Dict[str, Any]:
        """Create a scheduled event.

        Required: name, start_time (ISO 8601)
        Optional: description, end_time, location, channel_id, entity_type, image_url
        """
        perm_error = check_bot_permissions(guild, "discord.events.create")
        if perm_error:
            raise PermissionError(perm_error)

        clean = validate_kwargs("discord.events.create", kwargs)

        # Parse start time
        try:
            start_dt = datetime.fromisoformat(start_time)
        except (ValueError, TypeError):
            raise ValueError(f"Invalid start_time format: '{start_time}'. Use ISO 8601.")

        # Parse end time
        end_dt = None
        if "end_time" in clean:
            try:
                end_dt = datetime.fromisoformat(clean.pop("end_time"))
            except (ValueError, TypeError):
                pass

        # Resolve entity type
        entity_type_str = clean.pop("entity_type", "external").lower().strip()
        entity_type = _ENTITY_TYPE_MAP.get(entity_type_str)
        if entity_type is None:
            entity_type = nextcord.ScheduledEventEntityType.external

        # Build creation kwargs
        create_kwargs: Dict[str, Any] = {
            "name": name,
            "scheduled_start_time": start_dt,
            "entity_type": entity_type,
        }

        if end_dt:
            create_kwargs["scheduled_end_time"] = end_dt

        if "description" in clean:
            create_kwargs["description"] = clean["description"]

        # External events need location + end_time
        if entity_type == nextcord.ScheduledEventEntityType.external:
            location = clean.get("location", "Online")
            create_kwargs["entity_metadata"] = nextcord.EntityMetadata(location=location)
            if not end_dt:
                raise ValueError("External events require an end_time.")

        # Voice/Stage events need channel_id
        if entity_type in (
            nextcord.ScheduledEventEntityType.stage_instance,
            nextcord.ScheduledEventEntityType.voice,
        ):
            channel_id = clean.get("channel_id")
            if not channel_id:
                raise ValueError(f"{entity_type_str} events require a channel_id.")
            channel = guild.get_channel(int(channel_id))
            if not channel:
                raise ValueError(f"Channel '{channel_id}' not found.")
            create_kwargs["channel"] = channel

        # Handle image
        if "image_url" in clean:
            img_bytes = await download_image_bytes(clean["image_url"])
            if img_bytes:
                create_kwargs["image"] = img_bytes

        try:
            event = await guild.create_scheduled_event(**create_kwargs)
            logger.info("Created event '%s' (id=%s) in guild '%s'", event.name, event.id, guild.name)
            return {
                "id": str(event.id),
                "name": event.name,
                "start_time": start_time,
                "entity_type": entity_type_str,
            }
        except nextcord.errors.Forbidden:
            raise PermissionError("Bot lacks 'Manage Events' permission.")
        except nextcord.errors.HTTPException as exc:
            raise RuntimeError(f"Failed to create event: {exc}")

    async def edit(self, guild: nextcord.Guild, event_id: int, **kwargs) -> Dict[str, Any]:
        """Edit a scheduled event.

        Optional: name, description, start_time, end_time, location, channel_id, entity_type, image_url, status
        """
        perm_error = check_bot_permissions(guild, "discord.events.edit")
        if perm_error:
            raise PermissionError(perm_error)

        clean = validate_kwargs("discord.events.edit", kwargs)

        try:
            event = await guild.fetch_scheduled_event(int(event_id))
        except nextcord.errors.NotFound:
            raise ValueError(f"Event '{event_id}' not found.")

        edit_kwargs: Dict[str, Any] = {}

        if "name" in clean:
            edit_kwargs["name"] = clean["name"]
        if "description" in clean:
            edit_kwargs["description"] = clean["description"]
        if "start_time" in clean:
            try:
                edit_kwargs["scheduled_start_time"] = datetime.fromisoformat(clean["start_time"])
            except ValueError:
                pass
        if "end_time" in clean:
            try:
                edit_kwargs["scheduled_end_time"] = datetime.fromisoformat(clean["end_time"])
            except ValueError:
                pass
        if "image_url" in clean:
            img_bytes = await download_image_bytes(clean["image_url"])
            if img_bytes:
                edit_kwargs["image"] = img_bytes

        if not edit_kwargs:
            raise ValueError("No valid edit parameters provided for this event.")

        try:
            await event.edit(**edit_kwargs)
            logger.info("Edited event '%s' (id=%s)", event.name, event_id)
            return {"id": str(event_id), "updated_fields": list(edit_kwargs.keys())}
        except nextcord.errors.Forbidden:
            raise PermissionError("Bot lacks 'Manage Events' permission.")
        except nextcord.errors.HTTPException as exc:
            raise RuntimeError(f"Failed to edit event: {exc}")

    async def cancel(self, guild: nextcord.Guild, event_id: int, **kwargs) -> Dict[str, Any]:
        """Cancel (delete) a scheduled event."""
        perm_error = check_bot_permissions(guild, "discord.events.cancel")
        if perm_error:
            raise PermissionError(perm_error)

        try:
            event = await guild.fetch_scheduled_event(int(event_id))
            name = event.name
            await event.delete()
            logger.info("Cancelled event '%s' (id=%s)", name, event_id)
            return {"id": str(event_id), "name": name, "cancelled": True}
        except nextcord.errors.NotFound:
            raise ValueError(f"Event '{event_id}' not found.")
        except nextcord.errors.Forbidden:
            raise PermissionError("Bot lacks 'Manage Events' permission.")
        except nextcord.errors.HTTPException as exc:
            raise RuntimeError(f"Failed to cancel event: {exc}")

    async def list(self, guild: nextcord.Guild, **kwargs) -> Dict[str, Any]:
        """List all scheduled events in the guild."""
        try:
            events = await guild.fetch_scheduled_events()
            result = []
            for event in events:
                result.append({
                    "id": str(event.id),
                    "name": event.name,
                    "status": str(event.status),
                    "start_time": event.scheduled_start_time.isoformat() if event.scheduled_start_time else None,
                    "end_time": event.scheduled_end_time.isoformat() if event.scheduled_end_time else None,
                    "entity_type": str(event.entity_type),
                })
            return {"events": result, "count": len(result)}
        except nextcord.errors.HTTPException as exc:
            raise RuntimeError(f"Failed to list events: {exc}")

"""Discord Templates Connector — kwargs pattern. Actions: create, sync, delete"""

from __future__ import annotations
import logging
from typing import Any, Dict
import nextcord
from app.connectors.base import BaseConnector

logger = logging.getLogger(__name__)


class TemplatesConnector(BaseConnector):
    def __init__(self, bot: nextcord.Bot) -> None:
        self._bot = bot

    async def execute(self, action: str, guild: nextcord.Guild, **kwargs) -> Dict[str, Any]:
        actions = {"create": self.create, "sync": self.sync, "delete": self.delete}
        handler = actions.get(action)
        if handler is None:
            raise ValueError(f"Unknown action '{action}'")
        return await handler(guild, **kwargs)

    async def create(self, guild: nextcord.Guild, name: str, **kwargs) -> Dict[str, Any]:
        """Create guild template. kwargs: description"""
        description = kwargs.pop("description", None)
        try:
            template = await guild.create_template(name=name, description=description)
            return {"code": template.code, "name": template.name}
        except nextcord.Forbidden:
            raise PermissionError("manage_guild")
        except nextcord.HTTPException as exc:
            raise RuntimeError(f"Failed: {exc}")

    async def sync(self, guild: nextcord.Guild, template_code: str, **kwargs) -> Dict[str, Any]:
        """Sync template with current guild state."""
        try:
            templates = await guild.templates()
            template = next((t for t in templates if t.code == template_code), None)
            if template is None:
                raise ValueError(f"Template '{template_code}' not found")
            await template.sync()
            return {"synced": True, "code": template_code}
        except nextcord.Forbidden:
            raise PermissionError("manage_guild")

    async def delete(self, guild: nextcord.Guild, template_code: str, **kwargs) -> Dict[str, Any]:
        """Delete a guild template."""
        try:
            templates = await guild.templates()
            template = next((t for t in templates if t.code == template_code), None)
            if template is None:
                raise ValueError(f"Template '{template_code}' not found")
            await template.delete()
            return {"deleted": True, "code": template_code}
        except nextcord.Forbidden:
            raise PermissionError("manage_guild")

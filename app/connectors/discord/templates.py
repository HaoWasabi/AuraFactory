"""
Discord Templates Connector — Guild template management.

Actions: create, apply
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

import nextcord

from app.connectors.base import BaseConnector
from app.mcp.protocol import ToolDefinition
from app.connectors.discord._permissions import check_bot_permissions
from app.connectors.discord._validation import validate_kwargs

logger = logging.getLogger(__name__)


class TemplatesConnector(BaseConnector):
    """Manages Discord guild templates."""

    def __init__(self, bot: nextcord.Bot) -> None:
        self._bot = bot

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------

    async def create(
        self,
        guild: nextcord.Guild,
        name: str,
        description: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Create a guild template (snapshot of current structure).

        Args:
            guild: The target guild.
            name: Template name.
            description: Optional template description.

        Returns:
            Dict with template info.
        """
        if not name or not name.strip():
            raise ValueError("Template name cannot be empty")

        try:
            template = await guild.create_template(
                name=name,
                description=description or "",
            )
            logger.info(
                "Created template '%s' (code=%s) for guild '%s'",
                name,
                template.code,
                guild.name,
            )
            return {
                "code": template.code,
                "name": template.name,
                "description": template.description,
                "usage_count": template.usage_count,
                "creator_id": str(template.creator.id) if template.creator else None,
                "source_guild_id": str(guild.id),
            }
        except nextcord.errors.Forbidden:
            raise PermissionError("manage_guild")
        except nextcord.errors.HTTPException as exc:
            raise RuntimeError(f"Failed to create template: {exc}")

    async def apply(
        self,
        guild: nextcord.Guild,
        template_code: str,
    ) -> Dict[str, Any]:
        """Apply a template to the guild.

        WARNING: This is a CRITICAL operation. Applying a template restructures
        the guild. This fetches the template and recreates its structure.

        Args:
            guild: The target guild.
            template_code: The template code to apply.

        Returns:
            Dict with the result.
        """
        if not template_code or not template_code.strip():
            raise ValueError("Template code cannot be empty")

        try:
            # Fetch the template
            template = await self._bot.fetch_template(template_code)

            # Note: Discord API doesn't directly "apply" a template to an existing guild.
            # We replicate the template's structure by creating channels/roles.
            # This is an additive operation.
            results = {
                "template_name": template.name,
                "template_code": template_code,
                "roles_created": 0,
                "channels_created": 0,
                "applied": True,
            }

            # Recreate roles from template
            if hasattr(template, "serialized_source_guild"):
                source = template.serialized_source_guild
                for role_data in source.get("roles", []):
                    try:
                        await guild.create_role(
                            name=role_data.get("name", "New Role"),
                            color=nextcord.Color(role_data.get("color", 0)),
                            permissions=nextcord.Permissions(role_data.get("permissions", 0)),
                        )
                        results["roles_created"] += 1
                    except Exception:
                        pass

                for ch_data in source.get("channels", []):
                    try:
                        ch_type = ch_data.get("type", 0)
                        if ch_type == 4:  # Category
                            await guild.create_category(name=ch_data.get("name", "Category"))
                        elif ch_type == 2:  # Voice
                            await guild.create_voice_channel(name=ch_data.get("name", "Voice"))
                        else:  # Text
                            await guild.create_text_channel(name=ch_data.get("name", "channel"))
                        results["channels_created"] += 1
                    except Exception:
                        pass

            logger.info(
                "Applied template '%s' to guild '%s': %d roles, %d channels",
                template.name,
                guild.name,
                results["roles_created"],
                results["channels_created"],
            )
            return results

        except nextcord.errors.NotFound:
            raise ValueError(f"Template '{template_code}' not found")
        except nextcord.errors.Forbidden:
            raise PermissionError("administrator")
        except nextcord.errors.HTTPException as exc:
            raise RuntimeError(f"Failed to apply template: {exc}")

    # ------------------------------------------------------------------
    # BaseConnector interface
    # ------------------------------------------------------------------

    async def execute(self, action: str, **params: Any) -> Dict[str, Any]:
        """Dispatch to the appropriate action method."""
        actions = {
            "create": self.create,
            "apply": self.apply,
        }
        handler = actions.get(action)
        if handler is None:
            raise ValueError(
                f"Unknown action '{action}' for TemplatesConnector. "
                f"Available: {list(actions.keys())}"
            )
        return await handler(**params)

    def get_tool_definitions(self) -> List[ToolDefinition]:
        """Return tool definitions for template operations."""
        return [
            ToolDefinition(
                name="discord.templates.create",
                description="Create a guild template (snapshot of structure).",
                parameters={
                    "type": "object",
                    "properties": {
                        "guild_id": {"type": "string", "description": "Target guild ID."},
                        "name": {"type": "string", "description": "Template name."},
                        "description": {"type": "string", "description": "Template description (optional)."},
                    },
                    "required": ["guild_id", "name"],
                },
                risk_level="medium",
            ),
            ToolDefinition(
                name="discord.templates.apply",
                description="Apply a template to the guild. CRITICAL: restructures the guild additively.",
                parameters={
                    "type": "object",
                    "properties": {
                        "guild_id": {"type": "string", "description": "Target guild ID."},
                        "template_code": {"type": "string", "description": "Template code to apply."},
                    },
                    "required": ["guild_id", "template_code"],
                },
                risk_level="critical",
            ),
        ]

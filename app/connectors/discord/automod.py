"""
Discord AutoMod Connector — Auto-moderation rule management.

Actions: create_rule, delete_rule, list_rules
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List

import nextcord

from app.connectors.base import BaseConnector
from app.mcp.protocol import ToolDefinition

logger = logging.getLogger(__name__)


class AutomodConnector(BaseConnector):
    """Manages Discord guild auto-moderation rules."""

    def __init__(self, bot: nextcord.Bot) -> None:
        self._bot = bot

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------

    async def create_rule(
        self,
        guild: nextcord.Guild,
        name: str,
        trigger_type: int,
        actions: List[dict],
        **kwargs: Any,
    ) -> Dict[str, Any]:
        """Create an auto-moderation rule.

        Args:
            guild: The target guild.
            name: Rule name.
            trigger_type: Trigger type (1=keyword, 3=spam, 4=keyword_preset, 5=mention_spam).
            actions: List of action dicts (type, channel_id, duration_seconds, custom_message).
            **kwargs: Additional settings (trigger_metadata, exempt_roles, exempt_channels, enabled).

        Returns:
            Dict with created rule info.
        """
        if not name or not name.strip():
            raise ValueError("Rule name cannot be empty")
        if not actions:
            raise ValueError("At least one action is required")

        try:
            # Build automod action objects
            automod_actions = []
            for action_data in actions:
                action_type = action_data.get("type", 1)
                if action_type == 1:  # Block message
                    automod_actions.append(
                        nextcord.AutoModerationAction(
                            type=nextcord.AutoModerationActionType.block_message,
                            custom_message=action_data.get("custom_message"),
                        )
                    )
                elif action_type == 2:  # Send alert
                    automod_actions.append(
                        nextcord.AutoModerationAction(
                            type=nextcord.AutoModerationActionType.send_alert_message,
                            channel_id=int(action_data["channel_id"]),
                        )
                    )
                elif action_type == 3:  # Timeout
                    automod_actions.append(
                        nextcord.AutoModerationAction(
                            type=nextcord.AutoModerationActionType.timeout,
                            duration=action_data.get("duration_seconds", 60),
                        )
                    )

            # Build trigger metadata
            trigger_metadata = kwargs.get("trigger_metadata", {})

            # Map trigger_type int to enum
            trigger_type_map = {
                1: nextcord.AutoModerationTriggerType.keyword,
                3: nextcord.AutoModerationTriggerType.spam,
                4: nextcord.AutoModerationTriggerType.keyword_preset,
                5: nextcord.AutoModerationTriggerType.mention_spam,
            }
            trigger_enum = trigger_type_map.get(trigger_type)
            if trigger_enum is None:
                raise ValueError(f"Invalid trigger_type: {trigger_type}. Valid: {list(trigger_type_map.keys())}")

            rule = await guild.create_automod_rule(
                name=name,
                event_type=nextcord.AutoModerationEventType.message_send,
                trigger_type=trigger_enum,
                trigger_metadata=trigger_metadata if trigger_metadata else None,
                actions=automod_actions,
                enabled=kwargs.get("enabled", True),
                exempt_roles=[
                    guild.get_role(int(r)) for r in kwargs.get("exempt_roles", [])
                    if guild.get_role(int(r))
                ] or None,
                exempt_channels=[
                    guild.get_channel(int(c)) for c in kwargs.get("exempt_channels", [])
                    if guild.get_channel(int(c))
                ] or None,
            )

            logger.info(
                "Created automod rule '%s' (id=%s) in guild '%s'",
                name,
                rule.id,
                guild.name,
            )
            return {
                "id": str(rule.id),
                "name": rule.name,
                "trigger_type": trigger_type,
                "enabled": rule.enabled,
            }
        except nextcord.errors.Forbidden:
            raise PermissionError("manage_guild")
        except nextcord.errors.HTTPException as exc:
            raise RuntimeError(f"Failed to create automod rule: {exc}")

    async def delete_rule(
        self,
        guild: nextcord.Guild,
        rule_id: int,
    ) -> Dict[str, Any]:
        """Delete an auto-moderation rule.

        Args:
            guild: The target guild.
            rule_id: ID of the rule to delete.

        Returns:
            Dict confirming deletion.
        """
        try:
            rules = await guild.fetch_automod_rules()
            target_rule = None
            for rule in rules:
                if rule.id == int(rule_id):
                    target_rule = rule
                    break

            if target_rule is None:
                raise ValueError(f"AutoMod rule '{rule_id}' not found in guild")

            name = target_rule.name
            await target_rule.delete()
            logger.info("Deleted automod rule '%s' (id=%s) from guild '%s'", name, rule_id, guild.name)
            return {"deleted": True, "rule_id": str(rule_id), "name": name}
        except nextcord.errors.Forbidden:
            raise PermissionError("manage_guild")
        except nextcord.errors.HTTPException as exc:
            raise RuntimeError(f"Failed to delete automod rule: {exc}")

    async def list_rules(
        self,
        guild: nextcord.Guild,
    ) -> Dict[str, Any]:
        """List all auto-moderation rules in the guild.

        Args:
            guild: The target guild.

        Returns:
            Dict with rule list.
        """
        try:
            rules = await guild.fetch_automod_rules()
            result = []
            for rule in rules:
                result.append({
                    "id": str(rule.id),
                    "name": rule.name,
                    "enabled": rule.enabled,
                    "trigger_type": str(rule.trigger_type),
                    "creator_id": str(rule.creator_id) if rule.creator_id else None,
                })
            return {"rules": result, "count": len(result)}
        except nextcord.errors.Forbidden:
            raise PermissionError("manage_guild")
        except nextcord.errors.HTTPException as exc:
            raise RuntimeError(f"Failed to list automod rules: {exc}")

    # ------------------------------------------------------------------
    # BaseConnector interface
    # ------------------------------------------------------------------

    async def execute(self, action: str, **params: Any) -> Dict[str, Any]:
        """Dispatch to the appropriate action method."""
        actions = {
            "create_rule": self.create_rule,
            "delete_rule": self.delete_rule,
            "list_rules": self.list_rules,
        }
        handler = actions.get(action)
        if handler is None:
            raise ValueError(
                f"Unknown action '{action}' for AutomodConnector. "
                f"Available: {list(actions.keys())}"
            )
        return await handler(**params)

    def get_tool_definitions(self) -> List[ToolDefinition]:
        """Return tool definitions for automod operations."""
        return [
            ToolDefinition(
                name="discord.automod.create_rule",
                description="Create an auto-moderation rule (keyword filter, spam, etc.).",
                parameters={
                    "type": "object",
                    "properties": {
                        "guild_id": {"type": "string", "description": "Target guild ID."},
                        "name": {"type": "string", "description": "Rule name."},
                        "trigger_type": {
                            "type": "integer",
                            "description": "Trigger type (1=keyword, 3=spam, 4=keyword_preset, 5=mention_spam).",
                        },
                        "actions": {
                            "type": "array",
                            "description": "List of action dicts (type, channel_id, duration_seconds).",
                        },
                    },
                    "required": ["guild_id", "name", "trigger_type", "actions"],
                    "additionalProperties": True,
                },
                risk_level="high",
            ),
            ToolDefinition(
                name="discord.automod.delete_rule",
                description="Delete an auto-moderation rule.",
                parameters={
                    "type": "object",
                    "properties": {
                        "guild_id": {"type": "string", "description": "Target guild ID."},
                        "rule_id": {"type": "string", "description": "Rule ID to delete."},
                    },
                    "required": ["guild_id", "rule_id"],
                },
                risk_level="high",
            ),
            ToolDefinition(
                name="discord.automod.list_rules",
                description="List all auto-moderation rules in the guild.",
                parameters={
                    "type": "object",
                    "properties": {
                        "guild_id": {"type": "string", "description": "Target guild ID."},
                    },
                    "required": ["guild_id"],
                },
                risk_level="low",
            ),
        ]

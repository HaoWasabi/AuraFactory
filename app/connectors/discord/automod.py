"""Discord AutoMod Connector — kwargs pattern. Actions: create_rule, delete_rule, list_rules"""

from __future__ import annotations
import logging
from typing import Any, Dict, List
import nextcord
from app.connectors.base import BaseConnector

logger = logging.getLogger(__name__)

_TRIGGER_MAP = {
    1: nextcord.AutoModerationTriggerType.keyword,
    3: nextcord.AutoModerationTriggerType.spam,
    4: nextcord.AutoModerationTriggerType.keyword_preset,
    5: nextcord.AutoModerationTriggerType.mention_spam,
}


class AutomodConnector(BaseConnector):
    def __init__(self, bot: nextcord.Bot) -> None:
        self._bot = bot

    async def execute(self, action: str, guild: nextcord.Guild, **kwargs) -> Dict[str, Any]:
        actions = {"create_rule": self.create_rule, "delete_rule": self.delete_rule, "list_rules": self.list_rules}
        handler = actions.get(action)
        if handler is None:
            raise ValueError(f"Unknown action '{action}'")
        return await handler(guild, **kwargs)

    async def create_rule(self, guild: nextcord.Guild, name: str, trigger_type: int, actions: List[dict], **kwargs) -> Dict[str, Any]:
        """Create automod rule. kwargs: trigger_metadata, exempt_role_ids, exempt_channel_ids, enabled"""
        trigger_enum = _TRIGGER_MAP.get(trigger_type)
        if trigger_enum is None:
            raise ValueError(f"Invalid trigger_type {trigger_type}. Valid: {list(_TRIGGER_MAP.keys())}")

        # Build actions
        automod_actions = []
        for a in actions:
            a_type = a.get("type", 1)
            if a_type == 1:
                automod_actions.append(nextcord.AutoModerationAction(
                    type=nextcord.AutoModerationActionType.block_message,
                    custom_message=a.get("custom_message"),
                ))
            elif a_type == 2:
                automod_actions.append(nextcord.AutoModerationAction(
                    type=nextcord.AutoModerationActionType.send_alert_message,
                    channel_id=int(a["channel_id"]),
                ))
            elif a_type == 3:
                automod_actions.append(nextcord.AutoModerationAction(
                    type=nextcord.AutoModerationActionType.timeout,
                    duration=a.get("duration_seconds", 60),
                ))

        trigger_metadata = kwargs.pop("trigger_metadata", None)
        exempt_roles = [guild.get_role(int(r)) for r in kwargs.pop("exempt_role_ids", []) if guild.get_role(int(r))] or None
        exempt_channels = [guild.get_channel(int(c)) for c in kwargs.pop("exempt_channel_ids", []) if guild.get_channel(int(c))] or None
        enabled = kwargs.pop("enabled", True)

        try:
            rule = await guild.create_automod_rule(
                name=name,
                event_type=nextcord.AutoModerationEventType.message_send,
                trigger_type=trigger_enum,
                trigger_metadata=trigger_metadata,
                actions=automod_actions,
                enabled=enabled,
                exempt_roles=exempt_roles,
                exempt_channels=exempt_channels,
            )
            logger.info("Created automod rule '%s' (id=%s)", name, rule.id)
            return {"id": str(rule.id), "name": rule.name, "enabled": rule.enabled}
        except nextcord.Forbidden:
            raise PermissionError("manage_guild")
        except nextcord.HTTPException as exc:
            raise RuntimeError(f"Failed: {exc}")

    async def delete_rule(self, guild: nextcord.Guild, rule_id: int, **kwargs) -> Dict[str, Any]:
        """Delete automod rule."""
        try:
            rules = await guild.fetch_automod_rules()
            target = next((r for r in rules if r.id == int(rule_id)), None)
            if target is None:
                raise ValueError(f"Rule '{rule_id}' not found")
            name = target.name
            await target.delete()
            return {"deleted": True, "id": str(rule_id), "name": name}
        except nextcord.Forbidden:
            raise PermissionError("manage_guild")

    async def list_rules(self, guild: nextcord.Guild, **kwargs) -> Dict[str, Any]:
        """List all automod rules."""
        try:
            rules = await guild.fetch_automod_rules()
            return {
                "rules": [{"id": str(r.id), "name": r.name, "enabled": r.enabled, "trigger_type": str(r.trigger_type)} for r in rules],
                "count": len(rules),
            }
        except nextcord.Forbidden:
            raise PermissionError("manage_guild")

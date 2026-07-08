"""Discord Safety Connector — SPEC v2 new module.

Covers schema §5: Safety Setup (Content Filter, Raid Protection, MFA, AutoMod).

Actions: set_content_filter, set_raid_protection, set_mfa, automod_preset
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

import nextcord

from app.connectors.base import BaseConnector
from app.connectors.discord._permissions import check_bot_permissions
from app.connectors.discord._validation import (
    check_owner_only,
    validate_kwargs,
)

logger = logging.getLogger(__name__)

# Enum mappings
_CONTENT_FILTER_MAP = {
    "disabled": nextcord.ContentFilter.disabled,
    "no_role": nextcord.ContentFilter.no_role,
    "all_members": nextcord.ContentFilter.all_members,
}


class SafetyConnector(BaseConnector):
    """Manages Discord server safety settings."""

    def __init__(self, bot: nextcord.Bot) -> None:
        self._bot = bot

    async def set_content_filter(self, guild: nextcord.Guild, level: str, **kwargs) -> Dict[str, Any]:
        """Set the explicit content filter level.

        Args:
            level: One of 'disabled', 'no_role', 'all_members'
        """
        perm_error = check_bot_permissions(guild, "discord.safety.set_content_filter")
        if perm_error:
            raise PermissionError(perm_error)

        flt = _CONTENT_FILTER_MAP.get(level.lower().strip())
        if flt is None:
            raise ValueError(
                f"Invalid content filter level '{level}'. "
                f"Valid: {list(_CONTENT_FILTER_MAP.keys())}"
            )

        old_level = str(guild.explicit_content_filter)

        try:
            await guild.edit(explicit_content_filter=flt)
        except nextcord.errors.Forbidden:
            raise PermissionError("Bot lacks 'Manage Guild' permission.")
        except nextcord.errors.HTTPException as exc:
            raise RuntimeError(f"Failed to set content filter: {exc}")

        logger.info(
            "Content filter '%s' -> '%s' for guild '%s'",
            old_level, level, guild.name,
        )
        return {
            "guild_id": str(guild.id),
            "old_level": old_level,
            "new_level": level.lower().strip(),
        }

    async def set_raid_protection(self, guild: nextcord.Guild, **kwargs) -> Dict[str, Any]:
        """Configure raid protection (DM/invite pause).

        Optional kwargs: invites_disabled (bool), dms_disabled_until (ISO datetime str or None)

        Note: Uses PUT /guilds/{id}/incident-actions endpoint.
        This is a newer Discord API — may not be available in all nextcord versions.
        """
        perm_error = check_bot_permissions(guild, "discord.safety.set_raid_protection")
        if perm_error:
            raise PermissionError(perm_error)

        clean = validate_kwargs("discord.safety.set_raid_protection", kwargs)

        # This endpoint is relatively new — attempt via HTTP adapter if nextcord
        # doesn't expose it natively
        payload: Dict[str, Any] = {}
        if "invites_disabled" in clean:
            payload["invites_disabled_until"] = (
                None if not clean["invites_disabled"]
                else "2099-12-31T23:59:59Z"  # Discord uses future timestamp to enable
            )
        if "dms_disabled_until" in clean:
            payload["dms_disabled_until"] = clean["dms_disabled_until"]

        if not payload:
            raise ValueError("Provide at least one of: invites_disabled, dms_disabled_until")

        try:
            # Attempt via guild.edit if supported, otherwise use HTTP directly
            await guild._state.http.request(
                nextcord.http.Route("PUT", "/guilds/{guild_id}/incident-actions", guild_id=guild.id),
                json=payload,
            )
        except AttributeError:
            # Fallback: not supported in this nextcord version
            raise RuntimeError(
                "Raid protection endpoint not available in current nextcord version. "
                "Update nextcord or use raw HTTP client."
            )
        except nextcord.errors.Forbidden:
            raise PermissionError("Bot lacks 'Manage Guild' permission.")
        except nextcord.errors.HTTPException as exc:
            raise RuntimeError(f"Failed to set raid protection: {exc}")

        logger.info("Raid protection updated for guild '%s': %s", guild.name, payload)
        return {"guild_id": str(guild.id), "updated": payload}

    async def set_mfa(self, guild: nextcord.Guild, level: int, user_id: int = 0, **kwargs) -> Dict[str, Any]:
        """Set the MFA (2FA) requirement for server moderation.

        CRITICAL action — owner-only.

        Args:
            level: 0 (disabled) or 1 (required for moderator actions)
            user_id: The user requesting this (must be server owner)
        """
        perm_error = check_bot_permissions(guild, "discord.safety.set_mfa")
        if perm_error:
            raise PermissionError(perm_error)

        # Owner-only check
        owner_error = check_owner_only(guild, user_id)
        if owner_error:
            raise PermissionError(owner_error)

        if level not in (0, 1):
            raise ValueError("MFA level must be 0 (disabled) or 1 (required)")

        try:
            await guild.edit(mfa_level=level)
        except nextcord.errors.Forbidden:
            raise PermissionError(
                "Cannot set MFA level — this action requires the server owner's token. "
                "Bot tokens cannot change MFA settings."
            )
        except nextcord.errors.HTTPException as exc:
            raise RuntimeError(f"Failed to set MFA level: {exc}")

        logger.info("MFA level set to %d for guild '%s'", level, guild.name)
        return {"guild_id": str(guild.id), "mfa_level": level}

    async def automod_preset(self, guild: nextcord.Guild, preset_type: str, enabled: bool = True, **kwargs) -> Dict[str, Any]:
        """Configure AutoMod preset rules.

        Uses Discord AutoMod API (trigger_type = 4 for keyword_preset).

        Args:
            preset_type: One of 'profanity', 'sexual_content', 'slurs'
            enabled: Whether to enable or disable this preset
        Optional: exempt_role_ids, exempt_channel_ids
        """
        perm_error = check_bot_permissions(guild, "discord.safety.automod_preset")
        if perm_error:
            raise PermissionError(perm_error)

        clean = validate_kwargs("discord.safety.automod_preset", kwargs)

        # Preset type mapping
        preset_map = {
            "profanity": 1,
            "sexual_content": 2,
            "slurs": 3,
        }
        preset_value = preset_map.get(preset_type.lower().strip())
        if preset_value is None:
            raise ValueError(
                f"Invalid preset_type '{preset_type}'. Valid: {list(preset_map.keys())}"
            )

        # Build AutoMod rule payload
        rule_payload = {
            "name": f"AutoMod Preset: {preset_type}",
            "event_type": 1,  # MESSAGE_SEND
            "trigger_type": 4,  # KEYWORD_PRESET
            "trigger_metadata": {
                "presets": [preset_value],
            },
            "actions": [
                {"type": 1},  # BLOCK_MESSAGE
            ],
            "enabled": enabled,
        }

        # Add exemptions
        exempt_role_ids = clean.get("exempt_role_ids")
        exempt_channel_ids = clean.get("exempt_channel_ids")
        if exempt_role_ids:
            rule_payload["exempt_roles"] = [str(r) for r in exempt_role_ids]
        if exempt_channel_ids:
            rule_payload["exempt_channels"] = [str(c) for c in exempt_channel_ids]

        try:
            # Check if a rule with this preset already exists
            existing_rules = await guild.fetch_automod_rules()
            existing_rule = None
            for rule in existing_rules:
                if (
                    rule.trigger.type.value == 4
                    and preset_value in getattr(rule.trigger, "presets", [])
                ):
                    existing_rule = rule
                    break

            if existing_rule:
                # Update existing rule
                await existing_rule.edit(enabled=enabled)
                action = "updated"
            else:
                # Create new rule
                await guild._state.http.request(
                    nextcord.http.Route("POST", "/guilds/{guild_id}/auto-moderation/rules", guild_id=guild.id),
                    json=rule_payload,
                )
                action = "created"

        except nextcord.errors.Forbidden:
            raise PermissionError("Bot lacks 'Manage Guild' permission for AutoMod.")
        except nextcord.errors.HTTPException as exc:
            raise RuntimeError(f"Failed to configure AutoMod preset: {exc}")

        logger.info(
            "AutoMod preset '%s' %s (enabled=%s) for guild '%s'",
            preset_type, action, enabled, guild.name,
        )
        return {
            "guild_id": str(guild.id),
            "preset_type": preset_type,
            "enabled": enabled,
            "action": action,
        }

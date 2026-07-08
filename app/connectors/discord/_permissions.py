"""Bot permission check helpers — SPEC v2 §2 Layer 1.

Provides check_bot_permissions() to verify the bot has required Discord
permissions BEFORE calling any API endpoint.

Layer 1: Bot-level permission check (does the bot have manage_channels, etc.)
Layer 2: Application-level auth (handled by auth_service.py — is the user Owner/Admin?)
"""

import logging
from typing import Optional

import nextcord

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Map of tool actions → required bot permissions
# ---------------------------------------------------------------------------

TOOL_PERMISSIONS: dict = {
    # Channels
    "discord.channels.create": ["manage_channels"],
    "discord.channels.edit": ["manage_channels"],
    "discord.channels.delete": ["manage_channels"],
    "discord.channels.move": ["manage_channels"],
    "discord.channels.list": [],
    # Categories
    "discord.categories.create": ["manage_channels"],
    "discord.categories.edit": ["manage_channels"],
    "discord.categories.delete": ["manage_channels"],
    "discord.categories.sync": ["manage_channels", "manage_roles"],
    "discord.categories.list": [],
    # Roles
    "discord.roles.create": ["manage_roles"],
    "discord.roles.modify": ["manage_roles"],
    "discord.roles.delete": ["manage_roles"],
    "discord.roles.assign": ["manage_roles"],
    "discord.roles.batch_assign": ["manage_roles"],
    "discord.roles.clone": ["manage_roles"],
    "discord.roles.set_position": ["manage_roles"],
    "discord.roles.get_info": [],
    "discord.roles.list": [],
    # Members / Moderation
    "discord.members.kick": ["kick_members"],
    "discord.members.ban": ["ban_members"],
    "discord.members.unban": ["ban_members"],
    "discord.members.bulk_ban": ["ban_members"],
    "discord.members.timeout": ["moderate_members"],
    "discord.members.purge": ["manage_messages"],
    "discord.members.get_info": [],
    # Guild
    "discord.guild.get_info": [],
    "discord.guild.edit_profile": ["manage_guild"],
    "discord.guild.set_verification": ["manage_guild"],
    "discord.guild.delete_server": [],  # owner-only — perms irrelevant
    # Safety
    "discord.safety.set_content_filter": ["manage_guild"],
    "discord.safety.set_raid_protection": ["manage_guild"],
    "discord.safety.set_mfa": ["manage_guild"],
    "discord.safety.automod_preset": ["manage_guild"],
    # Engagement
    "discord.engagement.set_system_channels": ["manage_guild"],
    "discord.engagement.set_afk": ["manage_guild"],
    "discord.engagement.set_widget": ["manage_guild"],
    "discord.engagement.set_notifications": ["manage_guild"],
    # Community
    "discord.community.toggle": ["manage_guild"],
    # Integrations
    "discord.integrations.list": ["manage_guild"],
    "discord.integrations.remove": ["manage_guild"],
    # Audit
    "discord.audit.query": ["view_audit_log"],
    # Webhooks
    "discord.webhooks.create": ["manage_webhooks"],
    "discord.webhooks.delete": ["manage_webhooks"],
    "discord.webhooks.list": ["manage_webhooks"],
    # Templates
    "discord.templates.create": ["manage_guild"],
    "discord.templates.sync": ["manage_guild"],
    "discord.templates.delete": ["manage_guild"],
    "discord.templates.list": ["manage_guild"],
    # Stickers
    "discord.stickers.upload": ["manage_emojis_and_stickers"],
    "discord.stickers.edit": ["manage_emojis_and_stickers"],
    "discord.stickers.delete": ["manage_emojis_and_stickers"],
    "discord.stickers.list": [],
    # Soundboard
    "discord.soundboard.upload": ["manage_guild"],
    "discord.soundboard.edit": ["manage_guild"],
    "discord.soundboard.delete": ["manage_guild"],
    # Events
    "discord.events.create": ["manage_events"],
    "discord.events.edit": ["manage_events"],
    "discord.events.cancel": ["manage_events"],
    "discord.events.list": [],
    # Backup
    "discord.backup.export": ["administrator"],
    "discord.backup.restore": ["administrator"],
    # Bot Features
    "discord.features.setup_verification": ["manage_roles", "send_messages", "add_reactions"],
    "discord.features.create_poll": ["send_messages", "add_reactions"],
    "discord.features.setup_welcome": ["send_messages"],
    "discord.features.configure_auto_delete": ["manage_messages"],
}

# ---------------------------------------------------------------------------
# Risk Level Map
# ---------------------------------------------------------------------------

RISK_LEVELS: dict = {
    # LOW — auto-execute
    "discord.guild.get_info": "LOW",
    "discord.channels.list": "LOW",
    "discord.categories.list": "LOW",
    "discord.roles.list": "LOW",
    "discord.roles.get_info": "LOW",
    "discord.members.get_info": "LOW",
    "discord.audit.query": "LOW",
    "discord.integrations.list": "LOW",
    "discord.templates.list": "LOW",
    "discord.events.list": "LOW",
    "discord.stickers.list": "LOW",
    "discord.webhooks.list": "LOW",
    "discord.backup.export": "LOW",
    "discord.engagement.set_system_channels": "LOW",
    "discord.engagement.set_afk": "LOW",
    "discord.engagement.set_widget": "LOW",
    "discord.engagement.set_notifications": "LOW",
    "discord.stickers.upload": "LOW",
    "discord.stickers.edit": "LOW",
    "discord.stickers.delete": "LOW",
    "discord.soundboard.upload": "LOW",
    "discord.soundboard.edit": "LOW",
    "discord.soundboard.delete": "LOW",
    "discord.templates.create": "LOW",
    "discord.features.setup_verification": "LOW",
    "discord.features.create_poll": "LOW",
    "discord.features.setup_welcome": "LOW",
    "discord.features.configure_auto_delete": "LOW",
    # MEDIUM — simple confirm
    "discord.channels.create": "MEDIUM",
    "discord.channels.edit": "MEDIUM",
    "discord.channels.move": "MEDIUM",
    "discord.categories.create": "MEDIUM",
    "discord.categories.edit": "MEDIUM",
    "discord.categories.sync": "MEDIUM",
    "discord.roles.create": "MEDIUM",
    "discord.roles.modify": "MEDIUM",
    "discord.roles.assign": "MEDIUM",
    "discord.roles.batch_assign": "MEDIUM",
    "discord.roles.clone": "MEDIUM",
    "discord.roles.set_position": "MEDIUM",
    "discord.guild.edit_profile": "MEDIUM",
    "discord.events.create": "MEDIUM",
    "discord.events.edit": "MEDIUM",
    "discord.webhooks.create": "MEDIUM",
    "discord.templates.sync": "MEDIUM",
    "discord.backup.restore": "MEDIUM",
    # HIGH — approval required
    "discord.channels.delete": "HIGH",
    "discord.categories.delete": "HIGH",
    "discord.roles.delete": "HIGH",
    "discord.members.kick": "HIGH",
    "discord.members.unban": "HIGH",
    "discord.webhooks.delete": "HIGH",
    "discord.templates.delete": "HIGH",
    "discord.integrations.remove": "HIGH",
    "discord.guild.set_verification": "HIGH",
    "discord.safety.set_content_filter": "HIGH",
    "discord.safety.set_raid_protection": "HIGH",
    "discord.safety.automod_preset": "HIGH",
    "discord.community.toggle": "HIGH",
    "discord.events.cancel": "HIGH",
    "discord.members.timeout": "HIGH",
    # CRITICAL — double-confirm + irreversible warning
    "discord.members.ban": "CRITICAL",
    "discord.members.bulk_ban": "CRITICAL",
    "discord.members.purge": "CRITICAL",
    "discord.safety.set_mfa": "CRITICAL",
    "discord.guild.delete_server": "CRITICAL",
}


# ---------------------------------------------------------------------------
# Permission Check Function
# ---------------------------------------------------------------------------

def check_bot_permissions(
    guild: nextcord.Guild,
    tool_name: str,
    channel: Optional[nextcord.abc.GuildChannel] = None,
) -> Optional[str]:
    """Check if the bot has required permissions for the given tool.

    Args:
        guild: The Discord guild
        tool_name: Dotted tool identifier (e.g. "discord.channels.create")
        channel: Optional specific channel (for channel-level perm checks)

    Returns:
        Error message string if permissions are missing, else None (all OK).
    """
    required = TOOL_PERMISSIONS.get(tool_name, [])
    if not required:
        return None  # No perms needed (read-only)

    # Check at guild level by default, channel level if provided
    bot_perms = guild.me.guild_permissions
    if channel is not None:
        bot_perms = channel.permissions_for(guild.me)

    missing = []
    for perm_name in required:
        if not getattr(bot_perms, perm_name, False):
            missing.append(perm_name)

    if missing:
        friendly_names = [p.replace("_", " ").title() for p in missing]
        return f"Bot is missing required permissions: {', '.join(friendly_names)}"

    return None


def get_risk_level(tool_name: str) -> str:
    """Get the risk level for a tool. Defaults to MEDIUM if not mapped."""
    return RISK_LEVELS.get(tool_name, "MEDIUM")

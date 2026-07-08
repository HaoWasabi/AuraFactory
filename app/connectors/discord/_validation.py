"""Validation layer for Discord connector tools — SPEC v2 §1.

Provides PARAM_WHITELIST and validate_kwargs() to enforce guard rails
before spreading **kwargs into Nextcord API calls.
"""

import logging
from typing import Any, Dict, List, Optional, Set

import nextcord

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Parameter Whitelist: {tool_name: {context_key: [allowed_params]}}
# "_common" applies regardless of context (channel_type, action, etc.)
# ---------------------------------------------------------------------------

PARAM_WHITELIST: Dict[str, Dict[str, List[str]]] = {
    "discord.channels.create": {
        "_common": [
            "category_id", "position", "is_private", "allowed_role_ids",
            "allowed_user_ids", "advanced_permissions", "reason",
        ],
        "text": ["topic", "slowmode_delay", "nsfw"],
        "voice": ["bitrate", "user_limit", "rtc_region"],
        "stage": ["topic"],
        "forum": ["topic", "slowmode_delay", "default_auto_archive_duration"],
        "announcement": ["topic"],
        "news": ["topic"],
    },
    "discord.channels.edit": {
        "_common": [
            "name", "position", "sync_permissions", "update_permissions",
            "reason", "category_id",
        ],
        "text": ["topic", "slowmode_delay", "nsfw"],
        "voice": ["bitrate", "user_limit", "rtc_region"],
        "stage": ["topic"],
        "forum": ["topic", "slowmode_delay", "default_auto_archive_duration"],
        "announcement": ["topic"],
        "news": ["topic"],
    },
    "discord.channels.delete": {
        "_common": ["reason"],
    },
    "discord.channels.move": {
        "_common": ["category_id", "position", "sync_permissions"],
    },
    "discord.categories.create": {
        "_common": [
            "position", "is_private", "allowed_role_ids",
            "allowed_user_ids", "advanced_permissions", "reason",
        ],
    },
    "discord.categories.edit": {
        "_common": ["name", "position", "update_permissions", "reason"],
    },
    "discord.categories.delete": {
        "_common": ["reason"],
    },
    "discord.categories.sync": {
        "_common": [],
    },
    "discord.roles.create": {
        "_common": ["color", "hoist", "mentionable", "permissions", "position", "reason"],
    },
    "discord.roles.modify": {
        "_common": ["name", "color", "hoist", "mentionable", "permissions", "position", "reason"],
    },
    "discord.roles.delete": {
        "_common": ["reason"],
    },
    "discord.roles.assign": {
        "_common": [],
    },
    "discord.roles.batch_assign": {
        "_common": ["member_ids", "action"],
    },
    "discord.roles.clone": {
        "_common": ["new_name"],
    },
    "discord.roles.set_position": {
        "_common": ["position"],
    },
    "discord.guild.edit_profile": {
        "_common": [
            "name", "description", "icon_url", "banner_url",
            "splash_url", "discovery_splash_url", "tags",
            "verification_level", "explicit_content_filter", "preferred_locale",
        ],
    },
    "discord.guild.set_verification": {
        "_common": ["level"],
    },
    "discord.safety.set_content_filter": {
        "_common": ["level"],
    },
    "discord.safety.set_raid_protection": {
        "_common": ["invites_disabled", "dms_disabled_until"],
    },
    "discord.safety.set_mfa": {
        "_common": ["level"],
    },
    "discord.safety.automod_preset": {
        "_common": ["preset_type", "enabled", "exempt_role_ids", "exempt_channel_ids"],
    },
    "discord.engagement.set_system_channels": {
        "_common": [
            "system_channel_id", "suppress_join_notifications",
            "suppress_premium_subscriptions",
            "suppress_guild_reminder_notifications",
            "suppress_join_notification_replies",
        ],
    },
    "discord.engagement.set_afk": {
        "_common": ["afk_channel_id", "afk_timeout"],
    },
    "discord.engagement.set_widget": {
        "_common": ["widget_enabled", "widget_channel_id"],
    },
    "discord.engagement.set_notifications": {
        "_common": ["level"],
    },
    "discord.community.toggle": {
        "_common": ["enable", "rules_channel_id", "public_updates_channel_id"],
    },
    "discord.members.kick": {
        "_common": ["reason"],
    },
    "discord.members.ban": {
        "_common": ["delete_message_seconds", "reason"],
    },
    "discord.members.unban": {
        "_common": ["reason"],
    },
    "discord.members.bulk_ban": {
        "_common": ["member_ids", "delete_message_seconds", "reason"],
    },
    "discord.members.timeout": {
        "_common": ["duration_minutes", "reason"],
    },
    "discord.members.purge": {
        "_common": ["limit", "member_id"],
    },
    "discord.webhooks.create": {
        "_common": ["avatar_url", "reason"],
    },
    "discord.webhooks.delete": {
        "_common": ["reason"],
    },
    "discord.stickers.upload": {
        "_common": ["name", "description", "tags", "file_url"],
    },
    "discord.stickers.edit": {
        "_common": ["name", "description", "tags"],
    },
    "discord.stickers.delete": {
        "_common": ["reason"],
    },
    "discord.soundboard.upload": {
        "_common": ["name", "sound_url", "emoji_name", "emoji_id", "volume"],
    },
    "discord.soundboard.edit": {
        "_common": ["name", "emoji_name", "emoji_id", "volume"],
    },
    "discord.soundboard.delete": {
        "_common": [],
    },
    "discord.events.create": {
        "_common": [
            "name", "description", "start_time", "end_time",
            "location", "channel_id", "entity_type", "image_url",
        ],
    },
    "discord.events.edit": {
        "_common": [
            "name", "description", "start_time", "end_time",
            "location", "channel_id", "entity_type", "image_url", "status",
        ],
    },
    "discord.events.cancel": {
        "_common": [],
    },
    "discord.templates.create": {
        "_common": ["name", "description"],
    },
    "discord.templates.sync": {
        "_common": [],
    },
    "discord.templates.delete": {
        "_common": [],
    },
    "discord.audit.query": {
        "_common": ["action_type", "user_id", "limit", "before"],
    },
    "discord.backup.export": {
        "_common": [],
    },
    "discord.backup.restore": {
        "_common": ["backup_data"],
    },
    "discord.features.setup_verification": {
        "_common": ["channel_id", "role_id", "emoji", "title", "description"],
    },
    "discord.features.create_poll": {
        "_common": ["channel_id", "question", "options"],
    },
    "discord.features.setup_welcome": {
        "_common": ["channel_id", "welcome_title", "welcome_message_template"],
    },
    "discord.features.configure_auto_delete": {
        "_common": ["channel_id", "delay_seconds"],
    },
}

# AFK timeout must be one of these values (Discord constraint)
VALID_AFK_TIMEOUTS = {60, 300, 900, 1800, 3600}

# Sticker quota by boost level
STICKER_QUOTA = {0: 5, 1: 15, 2: 30, 3: 60}

# Soundboard quota by boost level
SOUNDBOARD_QUOTA = {0: 8, 1: 24, 2: 36, 3: 48}


# ---------------------------------------------------------------------------
# Core Validation Function
# ---------------------------------------------------------------------------

def validate_kwargs(
    tool_name: str,
    kwargs: Dict[str, Any],
    context: Optional[str] = None,
) -> Dict[str, Any]:
    """Filter kwargs to only whitelisted params for the given tool + context.

    Invalid params are logged as warnings and silently dropped — LLM may
    hallucinate extra fields and this should not be a hard error.

    Args:
        tool_name: Dotted tool identifier (e.g. "discord.channels.create")
        kwargs: Raw kwargs from LLM-generated plan
        context: Sub-context key (e.g. channel_type "text", "voice")

    Returns:
        Cleaned kwargs dict with only valid params.
    """
    whitelist_entry = PARAM_WHITELIST.get(tool_name)
    if whitelist_entry is None:
        # No whitelist defined — pass through (read-only tools, etc.)
        logger.debug("No whitelist for tool '%s' — passing all kwargs", tool_name)
        return kwargs

    # Build allowed set: _common + context-specific
    allowed: Set[str] = set(whitelist_entry.get("_common", []))
    if context:
        ctx_key = context.lower().strip()
        allowed.update(whitelist_entry.get(ctx_key, []))

    # Filter
    clean = {}
    dropped = []
    for key, val in kwargs.items():
        if key in allowed:
            clean[key] = val
        else:
            dropped.append(key)

    if dropped:
        logger.warning(
            "[Validation] Tool '%s' (ctx=%s): dropped invalid params: %s",
            tool_name, context, dropped,
        )

    return clean


# ---------------------------------------------------------------------------
# Precondition Checks
# ---------------------------------------------------------------------------

def check_community_required(guild: nextcord.Guild) -> Optional[str]:
    """Returns error message if Community is not enabled, else None."""
    if "COMMUNITY" not in guild.features:
        return "Server must have Community feature enabled for this action."
    return None


def check_boost_level(guild: nextcord.Guild, required_level: int) -> Optional[str]:
    """Returns error message if boost tier is insufficient."""
    if guild.premium_tier < required_level:
        return (
            f"Server requires Boost Level {required_level}+ "
            f"(current: Level {guild.premium_tier})."
        )
    return None


def check_sticker_quota(guild: nextcord.Guild) -> Optional[str]:
    """Returns error message if sticker slots are full."""
    max_slots = STICKER_QUOTA.get(guild.premium_tier, 5)
    if len(guild.stickers) >= max_slots:
        return (
            f"Sticker quota full ({len(guild.stickers)}/{max_slots}). "
            "Upgrade boost tier or delete existing stickers."
        )
    return None


def check_soundboard_quota(guild: nextcord.Guild) -> Optional[str]:
    """Returns error message if soundboard slots are full."""
    max_slots = SOUNDBOARD_QUOTA.get(guild.premium_tier, 8)
    # Note: guild.soundboard_sounds may not exist in all nextcord versions
    current = len(getattr(guild, "soundboard_sounds", []))
    if current >= max_slots:
        return (
            f"Soundboard quota full ({current}/{max_slots}). "
            "Upgrade boost tier or delete existing sounds."
        )
    return None


def check_afk_timeout(timeout: int) -> Optional[str]:
    """Returns error message if AFK timeout value is invalid."""
    if timeout not in VALID_AFK_TIMEOUTS:
        return (
            f"Invalid AFK timeout: {timeout}s. "
            f"Must be one of: {sorted(VALID_AFK_TIMEOUTS)}"
        )
    return None


def check_afk_channel_is_voice(guild: nextcord.Guild, channel_id: int) -> Optional[str]:
    """Returns error message if the specified channel is not a VoiceChannel."""
    channel = guild.get_channel(channel_id)
    if channel is None:
        return f"Channel ID {channel_id} not found in this server."
    if not isinstance(channel, nextcord.VoiceChannel):
        return (
            f"AFK channel must be a Voice Channel. "
            f"'{channel.name}' is a {type(channel).__name__}."
        )
    return None


def check_role_hierarchy(guild: nextcord.Guild, target) -> Optional[str]:
    """Returns error message if bot cannot manage this role/member due to hierarchy."""
    if hasattr(target, "top_role"):
        # It's a member
        if target.top_role >= guild.me.top_role:
            return (
                "Cannot manage this member — their highest role is "
                "equal to or above the bot's highest role."
            )
        if target.id == guild.owner_id:
            return "Cannot manage the server owner."
    elif isinstance(target, nextcord.Role):
        if target >= guild.me.top_role:
            return (
                "Cannot manage this role — it is equal to or above "
                "the bot's highest role."
            )
        if target.is_default():
            return "Cannot delete the @everyone role."
    return None


def check_community_prerequisites(guild: nextcord.Guild) -> List[str]:
    """Returns list of unmet prerequisites for enabling Community."""
    issues = []
    if guild.verification_level.value < nextcord.VerificationLevel.medium.value:
        issues.append(
            f"verification_level must be >= medium "
            f"(currently: {guild.verification_level})"
        )
    if guild.explicit_content_filter != nextcord.ContentFilter.all_members:
        issues.append(
            f"explicit_content_filter must be 'all_members' "
            f"(currently: {guild.explicit_content_filter})"
        )
    if not guild.text_channels:
        issues.append("Server must have at least 1 text channel for rules/updates")
    return issues


def check_owner_only(guild: nextcord.Guild, user_id: int) -> Optional[str]:
    """Returns error message if user is not the server owner."""
    if user_id != guild.owner_id:
        return "Only the server owner can perform this action."
    return None

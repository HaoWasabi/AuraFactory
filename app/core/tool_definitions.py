"""Tool definitions, name mappings, and risk levels for the Unified Agent.

This is the single source of truth for:
- TOOL_DEFINITIONS: Schema sent to LLM for function calling
- TOOL_NAME_MAP: LLM function name → MCP tool name
- HIGH_RISK_TOOLS: Tools requiring user confirmation before execution

Edit here to add/modify tools — no business logic to worry about.
"""

# ═══════════════════════════════════════════════════════════════════════════
# Tool Definitions (sent to LLM as available functions)
# ═══════════════════════════════════════════════════════════════════════════

TOOL_DEFINITIONS = [
    {
        "name": "create_channel",
        "description": "Create a new Discord channel (text, voice, stage, forum, news).",
        "parameters": {
            "properties": {
                "name": {"type": "string", "description": "Channel name (lowercase, hyphens)"},
                "type": {"type": "string", "description": "Channel type: text, voice, stage, forum, news"},
                "category_id": {"type": "string", "description": "Parent category ID"},
                "topic": {"type": "string", "description": "Channel topic (text only)"},
                "is_private": {"type": "boolean", "description": "Hide from @everyone"},
                "allowed_role_ids": {"type": "array", "items": {"type": "string"}, "description": "Roles for private access"},
                "slowmode_delay": {"type": "integer", "description": "Slowmode seconds (0-21600)"},
                "nsfw": {"type": "boolean", "description": "Age-restricted"},
                "user_limit": {"type": "integer", "description": "Max voice users (0=unlimited)"},
                "bitrate": {"type": "integer", "description": "Voice bitrate bps (8000-384000)"},
            },
            "required": ["name", "type"],
        },
    },
    {
        "name": "edit_channel",
        "description": "Edit channel properties (name, topic, slowmode, permissions).",
        "parameters": {
            "properties": {
                "channel_id": {"type": "string", "description": "Channel ID to edit"},
                "name": {"type": "string", "description": "New name"},
                "topic": {"type": "string", "description": "New topic"},
                "slowmode_delay": {"type": "integer"},
                "nsfw": {"type": "boolean"},
                "category_id": {"type": "string", "description": "Move to category"},
                "sync_permissions": {"type": "boolean"},
            },
            "required": ["channel_id"],
        },
    },
    {
        "name": "delete_channel",
        "description": "Delete a channel permanently. IRREVERSIBLE.",
        "parameters": {
            "properties": {
                "channel_id": {"type": "string", "description": "Channel to delete"},
                "reason": {"type": "string", "description": "Audit reason"},
            },
            "required": ["channel_id"],
        },
    },
    {
        "name": "create_category",
        "description": "Create a new category to organize channels.",
        "parameters": {
            "properties": {
                "name": {"type": "string", "description": "Category name"},
                "position": {"type": "integer"},
                "is_private": {"type": "boolean"},
                "allowed_role_ids": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["name"],
        },
    },
    {
        "name": "delete_category",
        "description": "Delete a category. Channels inside become uncategorized. IRREVERSIBLE.",
        "parameters": {
            "properties": {
                "category_id": {"type": "string", "description": "Category to delete"},
                "reason": {"type": "string"},
            },
            "required": ["category_id"],
        },
    },
    {
        "name": "create_role",
        "description": "Create a new role with color and permissions.",
        "parameters": {
            "properties": {
                "name": {"type": "string", "description": "Role name"},
                "color": {"type": "string", "description": "Hex color (#FF5733)"},
                "hoist": {"type": "boolean", "description": "Show separately"},
                "mentionable": {"type": "boolean"},
                "permissions": {"type": "object", "description": "{perm: true/false}"},
            },
            "required": ["name"],
        },
    },
    {
        "name": "delete_role",
        "description": "Delete a role. IRREVERSIBLE.",
        "parameters": {
            "properties": {
                "role_id": {"type": "string", "description": "Role to delete"},
                "reason": {"type": "string"},
            },
            "required": ["role_id"],
        },
    },
    {
        "name": "edit_role",
        "description": "Edit role name, color, permissions, or display.",
        "parameters": {
            "properties": {
                "role_id": {"type": "string", "description": "Role to edit"},
                "name": {"type": "string"},
                "color": {"type": "string"},
                "hoist": {"type": "boolean"},
                "mentionable": {"type": "boolean"},
                "permissions": {"type": "object"},
            },
            "required": ["role_id"],
        },
    },
    {
        "name": "assign_role",
        "description": "Assign a role to a member.",
        "parameters": {
            "properties": {
                "role_id": {"type": "string", "description": "Role to assign"},
                "member_id": {"type": "string", "description": "Member to receive role"},
            },
            "required": ["role_id", "member_id"],
        },
    },
    {
        "name": "kick_member",
        "description": "Kick a member from the server. They can rejoin via invite.",
        "parameters": {
            "properties": {
                "member_id": {"type": "string", "description": "Member to kick"},
                "reason": {"type": "string"},
            },
            "required": ["member_id"],
        },
    },
    {
        "name": "ban_member",
        "description": "Ban a member. They cannot rejoin unless unbanned.",
        "parameters": {
            "properties": {
                "member_id": {"type": "string", "description": "Member to ban"},
                "reason": {"type": "string"},
                "delete_message_seconds": {"type": "integer", "description": "Delete messages from last N seconds (max 604800)"},
            },
            "required": ["member_id"],
        },
    },
    {
        "name": "timeout_member",
        "description": "Timeout a member (disable communication temporarily).",
        "parameters": {
            "properties": {
                "member_id": {"type": "string", "description": "Member to timeout"},
                "duration_minutes": {"type": "integer", "description": "Duration 1-40320 (max 28 days)"},
                "reason": {"type": "string"},
            },
            "required": ["member_id", "duration_minutes"],
        },
    },
    {
        "name": "setup_verification",
        "description": "Set up reaction-based role verification in a channel.",
        "parameters": {
            "properties": {
                "channel_id": {"type": "string", "description": "Channel for verification"},
                "role_id": {"type": "string", "description": "Role to assign on verify"},
                "emoji": {"type": "string", "description": "Reaction emoji (default: ✅)"},
                "title": {"type": "string"},
                "description": {"type": "string"},
            },
            "required": ["channel_id", "role_id"],
        },
    },
    {
        "name": "create_poll",
        "description": "Create a reaction-based poll in a channel.",
        "parameters": {
            "properties": {
                "channel_id": {"type": "string", "description": "Channel for poll"},
                "question": {"type": "string", "description": "Poll question"},
                "options": {"type": "array", "items": {"type": "string"}, "description": "2-10 options"},
            },
            "required": ["channel_id", "question", "options"],
        },
    },
]


# ═══════════════════════════════════════════════════════════════════════════
# Tool Name Mapping (Gemini function name → MCP tool name)
# ═══════════════════════════════════════════════════════════════════════════

TOOL_NAME_MAP = {
    "create_channel": "discord.channels.create",
    "edit_channel": "discord.channels.edit",
    "delete_channel": "discord.channels.delete",
    "create_category": "discord.categories.create",
    "delete_category": "discord.categories.delete",
    "create_role": "discord.roles.create",
    "delete_role": "discord.roles.delete",
    "edit_role": "discord.roles.modify",
    "assign_role": "discord.roles.assign",
    "kick_member": "discord.members.kick",
    "ban_member": "discord.members.ban",
    "timeout_member": "discord.members.timeout",
    "setup_verification": "discord.features.setup_verification",
    "create_poll": "discord.features.create_poll",
}


# ═══════════════════════════════════════════════════════════════════════════
# High-Risk Tools (require user approval before execution)
# ═══════════════════════════════════════════════════════════════════════════

HIGH_RISK_TOOLS = {
    "discord.channels.delete",
    "discord.categories.delete",
    "discord.roles.delete",
    "discord.members.kick",
    "discord.members.ban",
    "discord.members.bulk_ban",
    "discord.members.timeout",
    "discord.backup.restore",
}

"""Base connector + shared helpers for Discord connectors.

All connectors inherit BaseConnector and use these helpers for
type coercion before spreading **kwargs into Nextcord API calls.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional

import nextcord

logger = logging.getLogger(__name__)


# ===========================================================================
# Shared Helpers (used across all connectors)
# ===========================================================================

def parse_color(color: Any) -> Optional[nextcord.Color]:
    """Normalize color input from LLM → nextcord.Color.

    Accepts: "#ff0000", "ff0000", 16711680, None
    """
    if color is None:
        return None
    if isinstance(color, str):
        return nextcord.Color(int(color.lstrip("#"), 16))
    if isinstance(color, int):
        return nextcord.Color(color)
    return None


def parse_permissions(perms_dict: Dict[str, bool]) -> nextcord.Permissions:
    """Convert {perm_name: bool} dict → nextcord.Permissions (set only True flags)."""
    perms = nextcord.Permissions.none()
    for name, value in perms_dict.items():
        if hasattr(perms, name) and isinstance(value, bool):
            setattr(perms, name, value)
    return perms


def merge_permissions(base: nextcord.Permissions, updates: Dict[str, bool]) -> nextcord.Permissions:
    """Merge updates onto existing permissions (preserves unmentioned flags)."""
    for name, value in updates.items():
        if hasattr(base, name) and isinstance(value, bool):
            setattr(base, name, value)
    return base


def permissions_to_dict(perms: nextcord.Permissions) -> Dict[str, bool]:
    """Extract only True permission flags as clean dict."""
    return {name: val for name, val in perms if val is True}


def build_overwrites(
    guild: nextcord.Guild,
    is_private: bool = False,
    allowed_role_ids: Optional[List[int]] = None,
    allowed_user_ids: Optional[List[int]] = None,
    advanced_permissions: Optional[Dict[str, bool]] = None,
) -> Optional[Dict[Any, nextcord.PermissionOverwrite]]:
    """Build permission overwrite map for channel/category creation.

    Logic:
      - is_private=True: hide from @everyone, grant view to listed roles/users
      - advanced_permissions: apply custom flags on top of view_channel
      - Neither set: return None (inherit defaults)
    """
    allowed_role_ids = allowed_role_ids or []
    allowed_user_ids = allowed_user_ids or []

    if not is_private and not advanced_permissions:
        return None

    overwrites: Dict[Any, nextcord.PermissionOverwrite] = {}

    # Build custom overwrite from advanced_permissions
    custom_ow = nextcord.PermissionOverwrite()
    if advanced_permissions:
        for perm, val in advanced_permissions.items():
            if hasattr(custom_ow, perm):
                setattr(custom_ow, perm, val)

    if is_private:
        # Hide from @everyone
        overwrites[guild.default_role] = nextcord.PermissionOverwrite(view_channel=False)

        # Grant access to allowed roles
        for r_id in allowed_role_ids:
            role = guild.get_role(int(r_id))
            if role:
                if advanced_permissions:
                    ow = nextcord.PermissionOverwrite(**{k: v for k, v in advanced_permissions.items() if hasattr(nextcord.PermissionOverwrite(), k)})
                    ow.view_channel = True
                    overwrites[role] = ow
                else:
                    overwrites[role] = nextcord.PermissionOverwrite(view_channel=True)

        # Grant access to allowed users
        for u_id in allowed_user_ids:
            member = guild.get_member(int(u_id))
            if member:
                if advanced_permissions:
                    ow = nextcord.PermissionOverwrite(**{k: v for k, v in advanced_permissions.items() if hasattr(nextcord.PermissionOverwrite(), k)})
                    ow.view_channel = True
                    overwrites[member] = ow
                else:
                    overwrites[member] = nextcord.PermissionOverwrite(view_channel=True)
    else:
        # Public channel with custom flags on @everyone
        overwrites[guild.default_role] = custom_ow

    # Bot always retains access
    overwrites[guild.me] = nextcord.PermissionOverwrite(
        view_channel=True, manage_channels=True
    )
    return overwrites


def role_to_dict(role: nextcord.Role) -> Dict[str, Any]:
    """Serialize role to JSON-safe dict."""
    return {
        "id": str(role.id),
        "name": role.name,
        "color": str(role.color),
        "color_value": role.color.value,
        "position": role.position,
        "hoist": role.hoist,
        "mentionable": role.mentionable,
        "managed": role.managed,
        "member_count": len(role.members),
        "permissions": permissions_to_dict(role.permissions),
    }


def channel_to_dict(channel: nextcord.abc.GuildChannel) -> Dict[str, Any]:
    """Serialize channel to JSON-safe dict."""
    import nextcord as _nc
    result = {
        "id": str(channel.id),
        "name": channel.name,
        "type": str(channel.type).split(".")[-1],
        "position": channel.position,
        "category_id": str(channel.category_id) if channel.category_id else None,
    }
    if hasattr(channel, "topic") and channel.topic:
        result["topic"] = channel.topic
    # Detect private: if @everyone role has explicit deny on view_channel
    try:
        everyone_role = channel.guild.default_role
        overwrites = channel.overwrites_for(everyone_role)
        result["is_private"] = overwrites.view_channel == False
    except Exception:
        result["is_private"] = False
    return result


# ===========================================================================
# Base Connector
# ===========================================================================

class BaseConnector(ABC):
    """Abstract base for all Discord connectors.

    Each connector exposes:
      - Action methods (create, edit, delete, list, etc.)
      - execute() dispatcher
      - get_actions() for discovery
    """

    @abstractmethod
    async def execute(self, action: str, guild: nextcord.Guild, **kwargs) -> Dict[str, Any]:
        """Dispatch to the appropriate action method."""
        ...

    def get_actions(self) -> List[str]:
        """Return list of supported action names."""
        return [
            name for name in dir(self)
            if not name.startswith("_")
            and name not in ("execute", "get_actions")
            and callable(getattr(self, name))
        ]

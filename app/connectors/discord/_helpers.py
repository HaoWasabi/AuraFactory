"""Shared helpers for Discord connectors — SPEC v2 §4.

Reusable utilities:
- download_image_bytes: Async image download from URL
- build_overwrites: Permission overwrite matrix builder
- RateLimitGate: Async rate limit pacer
- coerce_color: String/int → nextcord.Color
- coerce_permissions: Dict → nextcord.Permissions
- merge_permissions: Non-destructive permission update
"""

import asyncio
import logging
from typing import Any, Dict, List, Optional

import aiohttp
import nextcord

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Image Download
# ---------------------------------------------------------------------------

async def download_image_bytes(url: str, timeout: int = 15) -> Optional[bytes]:
    """Download image from URL and return raw bytes.

    Args:
        url: Image URL (must be accessible)
        timeout: Request timeout in seconds

    Returns:
        Image bytes on success, None on failure
    """
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                url, timeout=aiohttp.ClientTimeout(total=timeout)
            ) as response:
                if response.status == 200:
                    data = await response.read()
                    # Discord limit: 10MB for icons/banners
                    if len(data) > 10 * 1024 * 1024:
                        logger.warning(
                            "Image too large: %d bytes (max 10MB)", len(data)
                        )
                        return None
                    return data
                logger.warning(
                    "Image download failed: HTTP %d from %s", response.status, url
                )
    except asyncio.TimeoutError:
        logger.warning("Image download timed out: %s", url)
    except Exception as e:
        logger.warning("Image download error: %s", e)
    return None


# ---------------------------------------------------------------------------
# Permission Overwrite Builder
# ---------------------------------------------------------------------------

def build_overwrites(
    guild: nextcord.Guild,
    is_private: bool = False,
    allowed_role_ids: Optional[List] = None,
    allowed_user_ids: Optional[List] = None,
    advanced_permissions: Optional[Dict[str, bool]] = None,
) -> Optional[Dict[Any, nextcord.PermissionOverwrite]]:
    """Build permission overwrite matrix for channel/category creation.

    Args:
        guild: Discord guild object
        is_private: Whether to hide from @everyone
        allowed_role_ids: Role IDs that can see a private channel
        allowed_user_ids: User IDs that can see a private channel
        advanced_permissions: Custom perm flags applied on top

    Returns:
        Overwrite dict ready for Nextcord, or None if no overwrites needed.
    """
    allowed_role_ids = allowed_role_ids or []
    allowed_user_ids = allowed_user_ids or []

    if not is_private and not advanced_permissions:
        return None

    overwrites: Dict[Any, nextcord.PermissionOverwrite] = {}

    # Build custom overwrite from advanced_permissions
    custom_overwrite = nextcord.PermissionOverwrite()
    if advanced_permissions and isinstance(advanced_permissions, dict):
        for perm_name, value in advanced_permissions.items():
            if hasattr(custom_overwrite, perm_name):
                setattr(custom_overwrite, perm_name, value)

    if is_private:
        # Deny view for @everyone
        overwrites[guild.default_role] = nextcord.PermissionOverwrite(
            view_channel=False
        )

        # Allow view for specified roles
        for role_id in allowed_role_ids:
            role = guild.get_role(int(role_id)) if role_id else None
            if role:
                if advanced_permissions:
                    ow = nextcord.PermissionOverwrite(view_channel=True)
                    for perm_name, value in advanced_permissions.items():
                        if hasattr(ow, perm_name):
                            setattr(ow, perm_name, value)
                    overwrites[role] = ow
                else:
                    overwrites[role] = nextcord.PermissionOverwrite(view_channel=True)

        # Allow view for specified users
        for user_id in allowed_user_ids:
            member = guild.get_member(int(user_id)) if user_id else None
            if member:
                if advanced_permissions:
                    ow = nextcord.PermissionOverwrite(view_channel=True)
                    for perm_name, value in advanced_permissions.items():
                        if hasattr(ow, perm_name):
                            setattr(ow, perm_name, value)
                    overwrites[member] = ow
                else:
                    overwrites[member] = nextcord.PermissionOverwrite(view_channel=True)
    else:
        # Public channel with custom permissions for @everyone
        if advanced_permissions:
            overwrites[guild.default_role] = custom_overwrite

    # Always ensure bot retains management access
    overwrites[guild.me] = nextcord.PermissionOverwrite(
        view_channel=True, manage_channels=True
    )

    return overwrites


# ---------------------------------------------------------------------------
# Rate Limit Gate
# ---------------------------------------------------------------------------

class RateLimitGate:
    """Async rate limit pacer — sleeps every N API calls.

    Usage:
        gate = RateLimitGate(calls_per_batch=5, sleep_seconds=1.5)
        for item in items:
            await some_api_call(item)
            await gate.tick()
    """

    def __init__(self, calls_per_batch: int = 5, sleep_seconds: float = 1.5):
        self._counter = 0
        self._calls_per_batch = calls_per_batch
        self._sleep_seconds = sleep_seconds

    async def tick(self):
        """Call after each API request. Sleeps when batch threshold reached."""
        self._counter += 1
        if self._counter % self._calls_per_batch == 0:
            await asyncio.sleep(self._sleep_seconds)

    def reset(self):
        """Reset counter."""
        self._counter = 0


# ---------------------------------------------------------------------------
# Type Coercion Helpers
# ---------------------------------------------------------------------------

def coerce_color(value: Any) -> Optional[nextcord.Color]:
    """Convert string/int color to nextcord.Color.

    Accepts: "#ff0000", "ff0000", 0xff0000, 16711680
    Returns: nextcord.Color or None if invalid
    """
    if value is None:
        return None
    if isinstance(value, nextcord.Color):
        return value
    if isinstance(value, str):
        hex_str = value.lstrip("#")
        try:
            return nextcord.Color(int(hex_str, 16))
        except ValueError:
            logger.warning("Invalid color string: %s", value)
            return None
    if isinstance(value, int):
        return nextcord.Color(value)
    return None


def coerce_permissions(value: Any) -> Optional[nextcord.Permissions]:
    """Convert dict of {perm_name: bool} to nextcord.Permissions.

    Only sets explicitly provided permissions. Others default to False.
    """
    if not isinstance(value, dict):
        return None
    perms = nextcord.Permissions.none()
    for perm_name, perm_value in value.items():
        if hasattr(perms, perm_name) and isinstance(perm_value, bool):
            setattr(perms, perm_name, perm_value)
    return perms


def merge_permissions(
    existing: nextcord.Permissions,
    updates: Dict[str, bool],
) -> nextcord.Permissions:
    """Merge permission updates into existing permissions (non-destructive).

    Only changes keys present in updates — preserves all other permission bits.
    """
    for perm_name, perm_value in updates.items():
        if hasattr(existing, perm_name) and isinstance(perm_value, bool):
            setattr(existing, perm_name, perm_value)
    return existing

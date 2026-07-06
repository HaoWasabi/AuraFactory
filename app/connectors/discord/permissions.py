# app/tools/discord/permissions.py
"""
Discord Permission Management Tools.
Handles channel/category permission overwrites.
"""
from typing import Optional, Dict, Any
import nextcord


async def set_channel_permission(
    guild: nextcord.Guild,
    channel_name: str,
    target_name: str,
    target_type: str = "role",  # "role" | "member"
    allow: Optional[Dict[str, bool]] = None,
    deny: Optional[Dict[str, bool]] = None,
    reason: str = "AI Agent Request",
) -> Dict[str, Any]:
    """
    Set permission overwrite on a channel for a role or member.
    
    Args:
        channel_name: Name or ID of the channel
        target_name: Name of the role or member
        target_type: "role" or "member"
        allow: Dict of permission names to allow (e.g. {"send_messages": True})
        deny: Dict of permission names to deny (e.g. {"send_messages": True})
        reason: Audit log reason
    
    Returns:
        Dict with status and details
    """
    # Find channel
    channel = None
    for ch in guild.channels:
        if ch.name == channel_name or str(ch.id) == str(channel_name):
            channel = ch
            break
    
    if not channel:
        return {"success": False, "error": f"Channel '{channel_name}' not found"}

    # Find target
    target = None
    if target_type == "role":
        target = nextcord.utils.get(guild.roles, name=target_name)
        if not target:
            return {"success": False, "error": f"Role '{target_name}' not found"}
    elif target_type == "member":
        target = guild.get_member_named(target_name)
        if not target:
            # Try by ID
            try:
                target = await guild.fetch_member(int(target_name))
            except (ValueError, nextcord.NotFound):
                return {"success": False, "error": f"Member '{target_name}' not found"}

    # Build permission overwrite
    allow_perms = nextcord.PermissionOverwrite()
    deny_perms = nextcord.PermissionOverwrite()
    
    if allow:
        for perm_name, value in allow.items():
            if hasattr(allow_perms, perm_name):
                setattr(allow_perms, perm_name, True if value else None)
    
    if deny:
        for perm_name, value in deny.items():
            if hasattr(deny_perms, perm_name):
                setattr(deny_perms, perm_name, False if value else None)

    # Merge allow and deny into single overwrite
    overwrite = nextcord.PermissionOverwrite()
    if allow:
        for perm_name, value in allow.items():
            if hasattr(overwrite, perm_name) and value:
                setattr(overwrite, perm_name, True)
    if deny:
        for perm_name, value in deny.items():
            if hasattr(overwrite, perm_name) and value:
                setattr(overwrite, perm_name, False)

    await channel.set_permissions(target, overwrite=overwrite, reason=reason)

    return {
        "success": True,
        "channel": channel.name,
        "target": target_name,
        "target_type": target_type,
        "permissions_set": {"allow": allow or {}, "deny": deny or {}},
    }


async def sync_channel_permissions(
    guild: nextcord.Guild,
    channel_name: str,
    reason: str = "AI Agent Request",
) -> Dict[str, Any]:
    """
    Sync channel permissions with its parent category.
    """
    channel = None
    for ch in guild.channels:
        if ch.name == channel_name or str(ch.id) == str(channel_name):
            channel = ch
            break
    
    if not channel:
        return {"success": False, "error": f"Channel '{channel_name}' not found"}
    
    if not channel.category:
        return {"success": False, "error": f"Channel '{channel_name}' has no parent category"}

    await channel.edit(sync_permissions=True, reason=reason)

    return {
        "success": True,
        "channel": channel.name,
        "synced_with": channel.category.name,
    }


async def get_channel_permissions(
    guild: nextcord.Guild,
    channel_name: str,
) -> Dict[str, Any]:
    """
    Get current permission overwrites for a channel.
    """
    channel = None
    for ch in guild.channels:
        if ch.name == channel_name or str(ch.id) == str(channel_name):
            channel = ch
            break
    
    if not channel:
        return {"success": False, "error": f"Channel '{channel_name}' not found"}

    overwrites = []
    for target, overwrite in channel.overwrites.items():
        target_type = "role" if isinstance(target, nextcord.Role) else "member"
        allow, deny = overwrite.pair()
        overwrites.append({
            "target": target.name if hasattr(target, 'name') else str(target),
            "target_type": target_type,
            "allow": [perm for perm, value in allow if value],
            "deny": [perm for perm, value in deny if value],
        })

    return {
        "success": True,
        "channel": channel.name,
        "overwrites": overwrites,
    }

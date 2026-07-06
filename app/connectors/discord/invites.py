# app/tools/discord/invites.py
"""
Discord Invite Management Tools.
Create, list, revoke invite links.
"""
from typing import Optional, Dict, Any
import nextcord


async def create_invite(
    guild: nextcord.Guild,
    channel_name: Optional[str] = None,
    max_age: int = 86400,  # seconds (0 = never expire)
    max_uses: int = 0,  # 0 = unlimited
    temporary: bool = False,
    unique: bool = True,
    reason: str = "AI Agent Request",
) -> Dict[str, Any]:
    """
    Create an invite link.
    
    Args:
        channel_name: Channel for the invite (defaults to first text channel)
        max_age: Seconds until expiry (0 = never, 86400 = 24h, 604800 = 7 days)
        max_uses: Max number of uses (0 = unlimited)
        temporary: If True, member gets kicked when they go offline unless assigned a role
        unique: If True, creates a new unique invite each time
    """
    # Find channel
    channel = None
    if channel_name:
        for ch in guild.text_channels:
            if ch.name == channel_name or str(ch.id) == str(channel_name):
                channel = ch
                break
        if not channel:
            return {"success": False, "error": f"Channel '{channel_name}' not found"}
    else:
        # Default to first text channel
        channel = guild.text_channels[0] if guild.text_channels else None
        if not channel:
            return {"success": False, "error": "No text channels available"}

    try:
        invite = await channel.create_invite(
            max_age=max_age,
            max_uses=max_uses,
            temporary=temporary,
            unique=unique,
            reason=reason,
        )

        return {
            "success": True,
            "invite_url": str(invite),
            "invite_code": invite.code,
            "channel": channel.name,
            "max_age": max_age,
            "max_uses": max_uses,
            "temporary": temporary,
            "expires_at": str(invite.expires_at) if invite.expires_at else "Never",
        }
    except nextcord.Forbidden:
        return {"success": False, "error": "Bot lacks Create Invite permission"}
    except Exception as e:
        return {"success": False, "error": str(e)}


async def list_invites(guild: nextcord.Guild) -> Dict[str, Any]:
    """List all active invites in the guild."""
    try:
        invites = await guild.invites()
        invites_data = []
        for inv in invites:
            invites_data.append({
                "code": inv.code,
                "url": str(inv),
                "channel": inv.channel.name if inv.channel else None,
                "inviter": str(inv.inviter) if inv.inviter else None,
                "uses": inv.uses,
                "max_uses": inv.max_uses,
                "max_age": inv.max_age,
                "temporary": inv.temporary,
                "created_at": str(inv.created_at),
                "expires_at": str(inv.expires_at) if inv.expires_at else "Never",
            })
        
        return {"success": True, "invites": invites_data, "count": len(invites_data)}
    except nextcord.Forbidden:
        return {"success": False, "error": "Bot lacks Manage Server permission"}
    except Exception as e:
        return {"success": False, "error": str(e)}


async def revoke_invite(
    guild: nextcord.Guild,
    invite_code: str,
    reason: str = "AI Agent Request",
) -> Dict[str, Any]:
    """Revoke/delete an invite by code."""
    try:
        invites = await guild.invites()
        target = None
        for inv in invites:
            if inv.code == invite_code:
                target = inv
                break
        
        if not target:
            return {"success": False, "error": f"Invite '{invite_code}' not found"}

        await target.delete(reason=reason)
        return {"success": True, "revoked": invite_code}
    except nextcord.Forbidden:
        return {"success": False, "error": "Bot lacks Manage Server permission"}
    except Exception as e:
        return {"success": False, "error": str(e)}

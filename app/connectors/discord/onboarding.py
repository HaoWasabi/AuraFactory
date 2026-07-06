# app/tools/discord/onboarding.py
"""
Discord Onboarding & Welcome Management Tools.
Setup welcome screen, rules, onboarding prompts.
"""
from typing import Optional, Dict, Any, List
import nextcord


async def setup_welcome_screen(
    guild: nextcord.Guild,
    description: str,
    welcome_channels: Optional[List[Dict[str, str]]] = None,
    reason: str = "AI Agent Request",
) -> Dict[str, Any]:
    """
    Configure the Welcome Screen (requires Community enabled).
    
    Args:
        description: Welcome screen description text
        welcome_channels: List of {"channel_name": str, "description": str, "emoji": str}
    """
    try:
        # Build welcome channels
        channels = []
        if welcome_channels:
            for wc in welcome_channels:
                ch = nextcord.utils.get(guild.text_channels, name=wc.get("channel_name", ""))
                if ch:
                    channels.append(
                        nextcord.WelcomeChannel(
                            channel=ch,
                            description=wc.get("description", ""),
                            emoji=wc.get("emoji", "👋"),
                        )
                    )

        await guild.edit(
            welcome_screen=nextcord.WelcomeScreen(
                description=description,
                welcome_channels=channels,
            ),
            reason=reason,
        )

        return {
            "success": True,
            "description": description,
            "channels_configured": len(channels),
        }
    except nextcord.Forbidden:
        return {"success": False, "error": "Bot lacks Manage Server permission or Community not enabled"}
    except Exception as e:
        return {"success": False, "error": str(e)}


async def set_rules_channel(
    guild: nextcord.Guild,
    channel_name: str,
    reason: str = "AI Agent Request",
) -> Dict[str, Any]:
    """
    Set the rules/guidelines channel (Community feature).
    """
    channel = nextcord.utils.get(guild.text_channels, name=channel_name)
    if not channel:
        return {"success": False, "error": f"Channel '{channel_name}' not found"}

    try:
        await guild.edit(rules_channel=channel, reason=reason)
        return {"success": True, "rules_channel": channel.name}
    except Exception as e:
        return {"success": False, "error": str(e)}


async def set_system_channel(
    guild: nextcord.Guild,
    channel_name: str,
    join_notifications: bool = True,
    boost_notifications: bool = True,
    reason: str = "AI Agent Request",
) -> Dict[str, Any]:
    """
    Set system channel and configure notification types.
    """
    channel = nextcord.utils.get(guild.text_channels, name=channel_name)
    if not channel:
        return {"success": False, "error": f"Channel '{channel_name}' not found"}

    try:
        # Build system channel flags
        flags = nextcord.SystemChannelFlags()
        if not join_notifications:
            flags.join_notifications = True  # Suppress
        if not boost_notifications:
            flags.premium_subscriptions = True  # Suppress

        await guild.edit(
            system_channel=channel,
            system_channel_flags=flags,
            reason=reason,
        )
        return {
            "success": True,
            "system_channel": channel.name,
            "join_notifications": join_notifications,
            "boost_notifications": boost_notifications,
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


async def send_welcome_message(
    guild: nextcord.Guild,
    channel_name: str,
    title: str = "Chào mừng bạn đến server!",
    description: str = "",
    color: int = 0x5865F2,  # Discord blurple
    rules_summary: Optional[List[str]] = None,
    useful_channels: Optional[List[Dict[str, str]]] = None,
) -> Dict[str, Any]:
    """
    Send a rich embed welcome/rules message to a channel.
    Useful for setting up info channels.
    
    Args:
        channel_name: Target channel
        title: Embed title
        description: Main description text
        rules_summary: List of rules as strings
        useful_channels: List of {"name": str, "description": str}
    """
    channel = nextcord.utils.get(guild.text_channels, name=channel_name)
    if not channel:
        return {"success": False, "error": f"Channel '{channel_name}' not found"}

    embed = nextcord.Embed(
        title=title,
        description=description,
        color=color,
    )

    if rules_summary:
        rules_text = "\n".join(f"**{i+1}.** {rule}" for i, rule in enumerate(rules_summary))
        embed.add_field(name="📋 Nội quy", value=rules_text, inline=False)

    if useful_channels:
        channels_text = "\n".join(
            f"• **#{ch['name']}** — {ch.get('description', '')}"
            for ch in useful_channels
        )
        embed.add_field(name="📌 Kênh hữu ích", value=channels_text, inline=False)

    embed.set_footer(text=f"{guild.name} • Powered by AuraFactory")

    try:
        msg = await channel.send(embed=embed)
        return {
            "success": True,
            "message_id": msg.id,
            "channel": channel.name,
        }
    except nextcord.Forbidden:
        return {"success": False, "error": "Bot cannot send messages in this channel"}
    except Exception as e:
        return {"success": False, "error": str(e)}

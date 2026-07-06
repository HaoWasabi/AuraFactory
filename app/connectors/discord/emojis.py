# app/tools/discord/emojis.py
"""
Discord Emoji & Sticker Management Tools.
Upload, list, delete custom emojis.
"""
from typing import Optional, Dict, Any
import aiohttp
import nextcord


async def upload_emoji(
    guild: nextcord.Guild,
    emoji_name: str,
    image_url: str,
    reason: str = "AI Agent Request",
) -> Dict[str, Any]:
    """
    Upload a custom emoji from URL.
    
    Args:
        emoji_name: Name for the emoji (alphanumeric + underscore, 2-32 chars)
        image_url: URL of the image (PNG/GIF, max 256KB)
    """
    # Validate name
    import re
    if not re.match(r'^[a-zA-Z0-9_]{2,32}$', emoji_name):
        return {"success": False, "error": "Emoji name must be 2-32 alphanumeric/underscore characters"}

    try:
        # Download image
        async with aiohttp.ClientSession() as session:
            async with session.get(image_url) as resp:
                if resp.status != 200:
                    return {"success": False, "error": f"Failed to download image: HTTP {resp.status}"}
                
                image_data = await resp.read()
                
                if len(image_data) > 256 * 1024:
                    return {"success": False, "error": "Image too large (max 256KB)"}

        emoji = await guild.create_custom_emoji(
            name=emoji_name,
            image=image_data,
            reason=reason,
        )

        return {
            "success": True,
            "emoji_id": emoji.id,
            "emoji_name": emoji.name,
            "emoji_str": str(emoji),
            "animated": emoji.animated,
        }
    except nextcord.Forbidden:
        return {"success": False, "error": "Bot lacks Manage Emojis permission"}
    except nextcord.HTTPException as e:
        return {"success": False, "error": f"Discord API error: {e.text}"}
    except Exception as e:
        return {"success": False, "error": str(e)}


async def delete_emoji(
    guild: nextcord.Guild,
    emoji_name: str,
    reason: str = "AI Agent Request",
) -> Dict[str, Any]:
    """Delete a custom emoji by name."""
    emoji = None
    for e in guild.emojis:
        if e.name == emoji_name:
            emoji = e
            break
    
    if not emoji:
        return {"success": False, "error": f"Emoji '{emoji_name}' not found"}

    try:
        await emoji.delete(reason=reason)
        return {"success": True, "deleted": emoji_name}
    except nextcord.Forbidden:
        return {"success": False, "error": "Bot lacks Manage Emojis permission"}
    except Exception as e:
        return {"success": False, "error": str(e)}


async def list_emojis(guild: nextcord.Guild) -> Dict[str, Any]:
    """List all custom emojis in the guild."""
    emojis_data = []
    for emoji in guild.emojis:
        emojis_data.append({
            "id": emoji.id,
            "name": emoji.name,
            "animated": emoji.animated,
            "available": emoji.available,
            "str": str(emoji),
            "url": str(emoji.url),
        })
    
    return {
        "success": True,
        "emojis": emojis_data,
        "count": len(emojis_data),
        "limit": guild.emoji_limit,
        "slots_available": guild.emoji_limit - len(emojis_data),
    }

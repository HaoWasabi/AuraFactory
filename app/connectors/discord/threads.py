# app/tools/discord/threads.py
"""
Discord Thread Management Tools.
Create, archive, lock threads.
"""
from typing import Optional, Dict, Any
import nextcord


async def create_thread(
    guild: nextcord.Guild,
    channel_name: str,
    thread_name: str,
    message_content: Optional[str] = None,
    auto_archive_duration: int = 1440,  # minutes: 60, 1440, 4320, 10080
    thread_type: str = "public",  # "public" | "private"
    reason: str = "AI Agent Request",
) -> Dict[str, Any]:
    """
    Create a thread in a text channel.
    
    Args:
        channel_name: Parent channel name
        thread_name: Name of the new thread
        message_content: Optional starter message (creates thread from message)
        auto_archive_duration: Minutes until auto-archive (60, 1440, 4320, 10080)
        thread_type: "public" or "private"
    """
    # Find channel
    channel = None
    for ch in guild.text_channels:
        if ch.name == channel_name or str(ch.id) == str(channel_name):
            channel = ch
            break
    
    if not channel:
        return {"success": False, "error": f"Text channel '{channel_name}' not found"}

    try:
        if message_content:
            # Create thread from a new message
            msg = await channel.send(message_content)
            thread = await msg.create_thread(
                name=thread_name,
                auto_archive_duration=auto_archive_duration,
                reason=reason,
            )
        else:
            # Create standalone thread
            thread_type_enum = (
                nextcord.ChannelType.private_thread
                if thread_type == "private"
                else nextcord.ChannelType.public_thread
            )
            thread = await channel.create_thread(
                name=thread_name,
                type=thread_type_enum,
                auto_archive_duration=auto_archive_duration,
                reason=reason,
            )

        return {
            "success": True,
            "thread_id": thread.id,
            "thread_name": thread.name,
            "parent_channel": channel.name,
            "type": thread_type,
        }
    except nextcord.Forbidden:
        return {"success": False, "error": "Bot lacks permission to create threads"}
    except Exception as e:
        return {"success": False, "error": str(e)}


async def archive_thread(
    guild: nextcord.Guild,
    thread_id: int,
    locked: bool = False,
    reason: str = "AI Agent Request",
) -> Dict[str, Any]:
    """
    Archive (and optionally lock) a thread.
    """
    thread = guild.get_thread(thread_id)
    if not thread:
        # Try fetching
        try:
            thread = await guild.fetch_channel(thread_id)
        except nextcord.NotFound:
            return {"success": False, "error": f"Thread {thread_id} not found"}

    try:
        await thread.edit(archived=True, locked=locked, reason=reason)
        return {
            "success": True,
            "thread_id": thread.id,
            "thread_name": thread.name,
            "archived": True,
            "locked": locked,
        }
    except nextcord.Forbidden:
        return {"success": False, "error": "Bot lacks permission to archive threads"}
    except Exception as e:
        return {"success": False, "error": str(e)}


async def list_threads(
    guild: nextcord.Guild,
    channel_name: Optional[str] = None,
    include_archived: bool = False,
) -> Dict[str, Any]:
    """
    List active (and optionally archived) threads.
    """
    threads_data = []

    if channel_name:
        channel = None
        for ch in guild.text_channels:
            if ch.name == channel_name or str(ch.id) == str(channel_name):
                channel = ch
                break
        if not channel:
            return {"success": False, "error": f"Channel '{channel_name}' not found"}
        
        # Active threads
        for thread in channel.threads:
            threads_data.append({
                "id": thread.id,
                "name": thread.name,
                "archived": thread.archived,
                "locked": thread.locked,
                "member_count": thread.member_count,
            })
        
        if include_archived:
            async for thread in channel.archived_threads(limit=50):
                threads_data.append({
                    "id": thread.id,
                    "name": thread.name,
                    "archived": True,
                    "locked": thread.locked,
                    "member_count": thread.member_count,
                })
    else:
        # All active threads in guild
        threads = await guild.active_threads()
        for thread in threads:
            threads_data.append({
                "id": thread.id,
                "name": thread.name,
                "parent_channel": thread.parent.name if thread.parent else None,
                "archived": thread.archived,
                "locked": thread.locked,
                "member_count": thread.member_count,
            })

    return {
        "success": True,
        "threads": threads_data,
        "count": len(threads_data),
    }

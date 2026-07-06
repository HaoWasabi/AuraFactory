# app/channels/__init__.py
"""
Layer 1 — Channel Adapters.
Receive raw input from Discord/API/Web → standardized IncomingMessage.
Send OutgoingMessage back to the correct platform.
"""
from app.channels.discord_adapter import DiscordAdapter
from app.channels.api_adapter import APIAdapter

__all__ = ["DiscordAdapter", "APIAdapter"]

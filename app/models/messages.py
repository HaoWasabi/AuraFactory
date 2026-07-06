# app/models/messages.py
"""
Cross-layer message models.
IncomingMessage: standardized input from any platform.
OutgoingMessage: standardized response to user.
"""
from dataclasses import dataclass, field
from typing import Optional, Literal, List


@dataclass
class IncomingMessage:
    """Input from any platform, standardized."""
    user_id: str
    user_name: str
    prompt: str
    user_roles: List[str] = field(default_factory=list)  # Discord role names
    is_admin: bool = False  # True if user has admin/manage_guild permission
    guild_id: Optional[int] = None
    channel_id: Optional[int] = None
    message_id: Optional[str] = None
    source: Literal["discord", "api", "web"] = "discord"
    language: Optional[str] = None
    attachments: List[str] = field(default_factory=list)
    reply_to_message_id: Optional[str] = None
    metadata: dict = field(default_factory=dict)


@dataclass
class OutgoingMessage:
    """Response back to user."""
    content: str
    trace_id: str
    target_channel_id: Optional[int] = None
    target_user_id: Optional[str] = None
    source: Literal["discord", "api", "web"] = "discord"
    embed: Optional[dict] = None
    components: Optional[List[dict]] = None
    reply_to: Optional[str] = None
    ephemeral: bool = False
    metadata: dict = field(default_factory=dict)

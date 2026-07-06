"""Message models for AuraFactory pipeline."""
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class IncomingMessage:
    """Standardized incoming message from any channel (Discord/API/Web)."""
    user_id: str
    user_name: str
    prompt: str  # The cleaned user message content
    guild_id: Optional[int] = None
    channel_id: Optional[int] = None
    message_id: Optional[str] = None
    source: str = "discord"  # discord | api | web
    user_roles: List[str] = field(default_factory=list)
    is_admin: bool = False
    attachments: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)
    trace_id: str = field(default_factory=lambda: str(uuid.uuid4()))


@dataclass
class OutgoingMessage:
    """Standardized outgoing message to any channel."""
    content: str
    trace_id: str = ""
    target_channel_id: Optional[int] = None
    source: str = "discord"
    status: str = "success"
    approval_required: bool = False
    approval_id: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def mark_approved(self) -> None:
        """Mark this message as approved for sending."""
        self.status = "approved"
        self.approval_required = False

    def mark_sent(self) -> None:
        """Mark this message as successfully sent."""
        self.status = "sent"

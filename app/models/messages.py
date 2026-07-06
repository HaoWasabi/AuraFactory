"""Message models for incoming and outgoing Discord messages."""

import uuid
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class IncomingMessage:
    """Represents a message received from a Discord user."""

    user_id: str
    user_name: str
    guild_id: str
    content: str
    channel_id: str
    trace_id: str = field(default_factory=lambda: str(uuid.uuid4()))

    def __post_init__(self) -> None:
        if not self.content:
            raise ValueError("Message content cannot be empty")


@dataclass
class OutgoingMessage:
    """Represents a message to be sent back to Discord."""

    content: str
    trace_id: str
    status: str = "pending"
    approval_required: bool = False
    approval_id: Optional[str] = None

    def mark_approved(self) -> None:
        """Mark this message as approved for sending."""
        self.status = "approved"
        self.approval_required = False

    def mark_sent(self) -> None:
        """Mark this message as successfully sent."""
        self.status = "sent"

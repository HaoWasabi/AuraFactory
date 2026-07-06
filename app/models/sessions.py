"""Session models for user session management."""

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Dict, Any


@dataclass
class Session:
    """Represents an active user session."""

    session_id: str
    user_id: str
    guild_id: str
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    expires_at: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc) + timedelta(hours=24)
    )
    data: Dict[str, Any] = field(default_factory=dict)

    def is_expired(self) -> bool:
        """Check if the session has expired."""
        return datetime.now(timezone.utc) > self.expires_at

    def refresh(self, hours: int = 24) -> None:
        """Extend the session expiry."""
        self.expires_at = datetime.now(timezone.utc) + timedelta(hours=hours)

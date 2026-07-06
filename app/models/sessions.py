# app/models/sessions.py
"""Session model — conversation state per user."""
from dataclasses import dataclass, field
from typing import Optional, List
from datetime import datetime


@dataclass
class Session:
    """User conversation session."""
    id: str                             # UUID
    user_id: str
    guild_id: Optional[int]
    channel_id: Optional[int]
    created_at: datetime
    last_active: datetime
    message_history: List[dict] = field(default_factory=list)
    state: dict = field(default_factory=dict)  # Working memory slots
    is_active: bool = True

    def add_message(self, role: str, content: str) -> None:
        """Add a message to the session history."""
        self.message_history.append({
            "role": role,
            "content": content,
            "timestamp": datetime.utcnow().isoformat(),
        })
        self.last_active = datetime.utcnow()

    def get_context_window(self, max_messages: int = 10) -> List[dict]:
        """Get the last N messages as context window."""
        return self.message_history[-max_messages:]

    def set_state(self, key: str, value) -> None:
        """Set a working memory slot."""
        self.state[key] = value

    def get_state(self, key: str, default=None):
        """Get a working memory slot."""
        return self.state.get(key, default)

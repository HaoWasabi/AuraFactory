"""Custom exceptions for Discord connector operations."""
from __future__ import annotations

from typing import Any, Dict, Optional


class CommunityRequiredError(Exception):
    """Raised when an action requires the Community feature to be enabled on the guild.

    Carries structured context so the executor can surface a recovery suggestion
    instead of a raw error message.

    Attributes:
        feature_needed:  The Discord feature flag required (always "COMMUNITY").
        blocked_action:  The connector action that was blocked.
        channel_name:    Name of the channel being created, if applicable.
        channel_type:    Type of channel being created ("stage", "news", …).
    """

    def __init__(
        self,
        feature_needed: str = "COMMUNITY",
        blocked_action: str = "",
        channel_name: Optional[str] = None,
        channel_type: Optional[str] = None,
    ) -> None:
        self.feature_needed = feature_needed
        self.blocked_action = blocked_action
        self.channel_name = channel_name
        self.channel_type = channel_type or self._infer_channel_type(blocked_action)
        super().__init__(
            f"[community_required] Server feature '{feature_needed}' is required "
            f"to perform '{blocked_action}'. Enable Community in Server Settings first."
        )

    @staticmethod
    def _infer_channel_type(action: str) -> str:
        if "stage" in action:
            return "stage"
        if "news" in action or "announcement" in action:
            return "news"
        return "unknown"

    def to_dict(self) -> Dict[str, Any]:
        """Serialize to a dict for structured downstream handling."""
        return {
            "type": "community_required",
            "feature_needed": self.feature_needed,
            "blocked_action": self.blocked_action,
            "channel_name": self.channel_name,
            "channel_type": self.channel_type,
            "message": str(self),
        }

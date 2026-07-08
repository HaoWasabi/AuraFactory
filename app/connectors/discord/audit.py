"""Discord Audit Log Connector — SPEC v2 new module (schema §6).

Read-only audit log queries for debugging and transparency.

Actions: query
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

import nextcord

from app.connectors.base import BaseConnector
from app.connectors.discord._permissions import check_bot_permissions
from app.connectors.discord._validation import validate_kwargs

logger = logging.getLogger(__name__)


class AuditConnector(BaseConnector):
    """Queries Discord audit log. Read-only, LOW risk."""

    def __init__(self, bot: nextcord.Bot) -> None:
        self._bot = bot

    async def query(self, guild: nextcord.Guild, **kwargs) -> Dict[str, Any]:
        """Query the server's audit log.

        Optional kwargs: action_type (int), user_id (int), limit (int, max 100), before (snowflake)

        Returns recent audit log entries for inspection.
        """
        perm_error = check_bot_permissions(guild, "discord.audit.query")
        if perm_error:
            raise PermissionError(perm_error)

        clean = validate_kwargs("discord.audit.query", kwargs)

        limit = min(int(clean.get("limit", 25)), 100)
        action_type = clean.get("action_type")
        user_id = clean.get("user_id")

        fetch_kwargs: Dict[str, Any] = {"limit": limit}
        if action_type is not None:
            try:
                fetch_kwargs["action"] = nextcord.AuditLogAction(int(action_type))
            except (ValueError, KeyError):
                pass  # Skip invalid action type filter
        if user_id is not None:
            user = guild.get_member(int(user_id))
            if user:
                fetch_kwargs["user"] = user

        try:
            entries = []
            async for entry in guild.audit_logs(**fetch_kwargs):
                entries.append({
                    "id": str(entry.id),
                    "action": str(entry.action),
                    "user": str(entry.user) if entry.user else None,
                    "target": str(entry.target) if entry.target else None,
                    "reason": entry.reason,
                    "created_at": entry.created_at.isoformat() if entry.created_at else None,
                })
            return {"entries": entries, "count": len(entries)}
        except nextcord.errors.Forbidden:
            raise PermissionError("Bot lacks 'View Audit Log' permission.")
        except nextcord.errors.HTTPException as exc:
            raise RuntimeError(f"Failed to query audit log: {exc}")

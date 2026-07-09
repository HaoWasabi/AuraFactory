"""Discord Audit Connector — kwargs pattern. Actions: query"""

from __future__ import annotations
import logging
from typing import Any, Dict
import nextcord
from app.connectors.base import BaseConnector

logger = logging.getLogger(__name__)


class AuditConnector(BaseConnector):
    def __init__(self, bot: nextcord.Bot) -> None:
        self._bot = bot

    async def execute(self, action: str, guild: nextcord.Guild, **kwargs) -> Dict[str, Any]:
        actions = {"query": self.query}
        handler = actions.get(action)
        if handler is None:
            raise ValueError(f"Unknown action '{action}'")
        return await handler(guild, **kwargs)

    async def query(self, guild: nextcord.Guild, **kwargs) -> Dict[str, Any]:
        """Query audit log. kwargs: action_type, user_id, limit"""
        limit = kwargs.pop("limit", 50)
        user_id = kwargs.pop("user_id", None)
        action_type = kwargs.pop("action_type", None)

        query_kwargs: Dict[str, Any] = {"limit": int(limit)}
        if action_type is not None:
            try:
                query_kwargs["action"] = nextcord.AuditLogAction(int(action_type))
            except (ValueError, KeyError):
                pass

        try:
            entries = []
            async for entry in guild.audit_logs(**query_kwargs):
                if user_id and entry.user and entry.user.id != int(user_id):
                    continue
                entries.append({
                    "id": str(entry.id),
                    "action": str(entry.action),
                    "user": str(entry.user) if entry.user else None,
                    "target": str(entry.target) if entry.target else None,
                    "reason": entry.reason,
                    "created_at": entry.created_at.isoformat() if entry.created_at else None,
                })
            return {"entries": entries, "count": len(entries)}
        except nextcord.Forbidden:
            raise PermissionError("view_audit_log")
        except nextcord.HTTPException as exc:
            raise RuntimeError(f"Failed: {exc}")

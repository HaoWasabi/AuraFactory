from __future__ import annotations
import uuid
from datetime import datetime
from typing import Any, Optional
from pydantic import BaseModel, Field


# === Identity ===
class UserRecord(BaseModel):
    """Discord user record."""
    discord_user_id: int
    username: Optional[str] = None
    avatar_hash: Optional[str] = None
    last_login_at: Optional[datetime] = None


class GuildAdminEntry(BaseModel):
    """Guild admin/owner entry for permission caching."""
    user_id: int
    guild_id: int
    guild_name: Optional[str] = None
    is_owner: bool = False
    permissions_bitfield: int = 0
    cached_at: datetime = Field(default_factory=datetime.utcnow)


class BotInstall(BaseModel):
    """Bot installation record for a guild."""
    guild_id: int
    installed_by: Optional[int] = None
    installed_at: datetime = Field(default_factory=datetime.utcnow)
    is_active: bool = True


# === Session & Messages ===
class Session(BaseModel):
    """User session within a guild."""
    id: uuid.UUID = Field(default_factory=uuid.uuid4)
    guild_id: int
    user_id: int
    user_role: str = "member"
    history: list = Field(default_factory=list)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    last_active_at: datetime = Field(default_factory=datetime.utcnow)


class Message(BaseModel):
    """Individual message in a session."""
    id: uuid.UUID = Field(default_factory=uuid.uuid4)
    guild_id: int
    user_id: int
    origin: str  # 'web' | 'discord'
    role: str    # 'user' | 'bot'
    content: str
    created_at: datetime = Field(default_factory=datetime.utcnow)


# === Request Pipeline ===
class Request(BaseModel):
    """User request to the system (from web/Discord)."""
    id: uuid.UUID = Field(default_factory=uuid.uuid4)
    session_id: Optional[uuid.UUID] = None
    guild_id: int
    user_id: int
    origin: str = "discord"
    origin_channel_id: Optional[int] = None
    message: str
    intent: Optional[str] = None
    tool_mode: Optional[str] = None
    status: str = "received"
    response: Optional[str] = None
    error_message: Optional[str] = None
    llm_tokens_in: int = 0
    llm_tokens_out: int = 0
    llm_provider: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    completed_at: Optional[datetime] = None


class Plan(BaseModel):
    """Execution plan for a request."""
    id: uuid.UUID = Field(default_factory=uuid.uuid4)
    request_id: uuid.UUID
    guild_id: int
    description: Optional[str] = None
    total_steps: int
    risk_level: str  # LOW / MEDIUM / HIGH / CRITICAL
    status: str = "draft"
    current_step: int = 0
    approved_by: Optional[int] = None
    approved_at: Optional[datetime] = None
    rejected_reason: Optional[str] = None
    discord_message_id: Optional[int] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    expires_at: Optional[datetime] = None


class PlanStep(BaseModel):
    """Individual step in a plan."""
    id: uuid.UUID = Field(default_factory=uuid.uuid4)
    plan_id: uuid.UUID
    step_number: int
    tool_name: str
    tool_params: dict = Field(default_factory=dict)
    description: Optional[str] = None
    risk_level: str = "MEDIUM"
    status: str = "pending"
    result: Optional[dict] = None
    error_message: Optional[str] = None
    executed_at: Optional[datetime] = None
    duration_ms: Optional[int] = None


class AuditEntry(BaseModel):
    """Audit log entry for all tool executions."""
    id: uuid.UUID = Field(default_factory=uuid.uuid4)
    request_id: Optional[uuid.UUID] = None
    plan_step_id: Optional[uuid.UUID] = None
    guild_id: int
    user_id: int
    tool_name: str
    tool_params: dict
    risk_level: str
    success: bool
    result_data: Optional[dict] = None
    error_message: Optional[str] = None
    approved_by: Optional[int] = None
    executed_at: datetime = Field(default_factory=datetime.utcnow)
    duration_ms: Optional[int] = None


# === Server Context ===
class ServerSnapshot(BaseModel):
    """Snapshot of server state at a point in time."""
    guild_id: int
    categories: list = Field(default_factory=list)
    channels: list = Field(default_factory=list)
    roles: list = Field(default_factory=list)
    server_info: dict = Field(default_factory=dict)
    snapshot_at: datetime = Field(default_factory=datetime.utcnow)
    stale_after: Optional[datetime] = None


# === Enums / Constants ===
VALID_REQUEST_STATUSES = [
    'received', 'classified', 'planned', 'awaiting_approval',
    'executing', 'completed', 'failed', 'cancelled'
]

VALID_PLAN_STATUSES = [
    'draft', 'awaiting_approval', 'approved', 'executing',
    'completed', 'failed', 'cancelled'
]

VALID_STEP_STATUSES = ['pending', 'executing', 'completed', 'failed', 'skipped']

RISK_LEVELS = ['LOW', 'MEDIUM', 'HIGH', 'CRITICAL']

PERMISSIONS = {
    "owner":     {"setup", "manage", "moderate", "query", "server_settings", "automod"},
    "admin":     {"setup", "manage", "moderate", "query", "server_settings", "automod"},
    "moderator": {"moderate", "query"},
    "member":    {"query"},
}

RISK_REQUIRED_ROLE = {
    "LOW":      "member",
    "MEDIUM":   "admin",
    "HIGH":     "admin",
    "CRITICAL": "owner",
}

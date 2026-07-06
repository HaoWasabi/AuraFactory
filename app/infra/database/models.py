# app/infra/database/models.py
"""
SQLAlchemy ORM models for AuraFactory.
Defines all database tables per spec (08_data_models.md).
"""
import uuid
from datetime import datetime
from sqlalchemy import (
    Column, String, Integer, BigInteger, Boolean, DateTime,
    ForeignKey, Text, Float,
)
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import declarative_base
Base = declarative_base()


class Workspace(Base):
    """Discord guild/workspace registration."""
    __tablename__ = "workspaces"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    guild_id = Column(BigInteger, unique=True, nullable=False, index=True)
    guild_name = Column(String(100))
    owner_id = Column(String(50))
    config = Column(JSONB, default={})
    features = Column(JSONB, default={})
    created_at = Column(DateTime, default=datetime.utcnow)
    is_active = Column(Boolean, default=True)


class SessionDB(Base):
    """User conversation sessions."""
    __tablename__ = "sessions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(String(50), nullable=False, index=True)
    guild_id = Column(BigInteger, ForeignKey("workspaces.guild_id"), index=True)
    channel_id = Column(BigInteger)
    message_history = Column(JSONB, default=[])
    state = Column(JSONB, default={})
    created_at = Column(DateTime, default=datetime.utcnow)
    last_active = Column(DateTime, default=datetime.utcnow)
    is_active = Column(Boolean, default=True)


class TaskDB(Base):
    """Agent task execution log."""
    __tablename__ = "tasks"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    trace_id = Column(String(50), nullable=False, index=True)
    session_id = Column(UUID(as_uuid=True), ForeignKey("sessions.id"), nullable=True)
    parent_task_id = Column(UUID(as_uuid=True), ForeignKey("tasks.id"), nullable=True)
    agent_role = Column(String(20), nullable=False)
    action = Column(String(100), nullable=False)
    parameters = Column(JSONB, default={})
    status = Column(String(20), default="pending")
    result = Column(JSONB, default={})
    error_message = Column(Text, default="")
    execution_time_ms = Column(Float, default=0)
    tokens_used = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.utcnow)
    completed_at = Column(DateTime, nullable=True)


class ApprovalDB(Base):
    """Human-in-the-loop approval requests."""
    __tablename__ = "approvals"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    trace_id = Column(String(50), nullable=False, index=True)
    task_id = Column(UUID(as_uuid=True), ForeignKey("tasks.id"), nullable=True)
    guild_id = Column(BigInteger, nullable=False)
    user_id = Column(String(50), nullable=False)
    agent_role = Column(String(20), nullable=False)
    action = Column(String(100), nullable=False)
    parameters = Column(JSONB, default={})
    risk_level = Column(String(20), nullable=False)
    status = Column(String(20), default="pending")
    created_at = Column(DateTime, default=datetime.utcnow)
    decided_at = Column(DateTime, nullable=True)
    decided_by = Column(String(50), nullable=True)
    reason = Column(Text, default="")
    expires_at = Column(DateTime, nullable=True)


class MemoryDB(Base):
    """Long-term memory entries (persisted)."""
    __tablename__ = "memories"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    guild_id = Column(BigInteger, index=True)
    memory_type = Column(String(30), nullable=False, index=True)
    content = Column(Text, nullable=False)
    embedding_id = Column(String(100), nullable=True)
    importance = Column(Float, default=0.5)
    metadata = Column(JSONB, default={})
    source = Column(String(30), default="inferred")
    access_count = Column(Integer, default=0)
    last_accessed = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow)


class AuditLog(Base):
    """Audit trail for all agent actions."""
    __tablename__ = "audit_log"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    trace_id = Column(String(50), nullable=False, index=True)
    guild_id = Column(BigInteger, index=True)
    user_id = Column(String(50))
    agent_role = Column(String(20))
    action = Column(String(100))
    parameters = Column(JSONB, default={})
    result_status = Column(String(20))
    data = Column(JSONB, default={})
    created_at = Column(DateTime, default=datetime.utcnow)

# schemas/permissions.py
"""
Agentic AI Lens Principle 4: Pair autonomy with proportionate human oversight
Well-Architected (Security): Least privilege, defense in depth

Mỗi action có risk level → quyết định cần approval hay không.
Phase 1: Python dict check
Phase 2: Swap sang Cedar policies trên AWS Verified Permissions
"""
from enum import Enum
from typing import Dict, Set


class RiskLevel(str, Enum):
    """4 mức risk — scale oversight theo consequence"""
    LOW = "low"            # Auto-execute, không hỏi ai
    MEDIUM = "medium"      # Execute + notify admin
    HIGH = "high"          # Cần 1 admin approve TRƯỚC khi execute
    CRITICAL = "critical"  # Cần 2 admin approve + confirmation


# === ACTION → RISK MAPPING ===
# Đây là "Cedar policy" version local
# Khi lên AWS: convert thành Cedar policy language

ACTION_RISK_MAP: Dict[str, RiskLevel] = {
    # Architect Agent — Discord structure
    "create_channel": RiskLevel.MEDIUM,
    "modify_channel": RiskLevel.MEDIUM,
    "delete_channel": RiskLevel.HIGH,
    "create_category": RiskLevel.MEDIUM,
    "delete_category": RiskLevel.HIGH,
    
    # Moderator Agent — Member management
    "timeout_member": RiskLevel.MEDIUM,
    "kick_member": RiskLevel.HIGH,
    "ban_member": RiskLevel.CRITICAL,
    "purge_messages": RiskLevel.HIGH,
    "setup_automod": RiskLevel.MEDIUM,
    
    # DevOps Agent — Roles & System
    "create_role": RiskLevel.MEDIUM,
    "delete_role": RiskLevel.HIGH,
    "assign_role": RiskLevel.LOW,
    "backup_server": RiskLevel.LOW,
    "restore_server": RiskLevel.CRITICAL,
    "create_webhook": RiskLevel.MEDIUM,
    "delete_webhook": RiskLevel.HIGH,
    
    # Copilot Agent — Read-only (luôn safe)
    "query_knowledge": RiskLevel.LOW,
    "list_events": RiskLevel.LOW,
    "translate": RiskLevel.LOW,
    "answer_question": RiskLevel.LOW,
    
    # Bulk operations (luôn high risk)
    "bulk_create_channels": RiskLevel.HIGH,
    "bulk_delete": RiskLevel.CRITICAL,
}


# === AGENT → ALLOWED ACTIONS (Least Privilege) ===
# Mỗi agent CHỈ được dùng tools trong scope của mình

AGENT_PERMISSIONS: Dict[str, Set[str]] = {
    "orchestrator": {
        "route_to_agent", "decompose_task", "request_approval", "aggregate_results"
    },
    "architect": {
        "create_channel", "modify_channel", "delete_channel",
        "create_category", "delete_category", "bulk_create_channels",
    },
    "moderator": {
        "timeout_member", "kick_member", "ban_member",
        "purge_messages", "setup_automod",
    },
    "devops": {
        "create_role", "delete_role", "assign_role",
        "backup_server", "restore_server",
        "create_webhook", "delete_webhook",
    },
    "copilot": {
        "query_knowledge", "list_events", "translate", "answer_question",
    },
}


def check_permission(agent_role: str, action: str) -> bool:
    """
    Least privilege check — Phase 1 (local dict).
    Phase 2: Replace với Cedar policy evaluation.
    """
    allowed = AGENT_PERMISSIONS.get(agent_role, set())
    return action in allowed


def get_risk_level(action: str) -> RiskLevel:
    """Tra risk level cho action. Unknown actions = HIGH (safe default)."""
    return ACTION_RISK_MAP.get(action, RiskLevel.HIGH)


def requires_approval(action: str) -> bool:
    """Action này cần human approve trước khi execute?"""
    risk = get_risk_level(action)
    return risk in (RiskLevel.HIGH, RiskLevel.CRITICAL)

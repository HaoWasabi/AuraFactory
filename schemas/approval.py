# schemas/approval.py
"""
Agentic AI Lens Principle 4: Pair autonomy with proportionate human oversight
Well-Architected (Security): Human-in-the-loop for critical decisions

Approval flow:
  Agent muốn execute action nguy hiểm
    → Tạo PendingApproval (lưu state)
    → Frontend hiển thị nút Approve/Reject
    → Admin click → API /approve hoặc /reject
    → Agent execute (hoặc cancel)

Phase 1: In-memory store (dict)
Phase 2: DynamoDB + TTL + Discord notification
"""
import time
from dataclasses import dataclass, field
from typing import Dict, Any, Optional
from datetime import datetime
from uuid import uuid4


@dataclass
class PendingApproval:
    """Một yêu cầu phê duyệt đang chờ"""
    approval_id: str
    trace_id: str
    agent_id: str
    action: str
    parameters: Dict[str, Any]
    risk_level: str
    reason: str = ""
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    expires_at: float = 0.0  # Unix timestamp — hết hạn sau 5 phút
    status: str = "pending"  # pending | approved | rejected | expired
    approver: str = ""
    resolved_at: str = ""
    
    def to_dict(self) -> dict:
        return {
            "approval_id": self.approval_id,
            "trace_id": self.trace_id,
            "agent_id": self.agent_id,
            "action": self.action,
            "parameters": self.parameters,
            "risk_level": self.risk_level,
            "reason": self.reason,
            "created_at": self.created_at,
            "status": self.status,
            "approver": self.approver,
        }


class ApprovalStore:
    """
    Quản lý pending approvals.
    
    Phase 1: In-memory dict (restart = mất)
    Phase 2: Swap sang DynamoDB (persistent, TTL tự xóa expired)
    """
    
    TIMEOUT_SECONDS = 300  # 5 phút timeout
    
    def __init__(self):
        self._store: Dict[str, PendingApproval] = {}
    
    def create(
        self,
        trace_id: str,
        agent_id: str,
        action: str,
        parameters: Dict[str, Any],
        risk_level: str,
        reason: str = "",
    ) -> PendingApproval:
        """Tạo approval request mới"""
        approval = PendingApproval(
            approval_id=str(uuid4())[:8],
            trace_id=trace_id,
            agent_id=agent_id,
            action=action,
            parameters=parameters,
            risk_level=risk_level,
            reason=reason,
            expires_at=time.time() + self.TIMEOUT_SECONDS,
        )
        self._store[approval.approval_id] = approval
        return approval
    
    def get(self, approval_id: str) -> Optional[PendingApproval]:
        """Lấy approval by ID"""
        approval = self._store.get(approval_id)
        if approval and approval.status == "pending":
            # Check expired
            if time.time() > approval.expires_at:
                approval.status = "expired"
        return approval
    
    def approve(self, approval_id: str, approver: str = "admin") -> Optional[PendingApproval]:
        """Admin phê duyệt"""
        approval = self.get(approval_id)
        if not approval:
            return None
        if approval.status != "pending":
            return approval  # Đã xử lý rồi
        
        approval.status = "approved"
        approval.approver = approver
        approval.resolved_at = datetime.now().isoformat()
        return approval
    
    def reject(self, approval_id: str, approver: str = "admin", reason: str = "") -> Optional[PendingApproval]:
        """Admin từ chối"""
        approval = self.get(approval_id)
        if not approval:
            return None
        if approval.status != "pending":
            return approval
        
        approval.status = "rejected"
        approval.approver = approver
        approval.reason = reason
        approval.resolved_at = datetime.now().isoformat()
        return approval
    
    def list_pending(self) -> list:
        """Liệt kê tất cả approvals đang pending"""
        self._cleanup_expired()
        return [a.to_dict() for a in self._store.values() if a.status == "pending"]
    
    def list_all(self) -> list:
        """Liệt kê toàn bộ (for debug/dashboard)"""
        return [a.to_dict() for a in self._store.values()]
    
    def _cleanup_expired(self):
        """Tự động expire pending requests quá timeout"""
        now = time.time()
        for a in self._store.values():
            if a.status == "pending" and now > a.expires_at:
                a.status = "expired"

-- Migration 011: Add user_id to plans + react columns to audit_log
-- Required by: PlannerService, ExecutorService, ApprovalService

-- Plans: add user_id (needed for ownership verification in ApprovalService §5.5)
ALTER TABLE plans ADD COLUMN IF NOT EXISTS user_id BIGINT;

-- Audit_log: add react_adjusted and react_reason (§5.6b ReActStepHandler logging)
ALTER TABLE audit_log ADD COLUMN IF NOT EXISTS react_adjusted BOOLEAN DEFAULT FALSE;
ALTER TABLE audit_log ADD COLUMN IF NOT EXISTS react_reason TEXT;

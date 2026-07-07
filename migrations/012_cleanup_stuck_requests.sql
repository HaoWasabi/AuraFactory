-- Migration 012: One-time cleanup of stuck requests from before code fixes.
-- Marks any request stuck in active states as 'failed' so the lock is released.

UPDATE requests
SET status = 'failed', error_message = 'Cleaned up: stuck after server restart', completed_at = NOW()
WHERE status IN ('planned', 'awaiting_approval', 'executing');

UPDATE plans
SET status = 'cancelled'
WHERE status IN ('draft', 'awaiting_approval', 'approved', 'executing');

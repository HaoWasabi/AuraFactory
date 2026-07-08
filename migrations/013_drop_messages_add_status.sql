-- Migration 013: Drop messages table + add 'waiting_for_info' status
-- Required by: Planner clarify flow, dashboard session history (uses sessions.history instead)

-- 1. Drop messages table (data now lives in sessions.history JSONB)
DROP TABLE IF EXISTS messages;

-- 2. Add 'waiting_for_info' to requests.valid_status constraint
ALTER TABLE requests DROP CONSTRAINT IF EXISTS valid_status;
ALTER TABLE requests ADD CONSTRAINT valid_status CHECK (status IN (
    'received', 'classified', 'planned', 'awaiting_approval',
    'executing', 'completed', 'failed', 'cancelled',
    'waiting_for_info'
));

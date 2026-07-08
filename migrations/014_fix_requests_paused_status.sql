-- Migration 014: Fix requests.valid_status constraint to allow 'paused'
--
-- Migration 013 added a NEW constraint named 'valid_request_status' but
-- did NOT drop the ORIGINAL constraint 'valid_status' from migration 002.
-- Both constraints exist simultaneously, so any INSERT/UPDATE with status='paused'
-- fails on the old 'valid_status' constraint which does not include 'paused'.

-- Drop the original constraint from migration 002
ALTER TABLE requests
    DROP CONSTRAINT IF EXISTS valid_status;

-- Drop the one added by migration 013 (may or may not exist depending on DB state)
ALTER TABLE requests
    DROP CONSTRAINT IF EXISTS valid_request_status;

-- Re-add a single, canonical constraint with all valid statuses
ALTER TABLE requests
    ADD CONSTRAINT valid_status CHECK (status IN (
        'received', 'classified', 'planned', 'awaiting_approval',
        'executing', 'completed', 'failed', 'cancelled', 'paused'
    ));

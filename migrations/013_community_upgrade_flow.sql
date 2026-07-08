-- Migration 013: Community upgrade flow support
-- Adds community_payload to plans, and extends status enums.

-- 1. Add community_payload column (nullable JSONB) to plans
ALTER TABLE plans
    ADD COLUMN IF NOT EXISTS community_payload JSONB;

-- 2. Extend plans.status CHECK to include 'paused'
ALTER TABLE plans
    DROP CONSTRAINT IF EXISTS valid_plan_status;

ALTER TABLE plans
    ADD CONSTRAINT valid_plan_status CHECK (status IN (
        'draft', 'awaiting_approval', 'approved', 'executing',
        'completed', 'failed', 'cancelled', 'paused'
    ));

-- 3. Extend plan_steps.status CHECK to include 'paused'
ALTER TABLE plan_steps
    DROP CONSTRAINT IF EXISTS valid_step_status;

ALTER TABLE plan_steps
    ADD CONSTRAINT valid_step_status CHECK (status IN (
        'pending', 'executing', 'completed', 'failed', 'skipped', 'paused'
    ));

-- 4. Extend requests.status to include 'paused'
-- NOTE: The original constraint from migration 002 is named 'valid_status'.
-- We must drop BOTH the old name and the new name to avoid duplicates.
ALTER TABLE requests
    DROP CONSTRAINT IF EXISTS valid_status;

ALTER TABLE requests
    DROP CONSTRAINT IF EXISTS valid_request_status;

ALTER TABLE requests
    ADD CONSTRAINT valid_status CHECK (status IN (
        'received', 'classified', 'planned', 'awaiting_approval',
        'executing', 'completed', 'failed', 'cancelled', 'paused'
    ));

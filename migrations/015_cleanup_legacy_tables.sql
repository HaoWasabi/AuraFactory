-- Migration 015: Cleanup legacy tables from v1 pipeline (no longer used by UnifiedAgent v2)
-- 
-- Dead tables (no INSERT/SELECT in current codebase):
--   - plan_steps: v1 multi-step planner (replaced by in-memory pipeline)
--   - plans: v1 plan storage (replaced by RequestLifecycle)
--   - rate_limits: v1 rate limiting (replaced by in-memory RateLimitMiddleware)
--   - requests: v1 request tracking (replaced by RequestLifecycle FSM)
--
-- Note: audit_log.request_id FK references requests(id) — set to NULL before drop.
-- Note: plans.request_id FK references requests(id) — cascade on drop.

-- Step 1: Drop dependent tables first (has FK to plans)
DROP TABLE IF EXISTS plan_steps CASCADE;

-- Step 2: Drop plans (has FK to requests)
DROP TABLE IF EXISTS plans CASCADE;

-- Step 3: Drop rate_limits (no FKs)
DROP TABLE IF EXISTS rate_limits;

-- Step 4: Remove FK constraint from audit_log → requests, then drop requests
ALTER TABLE audit_log DROP CONSTRAINT IF EXISTS audit_log_request_id_fkey;
ALTER TABLE audit_log DROP COLUMN IF EXISTS request_id;
ALTER TABLE audit_log DROP COLUMN IF EXISTS plan_step_id;

-- Step 5: Drop requests table
DROP TABLE IF EXISTS requests;

-- Step 6: Cleanup — remove react columns from audit_log (legacy v1 ReAct pattern)
ALTER TABLE audit_log DROP COLUMN IF EXISTS react_adjusted;
ALTER TABLE audit_log DROP COLUMN IF EXISTS react_reason;

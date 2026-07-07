CREATE TABLE IF NOT EXISTS plans (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    request_id UUID REFERENCES requests(id) ON DELETE CASCADE,
    guild_id BIGINT NOT NULL,
    description TEXT,
    total_steps INT NOT NULL,
    risk_level VARCHAR(10) NOT NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'draft',
    current_step INT DEFAULT 0,
    approved_by BIGINT,
    approved_at TIMESTAMPTZ,
    rejected_reason TEXT,
    discord_message_id BIGINT,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    expires_at TIMESTAMPTZ DEFAULT NOW() + INTERVAL '30 minutes',
    CONSTRAINT valid_plan_status CHECK (status IN (
        'draft', 'awaiting_approval', 'approved', 'executing',
        'completed', 'failed', 'cancelled'
    ))
);

CREATE TABLE IF NOT EXISTS plan_steps (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    plan_id UUID REFERENCES plans(id) ON DELETE CASCADE,
    step_number INT NOT NULL,
    tool_name VARCHAR(50) NOT NULL,
    tool_params JSONB NOT NULL DEFAULT '{}',
    description TEXT,
    risk_level VARCHAR(10) NOT NULL DEFAULT 'medium',
    status VARCHAR(20) NOT NULL DEFAULT 'pending',
    result JSONB,
    error_message TEXT,
    executed_at TIMESTAMPTZ,
    duration_ms INT,
    UNIQUE(plan_id, step_number),
    CONSTRAINT valid_step_status CHECK (status IN (
        'pending', 'executing', 'completed', 'failed', 'skipped'
    ))
);
CREATE INDEX IF NOT EXISTS idx_plan_steps_plan ON plan_steps(plan_id, step_number);
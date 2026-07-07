CREATE TABLE IF NOT EXISTS audit_log (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    request_id UUID REFERENCES requests(id),
    plan_step_id UUID REFERENCES plan_steps(id),
    guild_id BIGINT NOT NULL,
    user_id BIGINT NOT NULL,
    tool_name VARCHAR(50) NOT NULL,
    tool_params JSONB NOT NULL,
    risk_level VARCHAR(10) NOT NULL,
    success BOOLEAN NOT NULL,
    result_data JSONB,
    error_message TEXT,
    approved_by BIGINT,
    executed_at TIMESTAMPTZ DEFAULT NOW(),
    duration_ms INT
);
CREATE INDEX IF NOT EXISTS idx_audit_guild ON audit_log(guild_id, executed_at DESC);
CREATE INDEX IF NOT EXISTS idx_audit_user ON audit_log(user_id, executed_at DESC);
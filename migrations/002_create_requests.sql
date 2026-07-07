CREATE TABLE IF NOT EXISTS requests (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id UUID REFERENCES sessions(id),
    guild_id BIGINT NOT NULL,
    user_id BIGINT NOT NULL,
    origin VARCHAR(10) NOT NULL DEFAULT 'discord',
    origin_channel_id BIGINT,
    message TEXT NOT NULL,
    intent VARCHAR(30),
    tool_mode VARCHAR(20),
    status VARCHAR(20) NOT NULL DEFAULT 'received',
    response TEXT,
    error_message TEXT,
    llm_tokens_in INT DEFAULT 0,
    llm_tokens_out INT DEFAULT 0,
    llm_provider VARCHAR(20),
    created_at TIMESTAMPTZ DEFAULT NOW(),
    completed_at TIMESTAMPTZ,
    CONSTRAINT valid_status CHECK (status IN (
        'received', 'classified', 'planned', 'awaiting_approval',
        'executing', 'completed', 'failed', 'cancelled'
    ))
);
CREATE INDEX IF NOT EXISTS idx_requests_session ON requests(session_id);
CREATE INDEX IF NOT EXISTS idx_requests_status ON requests(status) WHERE status NOT IN ('completed', 'failed');
CREATE UNIQUE INDEX IF NOT EXISTS idx_one_active_request
    ON requests(guild_id, user_id)
    WHERE status IN ('planned', 'awaiting_approval', 'executing');
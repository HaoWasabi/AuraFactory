"""SQL schema definitions for all AuraFactory tables."""

SCHEMA_SQL = """
-- Guilds table
CREATE TABLE IF NOT EXISTS guilds (
    guild_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    budget_daily_usd NUMERIC(10, 4) DEFAULT 5.0,
    rate_limit_per_min INTEGER DEFAULT 30,
    features JSONB DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Sessions table
CREATE TABLE IF NOT EXISTS sessions (
    session_id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    guild_id TEXT NOT NULL REFERENCES guilds(guild_id) ON DELETE CASCADE,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    expires_at TIMESTAMPTZ NOT NULL,
    data JSONB DEFAULT '{}'::jsonb
);

CREATE INDEX IF NOT EXISTS idx_sessions_user_id ON sessions(user_id);
CREATE INDEX IF NOT EXISTS idx_sessions_guild_id ON sessions(guild_id);
CREATE INDEX IF NOT EXISTS idx_sessions_expires_at ON sessions(expires_at);

-- Approvals table
CREATE TABLE IF NOT EXISTS approvals (
    approval_id TEXT PRIMARY KEY,
    trace_id TEXT NOT NULL,
    guild_id TEXT NOT NULL REFERENCES guilds(guild_id) ON DELETE CASCADE,
    user_id TEXT NOT NULL,
    content TEXT NOT NULL,
    status TEXT DEFAULT 'pending',
    reviewed_by TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    reviewed_at TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_approvals_guild_id ON approvals(guild_id);
CREATE INDEX IF NOT EXISTS idx_approvals_status ON approvals(status);

-- Procedural memory table
CREATE TABLE IF NOT EXISTS procedural_memory (
    rule_id TEXT PRIMARY KEY,
    guild_id TEXT NOT NULL REFERENCES guilds(guild_id) ON DELETE CASCADE,
    trigger_condition JSONB NOT NULL DEFAULT '{}'::jsonb,
    action JSONB NOT NULL DEFAULT '{}'::jsonb,
    confidence NUMERIC(5, 4) DEFAULT 0.5,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_procedural_memory_guild_id ON procedural_memory(guild_id);
CREATE INDEX IF NOT EXISTS idx_procedural_memory_confidence ON procedural_memory(confidence);

-- Knowledge store table
CREATE TABLE IF NOT EXISTS knowledge_store (
    id SERIAL PRIMARY KEY,
    guild_id TEXT NOT NULL REFERENCES guilds(guild_id) ON DELETE CASCADE,
    snapshot JSONB NOT NULL DEFAULT '{}'::jsonb,
    crawled_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_knowledge_store_guild_id ON knowledge_store(guild_id);
CREATE INDEX IF NOT EXISTS idx_knowledge_store_crawled_at ON knowledge_store(crawled_at);

-- Cost log table
CREATE TABLE IF NOT EXISTS cost_log (
    id SERIAL PRIMARY KEY,
    trace_id TEXT NOT NULL,
    guild_id TEXT NOT NULL,
    agent_name TEXT NOT NULL,
    provider TEXT NOT NULL,
    tokens_in INTEGER DEFAULT 0,
    tokens_out INTEGER DEFAULT 0,
    cost_usd NUMERIC(10, 6) DEFAULT 0.0,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_cost_log_guild_id ON cost_log(guild_id);
CREATE INDEX IF NOT EXISTS idx_cost_log_agent_name ON cost_log(agent_name);
CREATE INDEX IF NOT EXISTS idx_cost_log_created_at ON cost_log(created_at);

-- Audit log table
CREATE TABLE IF NOT EXISTS audit_log (
    id SERIAL PRIMARY KEY,
    trace_id TEXT NOT NULL,
    guild_id TEXT NOT NULL,
    user_id TEXT,
    action TEXT NOT NULL,
    details JSONB DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_audit_log_guild_id ON audit_log(guild_id);
CREATE INDEX IF NOT EXISTS idx_audit_log_action ON audit_log(action);
CREATE INDEX IF NOT EXISTS idx_audit_log_created_at ON audit_log(created_at);
"""

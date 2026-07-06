-- ============================================================
-- AuraFactory — Schema v1.0 (Phase 1)
-- PostgreSQL 16+
-- ============================================================

-- Extensions
CREATE EXTENSION IF NOT EXISTS "pgcrypto";    -- gen_random_uuid()
CREATE EXTENSION IF NOT EXISTS "pg_trgm";     -- fuzzy text search

-- ============================================================
-- 1. WORKSPACES (Discord Servers)
-- ============================================================
CREATE TABLE workspaces (
    workspace_id    UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    discord_guild_id BIGINT NOT NULL UNIQUE,
    name            TEXT NOT NULL,
    owner_discord_id BIGINT NOT NULL,
    plan            TEXT NOT NULL DEFAULT 'free',   -- free | pro | enterprise
    status          TEXT NOT NULL DEFAULT 'active', -- active | suspended
    token_budget_daily INT DEFAULT 100000,
    token_used_today   INT DEFAULT 0,
    settings        JSONB DEFAULT '{}',
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    updated_at      TIMESTAMPTZ DEFAULT NOW()
);

-- ============================================================
-- 2. SESSIONS (Phiên hội thoại)
-- ============================================================
CREATE TABLE sessions (
    session_id      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    workspace_id    UUID NOT NULL REFERENCES workspaces(workspace_id) ON DELETE CASCADE,
    user_discord_id BIGINT NOT NULL,
    channel         TEXT NOT NULL DEFAULT 'discord', -- discord | web_chat | api
    status          TEXT NOT NULL DEFAULT 'active',  -- active | completed | expired
    summary         TEXT,
    total_tokens    INT DEFAULT 0,
    total_cost_usd  NUMERIC(10,6) DEFAULT 0.0,
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    last_active_at  TIMESTAMPTZ DEFAULT NOW(),
    expired_at      TIMESTAMPTZ
);

CREATE INDEX idx_sessions_workspace ON sessions(workspace_id, status);
CREATE INDEX idx_sessions_user ON sessions(user_discord_id, last_active_at DESC);

-- ============================================================
-- 3. MESSAGES (Lịch sử tin nhắn)
-- ============================================================
CREATE TABLE messages (
    message_id      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id      UUID NOT NULL REFERENCES sessions(session_id) ON DELETE CASCADE,
    role            TEXT NOT NULL,      -- user | assistant | system | tool
    content         TEXT NOT NULL,
    agent_id        TEXT,               -- NULL nếu user message
    token_count     INT DEFAULT 0,
    metadata        JSONB,             -- tool_calls, model, etc.
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_messages_session ON messages(session_id, created_at);

-- ============================================================
-- 4. AGENTS (Agent Registry)
-- ============================================================
CREATE TABLE agents (
    agent_id        TEXT PRIMARY KEY,   -- orchestrator | architect | copilot
    display_name    TEXT NOT NULL,
    description     TEXT,
    status          TEXT NOT NULL DEFAULT 'active',
    model_preference TEXT DEFAULT 'auto',
    max_loops       INT DEFAULT 10,
    token_budget    INT DEFAULT 50000,
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    updated_at      TIMESTAMPTZ DEFAULT NOW()
);

-- Agent capabilities (normalized — dễ query "ai có quyền gì?")
CREATE TABLE agent_capabilities (
    agent_id        TEXT NOT NULL REFERENCES agents(agent_id) ON DELETE CASCADE,
    capability      TEXT NOT NULL,      -- create_channel, manage_roles, etc.
    PRIMARY KEY (agent_id, capability)
);

-- ============================================================
-- 5. TASKS (Nhiệm vụ thực thi)
-- ============================================================
CREATE TABLE tasks (
    task_id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id      UUID NOT NULL REFERENCES sessions(session_id) ON DELETE CASCADE,
    workspace_id    UUID NOT NULL REFERENCES workspaces(workspace_id),
    parent_task_id  UUID REFERENCES tasks(task_id),
    assigned_agent  TEXT NOT NULL REFERENCES agents(agent_id),

    -- Definition
    intent          TEXT NOT NULL,      -- create_channels, setup_roles, etc.
    parameters      JSONB NOT NULL DEFAULT '{}',
    constraints     JSONB,

    -- State
    status          TEXT NOT NULL DEFAULT 'pending',
        -- pending | running | waiting_approval | completed | failed | cancelled
    current_step    INT DEFAULT 0,
    total_steps     INT,
    scratchpad      JSONB,             -- agent reasoning state (persist for recovery)

    -- Results
    result          JSONB,
    error           TEXT,

    -- Metrics
    loops_used      INT DEFAULT 0,
    tokens_used     INT DEFAULT 0,
    cost_usd        NUMERIC(10,6) DEFAULT 0.0,
    duration_ms     INT,

    -- Risk & Approval
    risk_level      TEXT NOT NULL DEFAULT 'LOW',  -- LOW | MEDIUM | HIGH | CRITICAL
    requires_approval BOOLEAN DEFAULT FALSE,

    created_at      TIMESTAMPTZ DEFAULT NOW(),
    started_at      TIMESTAMPTZ,
    completed_at    TIMESTAMPTZ
);

CREATE INDEX idx_tasks_session ON tasks(session_id);
CREATE INDEX idx_tasks_status ON tasks(workspace_id, status);

-- ============================================================
-- 6. APPROVALS (Human-in-the-Loop)
-- ============================================================
CREATE TABLE approvals (
    approval_id     UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    task_id         UUID NOT NULL REFERENCES tasks(task_id) ON DELETE CASCADE,
    workspace_id    UUID NOT NULL REFERENCES workspaces(workspace_id),

    -- What
    action_type     TEXT NOT NULL,      -- delete_channel, kick_member, etc.
    action_detail   JSONB NOT NULL,
    risk_level      TEXT NOT NULL,      -- HIGH | CRITICAL

    -- State
    status          TEXT NOT NULL DEFAULT 'pending', -- pending | approved | rejected | expired
    reviewer_discord_id BIGINT,
    reviewer_note   TEXT,

    -- Timing
    requested_at    TIMESTAMPTZ DEFAULT NOW(),
    expires_at      TIMESTAMPTZ,
    resolved_at     TIMESTAMPTZ
);

CREATE INDEX idx_approvals_pending ON approvals(workspace_id, status)
    WHERE status = 'pending';

-- ============================================================
-- 7. TOOL EXECUTIONS (Lịch sử gọi tool)
-- ============================================================
CREATE TABLE tool_executions (
    execution_id    UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    task_id         UUID NOT NULL REFERENCES tasks(task_id) ON DELETE CASCADE,
    agent_id        TEXT NOT NULL REFERENCES agents(agent_id),

    -- Tool info
    tool_name       TEXT NOT NULL,
    tool_input      JSONB NOT NULL,
    tool_output     JSONB,

    -- State
    status          TEXT NOT NULL DEFAULT 'success', -- success | failed | timeout | rolled_back
    error_message   TEXT,
    duration_ms     INT,

    -- Rollback
    rollback_data   JSONB,
    rolled_back     BOOLEAN DEFAULT FALSE,

    executed_at     TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_tool_exec_task ON tool_executions(task_id, executed_at);

-- ============================================================
-- 8. TRACES (Distributed Tracing — thay thế JSONL file)
-- ============================================================
CREATE TABLE traces (
    trace_id        UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id      UUID REFERENCES sessions(session_id),
    workspace_id    UUID NOT NULL REFERENCES workspaces(workspace_id),
    status          TEXT NOT NULL DEFAULT 'active', -- active | completed | error
    total_duration_ms INT,
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    completed_at    TIMESTAMPTZ
);

CREATE TABLE trace_events (
    event_id        UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    trace_id        UUID NOT NULL REFERENCES traces(trace_id) ON DELETE CASCADE,
    parent_event_id UUID REFERENCES trace_events(event_id),

    -- Event info
    event_type      TEXT NOT NULL,      -- llm_call | tool_call | agent_step | decision
    agent_id        TEXT,
    detail          JSONB NOT NULL,     -- model, tokens, input/output summary

    -- Timing
    started_at      TIMESTAMPTZ DEFAULT NOW(),
    duration_ms     INT
);

CREATE INDEX idx_trace_events_trace ON trace_events(trace_id, started_at);

-- ============================================================
-- 9. AUDIT LOG (Nhật ký kiểm toán)
-- ============================================================
CREATE TABLE audit_log (
    log_id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    trace_id        UUID REFERENCES traces(trace_id),
    workspace_id    UUID NOT NULL,

    -- Who
    actor_type      TEXT NOT NULL,      -- user | agent | system
    actor_id        TEXT NOT NULL,

    -- What
    action          TEXT NOT NULL,      -- channel.create, role.assign, etc.
    resource_type   TEXT,               -- channel | role | member | webhook
    resource_id     TEXT,
    detail          JSONB,

    -- Context
    session_id      UUID,
    task_id         UUID,
    risk_level      TEXT,

    created_at      TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_audit_workspace ON audit_log(workspace_id, created_at DESC);
CREATE INDEX idx_audit_trace ON audit_log(trace_id);

-- ============================================================
-- 10. COST TRACKING
-- ============================================================
CREATE TABLE cost_records (
    record_id       UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    workspace_id    UUID NOT NULL REFERENCES workspaces(workspace_id),
    session_id      UUID REFERENCES sessions(session_id),
    task_id         UUID REFERENCES tasks(task_id),
    agent_id        TEXT REFERENCES agents(agent_id),

    -- Usage
    model_name      TEXT NOT NULL,
    input_tokens    INT NOT NULL,
    output_tokens   INT NOT NULL,
    total_tokens    INT NOT NULL,
    cost_usd        NUMERIC(10,6) NOT NULL,

    -- Context
    call_type       TEXT,               -- reasoning | planning | consolidation | embedding

    created_at      TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_cost_workspace_date ON cost_records(workspace_id, created_at DESC);

-- ============================================================
-- 11. PROMPT VERSIONS
-- ============================================================
CREATE TABLE prompt_versions (
    version_id      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    prompt_name     TEXT NOT NULL,      -- orchestrator_system, architect_system
    agent_id        TEXT REFERENCES agents(agent_id),
    content         TEXT NOT NULL,
    version_number  INT NOT NULL,
    author          TEXT,
    change_reason   TEXT,
    is_active       BOOLEAN DEFAULT FALSE,
    success_rate    NUMERIC(5,2),
    avg_tokens      NUMERIC(10,1),
    eval_score      NUMERIC(3,2),
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    deployed_at     TIMESTAMPTZ
);

CREATE UNIQUE INDEX idx_prompt_active ON prompt_versions(prompt_name)
    WHERE is_active = TRUE;

-- ============================================================
-- 12. DISCORD SNAPSHOT (Cache state cho rollback & audit)
-- ============================================================
CREATE TABLE discord_channels (
    channel_id      BIGINT PRIMARY KEY,
    workspace_id    UUID NOT NULL REFERENCES workspaces(workspace_id) ON DELETE CASCADE,
    guild_id        BIGINT NOT NULL,
    name            TEXT NOT NULL,
    type            TEXT NOT NULL,       -- text | voice | category | forum
    category_id     BIGINT,
    position        INT,
    synced_at       TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE discord_roles (
    role_id         BIGINT PRIMARY KEY,
    workspace_id    UUID NOT NULL REFERENCES workspaces(workspace_id) ON DELETE CASCADE,
    guild_id        BIGINT NOT NULL,
    name            TEXT NOT NULL,
    color           INT DEFAULT 0,
    position        INT,
    permissions     BIGINT DEFAULT 0,
    synced_at       TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE discord_members (
    member_id       BIGINT NOT NULL,
    workspace_id    UUID NOT NULL REFERENCES workspaces(workspace_id) ON DELETE CASCADE,
    guild_id        BIGINT NOT NULL,
    display_name    TEXT,
    role_ids        BIGINT[],           -- Array of role IDs
    joined_at       TIMESTAMPTZ,
    synced_at       TIMESTAMPTZ DEFAULT NOW(),
    PRIMARY KEY (member_id, workspace_id)
);

-- ============================================================
-- 13. PROCEDURAL MEMORY (Learned Patterns)
-- ============================================================
CREATE TABLE procedural_memory (
    memory_id       UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    workspace_id    UUID NOT NULL REFERENCES workspaces(workspace_id) ON DELETE CASCADE,

    pattern_name    TEXT NOT NULL,
    description     TEXT NOT NULL,       -- Human-readable summary

    -- Trigger & Action
    trigger_conditions JSONB NOT NULL,   -- {"actor": "user_id", "risk": "<=MEDIUM"}
    action_template    JSONB NOT NULL,   -- {"action": "auto_execute", "skip_confirm": true}

    -- Confidence
    confidence      NUMERIC(3,2) DEFAULT 0.50,
    times_applied   INT DEFAULT 0,
    times_succeeded INT DEFAULT 0,
    times_overridden INT DEFAULT 0,

    -- Lifecycle
    learned_from    UUID[],             -- episode IDs
    status          TEXT NOT NULL DEFAULT 'active', -- active | superseded | disabled
    superseded_by   UUID REFERENCES procedural_memory(memory_id),

    created_at      TIMESTAMPTZ DEFAULT NOW(),
    last_applied_at TIMESTAMPTZ,
    updated_at      TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_proc_mem_active ON procedural_memory(workspace_id, confidence DESC)
    WHERE status = 'active';
CREATE INDEX idx_proc_mem_triggers ON procedural_memory
    USING GIN (trigger_conditions);

-- ============================================================
-- 14. CONSOLIDATION QUEUE (Post-session memory extraction)
-- ============================================================
CREATE TABLE consolidation_queue (
    queue_id        UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id      UUID NOT NULL REFERENCES sessions(session_id),
    workspace_id    UUID NOT NULL,
    conversation_text TEXT NOT NULL,
    task_results    JSONB,
    status          TEXT NOT NULL DEFAULT 'pending', -- pending | processing | completed | failed
    extracted_data  JSONB,              -- episodes + facts + procedures combined
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    processed_at    TIMESTAMPTZ
);

CREATE INDEX idx_consolidation_pending ON consolidation_queue(status)
    WHERE status = 'pending';

-- ============================================================
-- 15. MEMORY CHANGELOG (Audit trail for memory writes)
-- ============================================================
CREATE TABLE memory_changelog (
    changelog_id    UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    workspace_id    UUID NOT NULL,
    memory_type     TEXT NOT NULL,       -- episodic | semantic | procedural
    memory_id       UUID NOT NULL,
    operation       TEXT NOT NULL,       -- create | update | supersede | delete
    old_value       JSONB,
    new_value       JSONB,
    reason          TEXT,
    triggered_by    TEXT,                -- consolidation_pipeline | user_command | system_decay
    session_id      UUID,
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_memlog_workspace ON memory_changelog(workspace_id, created_at DESC);

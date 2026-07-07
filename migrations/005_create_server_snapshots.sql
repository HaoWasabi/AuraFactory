CREATE TABLE IF NOT EXISTS server_snapshots (
    guild_id BIGINT PRIMARY KEY,
    categories JSONB DEFAULT '[]',
    channels JSONB DEFAULT '[]',
    roles JSONB DEFAULT '[]',
    server_info JSONB DEFAULT '{}',
    snapshot_at TIMESTAMPTZ DEFAULT NOW(),
    stale_after TIMESTAMPTZ DEFAULT NOW() + INTERVAL '60 seconds'
);
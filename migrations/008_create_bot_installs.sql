CREATE TABLE IF NOT EXISTS bot_installs (
    guild_id BIGINT PRIMARY KEY,
    installed_by BIGINT,
    installed_at TIMESTAMPTZ DEFAULT NOW(),
    is_active BOOLEAN DEFAULT TRUE
);
CREATE TABLE IF NOT EXISTS users (
    discord_user_id BIGINT PRIMARY KEY,
    username VARCHAR(100),
    avatar_hash VARCHAR(100),
    access_token_enc TEXT,
    refresh_token_enc TEXT,
    token_expires_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    last_login_at TIMESTAMPTZ
);
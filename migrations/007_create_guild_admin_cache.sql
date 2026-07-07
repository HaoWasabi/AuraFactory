CREATE TABLE IF NOT EXISTS guild_admin_cache (
    user_id BIGINT REFERENCES users(discord_user_id),
    guild_id BIGINT NOT NULL,
    guild_name VARCHAR(100),
    is_owner BOOLEAN,
    permissions_bitfield BIGINT,
    cached_at TIMESTAMPTZ DEFAULT NOW(),
    PRIMARY KEY (user_id, guild_id)
);
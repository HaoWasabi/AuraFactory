CREATE TABLE IF NOT EXISTS rate_limits (
    user_id BIGINT NOT NULL,
    guild_id BIGINT NOT NULL,
    window_start TIMESTAMPTZ NOT NULL,
    request_count INT DEFAULT 1,
    PRIMARY KEY (user_id, guild_id, window_start)
);
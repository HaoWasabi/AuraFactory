-- Allow multiple sessions per user per guild (for chat history sidebar)
-- Drop the unique constraint that limited to 1 session per user/guild
ALTER TABLE sessions DROP CONSTRAINT IF EXISTS sessions_guild_id_user_id_key;

-- Add index for fast lookup by guild+user (non-unique)
CREATE INDEX IF NOT EXISTS idx_sessions_guild_user ON sessions(guild_id, user_id);

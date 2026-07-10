-- Migration 016: Chat Memory — session tracking enhancements
-- Adds discord_thread_id to sessions, session_id FK to messages,
-- and expands sessions to support multiple sessions per user per guild.

-- 1. Drop the UNIQUE(guild_id, user_id) constraint on sessions to allow multiple sessions
ALTER TABLE sessions
    DROP CONSTRAINT IF EXISTS sessions_guild_id_user_id_key;

-- 2. Add title + discord_thread_id to sessions
ALTER TABLE sessions
    ADD COLUMN IF NOT EXISTS title TEXT,
    ADD COLUMN IF NOT EXISTS discord_thread_id BIGINT,
    ADD COLUMN IF NOT EXISTS is_active BOOLEAN DEFAULT TRUE;

-- 3. Add session_id FK to messages (for grouping messages by session)
ALTER TABLE messages
    ADD COLUMN IF NOT EXISTS session_id UUID REFERENCES sessions(id) ON DELETE SET NULL;

-- 4. Indexes
CREATE INDEX IF NOT EXISTS idx_sessions_user_guild ON sessions(guild_id, user_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_sessions_thread ON sessions(discord_thread_id) WHERE discord_thread_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_messages_session ON messages(session_id, created_at);

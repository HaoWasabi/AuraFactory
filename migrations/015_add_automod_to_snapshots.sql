-- Migration 015: Add automod_rules column to server_snapshots
ALTER TABLE server_snapshots
    ADD COLUMN IF NOT EXISTS automod_rules JSONB DEFAULT '[]';

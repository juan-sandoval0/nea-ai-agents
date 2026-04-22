-- Migration 007: Add user_id to outreach_history
-- Phase 3.1: Thread Clerk user ID through outreach save path
-- Run in Supabase SQL Editor.
--
-- Scope:
--   Add user_id column to outreach_history to track which Clerk user
--   generated each outreach message (parallel to briefing_history.user_id)

-- =============================================================================
-- outreach_history: add user_id column
-- =============================================================================
ALTER TABLE outreach_history ADD COLUMN IF NOT EXISTS user_id TEXT;

-- Index for user-scoped queries
CREATE INDEX IF NOT EXISTS idx_outreach_history_user_id
  ON outreach_history(user_id);

-- Note: RLS policies will be updated in a future migration to filter by user_id

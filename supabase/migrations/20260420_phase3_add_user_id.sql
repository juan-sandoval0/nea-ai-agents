-- Phase 3.1: Add user_id columns for per-user tracking
-- Run this migration in Supabase SQL Editor

-- =============================================================================
-- ADD user_id COLUMNS
-- =============================================================================

-- Add user_id to briefing_history
ALTER TABLE briefing_history ADD COLUMN IF NOT EXISTS user_id TEXT;
CREATE INDEX IF NOT EXISTS idx_briefing_history_user_id ON briefing_history(user_id);

-- Add user_id to outreach_history
ALTER TABLE outreach_history ADD COLUMN IF NOT EXISTS user_id TEXT;
CREATE INDEX IF NOT EXISTS idx_outreach_history_user_id ON outreach_history(user_id);

-- =============================================================================
-- UPDATE RLS POLICIES (Optional - enable when ready for per-user isolation)
-- =============================================================================

-- NOTE: These policies are commented out by default.
-- Uncomment when you want to enforce per-user data isolation.
-- Service role will always bypass RLS.

/*
-- Drop existing public read policies
DROP POLICY IF EXISTS "Public read" ON briefing_history;
DROP POLICY IF EXISTS "Public read" ON outreach_history;

-- Create per-user read policies
CREATE POLICY "Users can read own briefings"
  ON briefing_history FOR SELECT
  USING (
    user_id IS NULL  -- Allow reading old records without user_id
    OR user_id = current_setting('request.jwt.claims', true)::json->>'sub'
  );

CREATE POLICY "Users can read own outreach"
  ON outreach_history FOR SELECT
  USING (
    user_id IS NULL  -- Allow reading old records without user_id
    OR user_id = current_setting('request.jwt.claims', true)::json->>'sub'
  );

-- Create insert policies
CREATE POLICY "Users can create own briefings"
  ON briefing_history FOR INSERT
  WITH CHECK (
    user_id = current_setting('request.jwt.claims', true)::json->>'sub'
  );

CREATE POLICY "Users can create own outreach"
  ON outreach_history FOR INSERT
  WITH CHECK (
    user_id = current_setting('request.jwt.claims', true)::json->>'sub'
  );
*/

-- =============================================================================
-- VERIFICATION QUERIES
-- =============================================================================

-- Verify columns were added:
-- SELECT column_name, data_type FROM information_schema.columns
-- WHERE table_name = 'briefing_history' AND column_name = 'user_id';

-- Check index exists:
-- SELECT indexname FROM pg_indexes WHERE tablename = 'briefing_history' AND indexname = 'idx_briefing_history_user_id';

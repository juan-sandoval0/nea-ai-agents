-- Migration: Add feedback tables for outreach continual learning
-- Run this in Supabase SQL Editor

-- =============================================================================
-- OUTREACH FEEDBACK (Phase 1 — collect investor edits)
-- =============================================================================
CREATE TABLE IF NOT EXISTS outreach_feedback (
  id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  outreach_id      TEXT,                    -- optional link to outreach_history
  investor_key     TEXT NOT NULL,
  company_id       TEXT,
  context_type     TEXT,
  original_message TEXT NOT NULL,
  edited_message   TEXT,                    -- NULL if just approved/rejected
  approval_status  TEXT NOT NULL CHECK (approval_status IN ('approved', 'edited', 'rejected')),
  investor_notes   TEXT,
  created_at       TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_outreach_feedback_investor ON outreach_feedback(investor_key);
CREATE INDEX IF NOT EXISTS idx_outreach_feedback_context  ON outreach_feedback(investor_key, context_type);
CREATE INDEX IF NOT EXISTS idx_outreach_feedback_status   ON outreach_feedback(approval_status);
CREATE INDEX IF NOT EXISTS idx_outreach_feedback_created  ON outreach_feedback(created_at DESC);

-- =============================================================================
-- INVESTOR LEARNED PREFERENCES (Phase 2 — pattern extraction, schema ready)
-- =============================================================================
CREATE TABLE IF NOT EXISTS investor_learned_preferences (
  id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  investor_key        TEXT NOT NULL,
  preference_text     TEXT NOT NULL,    -- bullet list of extracted rules
  derived_from_count  INT  DEFAULT 0,   -- number of edits this was built from
  version             INT  DEFAULT 1,
  is_active           BOOLEAN DEFAULT TRUE,
  created_at          TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_investor_prefs_key    ON investor_learned_preferences(investor_key);
CREATE INDEX IF NOT EXISTS idx_investor_prefs_active ON investor_learned_preferences(investor_key, is_active);

-- =============================================================================
-- ROW LEVEL SECURITY
-- =============================================================================
ALTER TABLE outreach_feedback ENABLE ROW LEVEL SECURITY;
ALTER TABLE investor_learned_preferences ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Public read"   ON outreach_feedback FOR SELECT USING (true);
CREATE POLICY "Public insert" ON outreach_feedback FOR INSERT WITH CHECK (true);

CREATE POLICY "Public read"   ON investor_learned_preferences FOR SELECT USING (true);
CREATE POLICY "Public insert" ON investor_learned_preferences FOR INSERT WITH CHECK (true);

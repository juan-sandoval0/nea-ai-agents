-- Migration 006: Close briefing schema gaps between SQLite and Supabase
-- Supports Phase 2 migration off SQLite onto Supabase.
-- Run in Supabase SQL Editor.
--
-- Scope:
--   1. Add missing columns to briefing_companies (arr_apr, investors, website_update, source_map)
--   2. Add missing column to briefing_news (source)
--   3. Create briefing_signals table (parity with SQLite key_signals)

-- =============================================================================
-- 1. briefing_companies: add missing CompanyCore fields
-- =============================================================================
ALTER TABLE briefing_companies ADD COLUMN IF NOT EXISTS arr_apr TEXT;
ALTER TABLE briefing_companies ADD COLUMN IF NOT EXISTS investors JSONB DEFAULT '[]'::jsonb;
ALTER TABLE briefing_companies ADD COLUMN IF NOT EXISTS website_update TEXT;
ALTER TABLE briefing_companies ADD COLUMN IF NOT EXISTS source_map JSONB DEFAULT '{}'::jsonb;

-- =============================================================================
-- 2. briefing_news: add source provenance
-- =============================================================================
ALTER TABLE briefing_news ADD COLUMN IF NOT EXISTS source TEXT DEFAULT 'news_api';

-- =============================================================================
-- 3. briefing_signals: new table mirroring SQLite key_signals
-- =============================================================================
CREATE TABLE IF NOT EXISTS briefing_signals (
  id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  company_id    TEXT NOT NULL,
  signal_type   TEXT NOT NULL,          -- hiring, traffic, funding, website_update
  description   TEXT NOT NULL,
  source        TEXT DEFAULT 'harmonic',
  observed_at   TIMESTAMPTZ DEFAULT now(),
  created_at    TIMESTAMPTZ DEFAULT now(),
  UNIQUE(company_id, signal_type, description)
);

CREATE INDEX IF NOT EXISTS idx_briefing_signals_company
  ON briefing_signals(company_id);
CREATE INDEX IF NOT EXISTS idx_briefing_signals_type
  ON briefing_signals(company_id, signal_type);

ALTER TABLE briefing_signals ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Public read" ON briefing_signals
  FOR SELECT USING (true);

CREATE POLICY "Service write" ON briefing_signals
  FOR ALL USING (true);

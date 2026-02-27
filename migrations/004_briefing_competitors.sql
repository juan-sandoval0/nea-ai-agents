-- Migration 004: Add briefing_competitors table
-- Stores top startup and incumbent competitors per company for meeting briefings.
-- Data is fetched from Harmonic's find_similar_companies endpoint during ingest.
--
-- Run in Supabase SQL editor.

CREATE TABLE IF NOT EXISTS briefing_competitors (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  company_id TEXT NOT NULL,
  competitor_name TEXT NOT NULL,
  competitor_domain TEXT,
  competitor_type TEXT NOT NULL DEFAULT 'startup', -- 'startup' or 'incumbent'
  description TEXT,
  funding_total REAL,
  funding_stage TEXT,
  funding_last_amount REAL,
  funding_last_date TEXT,
  headcount INTEGER,
  tags TEXT,
  harmonic_id TEXT,
  observed_at TIMESTAMPTZ DEFAULT now(),
  created_at TIMESTAMPTZ DEFAULT now(),
  UNIQUE(company_id, competitor_name)
);

CREATE INDEX IF NOT EXISTS idx_briefing_competitors_company
  ON briefing_competitors(company_id);

ALTER TABLE briefing_competitors ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Public read" ON briefing_competitors
  FOR SELECT USING (true);

CREATE POLICY "Service write" ON briefing_competitors
  FOR ALL USING (true);

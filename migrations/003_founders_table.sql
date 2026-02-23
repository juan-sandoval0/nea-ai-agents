-- Migration: Add founders table for Lovable UI access
-- Run this in Supabase SQL Editor

-- =============================================================================
-- FOUNDERS (key team members with enriched backgrounds)
-- =============================================================================
CREATE TABLE IF NOT EXISTS founders (
  id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  company_id   TEXT NOT NULL,              -- company domain/URL identifier
  company_name TEXT,                       -- denormalized for easier queries
  name         TEXT NOT NULL,
  role_title   TEXT,
  linkedin_url TEXT,
  background   TEXT,                       -- LLM-generated summary from Swarm
  source       TEXT DEFAULT 'harmonic',    -- 'harmonic', 'swarm', etc.
  observed_at  TIMESTAMPTZ DEFAULT now(),
  created_at   TIMESTAMPTZ DEFAULT now(),
  UNIQUE(company_id, name)                 -- prevent duplicates
);

CREATE INDEX IF NOT EXISTS idx_founders_company ON founders(company_id);
CREATE INDEX IF NOT EXISTS idx_founders_name ON founders(name);

-- =============================================================================
-- ROW LEVEL SECURITY
-- =============================================================================
ALTER TABLE founders ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Public read" ON founders FOR SELECT USING (true);

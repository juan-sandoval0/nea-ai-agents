-- NEA AI Agents - Supabase Schema
-- Run this in the Supabase SQL Editor to create all tables

-- =============================================================================
-- INVESTORS
-- =============================================================================
CREATE TABLE investors (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  name TEXT NOT NULL,
  email TEXT,
  slack_id TEXT,
  is_active BOOLEAN DEFAULT true,
  created_at TIMESTAMPTZ DEFAULT now()
);

-- =============================================================================
-- WATCHED COMPANIES (portfolio + competitors)
-- =============================================================================
CREATE TABLE watched_companies (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  company_id TEXT UNIQUE NOT NULL,
  company_name TEXT NOT NULL,
  category TEXT NOT NULL CHECK (category IN ('portfolio', 'competitor')),
  harmonic_id TEXT,
  parent_company_id UUID REFERENCES watched_companies(id),
  competitors_refreshed_at TIMESTAMPTZ,
  industry_tags JSONB DEFAULT '[]',
  is_active BOOLEAN DEFAULT true,
  added_at TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX idx_companies_category ON watched_companies(category);
CREATE INDEX idx_companies_parent ON watched_companies(parent_company_id);

-- =============================================================================
-- INVESTOR-COMPANY JUNCTION
-- =============================================================================
CREATE TABLE investor_companies (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  investor_id UUID REFERENCES investors(id) ON DELETE CASCADE,
  company_id UUID REFERENCES watched_companies(id) ON DELETE CASCADE,
  added_at TIMESTAMPTZ DEFAULT now(),
  UNIQUE(investor_id, company_id)
);

-- =============================================================================
-- COMPANY SIGNALS
-- =============================================================================
CREATE TABLE company_signals (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  company_id UUID REFERENCES watched_companies(id) ON DELETE CASCADE,
  signal_type TEXT NOT NULL,
  headline TEXT NOT NULL,
  description TEXT,
  source_url TEXT,
  source_name TEXT,
  published_date DATE,
  relevance_score INTEGER DEFAULT 0,
  score_breakdown JSONB,
  raw_data JSONB,
  sentiment TEXT CHECK (sentiment IN ('positive', 'negative', 'neutral')),
  synopsis TEXT,
  detected_at TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX idx_signals_company ON company_signals(company_id);
CREATE INDEX idx_signals_type ON company_signals(signal_type);
CREATE INDEX idx_signals_score ON company_signals(relevance_score DESC);
CREATE INDEX idx_signals_detected ON company_signals(detected_at DESC);

-- =============================================================================
-- EMPLOYEE SNAPSHOTS
-- =============================================================================
CREATE TABLE employee_snapshots (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  company_id UUID REFERENCES watched_companies(id) ON DELETE CASCADE,
  snapshot_date DATE DEFAULT CURRENT_DATE,
  employees JSONB NOT NULL,
  created_at TIMESTAMPTZ DEFAULT now()
);

-- =============================================================================
-- BRIEFING HISTORY
-- =============================================================================
CREATE TABLE briefing_history (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  company_id TEXT NOT NULL,
  company_name TEXT NOT NULL,
  created_at TIMESTAMPTZ DEFAULT now(),
  markdown TEXT,
  success BOOLEAN DEFAULT true,
  error TEXT,
  data_sources JSONB
);

CREATE INDEX idx_briefings_company ON briefing_history(company_id);
CREATE INDEX idx_briefings_created ON briefing_history(created_at DESC);

-- =============================================================================
-- DIGEST HISTORY (news aggregator runs)
-- =============================================================================
CREATE TABLE digest_history (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  generated_at TIMESTAMPTZ DEFAULT now(),
  story_count INTEGER DEFAULT 0,
  portfolio_count INTEGER DEFAULT 0,
  competitor_count INTEGER DEFAULT 0,
  top_stories_summary TEXT,
  investor_filter TEXT,
  success BOOLEAN DEFAULT true,
  error TEXT
);

CREATE INDEX idx_digest_history_generated ON digest_history(generated_at DESC);

-- =============================================================================
-- OUTREACH HISTORY (outreach agent messages)
-- =============================================================================
CREATE TABLE outreach_history (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  company_id TEXT NOT NULL,
  company_name TEXT NOT NULL,
  contact_name TEXT NOT NULL,
  investor_key TEXT NOT NULL,
  context_type TEXT NOT NULL,
  output_format TEXT NOT NULL,
  created_at TIMESTAMPTZ DEFAULT now(),
  message_preview TEXT,
  full_message TEXT,
  model TEXT,
  tokens_total INTEGER DEFAULT 0,
  latency_ms INTEGER DEFAULT 0,
  success BOOLEAN DEFAULT true,
  error TEXT
);

CREATE INDEX idx_outreach_company ON outreach_history(company_id);
CREATE INDEX idx_outreach_investor ON outreach_history(investor_key);
CREATE INDEX idx_outreach_created ON outreach_history(created_at DESC);

-- =============================================================================
-- AUDIT LOGS (all agents)
-- =============================================================================
CREATE TABLE audit_logs (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  created_at TIMESTAMPTZ DEFAULT now(),
  agent TEXT NOT NULL,
  event_type TEXT NOT NULL,
  action TEXT NOT NULL,
  resource_type TEXT,
  resource_id TEXT,
  actor TEXT,
  details JSONB DEFAULT '{}',
  request_id TEXT
);

CREATE INDEX idx_audit_agent ON audit_logs(agent);
CREATE INDEX idx_audit_event_type ON audit_logs(event_type);
CREATE INDEX idx_audit_created ON audit_logs(created_at DESC);

-- =============================================================================
-- JOB RUNS (track agent execution status for UI)
-- =============================================================================
CREATE TABLE job_runs (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  agent_type TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'running', 'completed', 'failed')),
  created_at TIMESTAMPTZ DEFAULT now(),
  started_at TIMESTAMPTZ,
  completed_at TIMESTAMPTZ,
  error TEXT,
  result_summary JSONB DEFAULT '{}',
  triggered_by TEXT DEFAULT 'api'
);

CREATE INDEX idx_job_runs_status ON job_runs(status);
CREATE INDEX idx_job_runs_agent ON job_runs(agent_type);
CREATE INDEX idx_job_runs_created ON job_runs(created_at DESC);

-- =============================================================================
-- STORIES (cached digest stories)
-- =============================================================================
CREATE TABLE stories (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  story_id TEXT UNIQUE NOT NULL,
  primary_url TEXT NOT NULL,
  primary_title TEXT NOT NULL,
  other_urls JSONB DEFAULT '[]',
  classification TEXT DEFAULT 'GENERAL',
  sentiment_label TEXT DEFAULT 'Neutral',
  sentiment_score INTEGER DEFAULT 0,
  sentiment_keywords JSONB DEFAULT '[]',
  synopsis TEXT,
  company_id TEXT,
  company_name TEXT,
  company_category TEXT,
  parent_company_name TEXT,
  industry_tags JSONB DEFAULT '[]',
  priority_score REAL DEFAULT 0,
  priority_reasons JSONB DEFAULT '[]',
  published_date TEXT,
  max_engagement INTEGER DEFAULT 0,
  source_count INTEGER DEFAULT 0,
  article_signal_ids JSONB DEFAULT '[]',
  digest_generated_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX idx_stories_digest ON stories(digest_generated_at DESC);
CREATE INDEX idx_stories_company ON stories(company_id);
CREATE INDEX idx_stories_classification ON stories(classification);
CREATE INDEX idx_stories_priority ON stories(priority_score DESC);

-- =============================================================================
-- STORY CLUSTERS (for investor digest)
-- =============================================================================
CREATE TABLE story_clusters (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  cluster_key TEXT UNIQUE NOT NULL,
  title TEXT NOT NULL,
  summary TEXT,
  signal_ids JSONB DEFAULT '[]',
  company_ids JSONB DEFAULT '[]',
  primary_signal_type TEXT,
  sentiment TEXT,
  relevance_score INTEGER DEFAULT 0,
  created_at TIMESTAMPTZ DEFAULT now(),
  updated_at TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX idx_clusters_created ON story_clusters(created_at DESC);

-- =============================================================================
-- FOUNDERS (key team members with enriched backgrounds)
-- =============================================================================
CREATE TABLE founders (
  id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  company_id   TEXT NOT NULL,
  company_name TEXT,
  name         TEXT NOT NULL,
  role_title   TEXT,
  linkedin_url TEXT,
  background   TEXT,
  source       TEXT DEFAULT 'harmonic',
  observed_at  TIMESTAMPTZ DEFAULT now(),
  created_at   TIMESTAMPTZ DEFAULT now(),
  UNIQUE(company_id, name)
);

CREATE INDEX idx_founders_company ON founders(company_id);
CREATE INDEX idx_founders_name ON founders(name);

-- =============================================================================
-- ROW LEVEL SECURITY
-- =============================================================================

-- Enable RLS on all tables
ALTER TABLE watched_companies ENABLE ROW LEVEL SECURITY;
ALTER TABLE company_signals ENABLE ROW LEVEL SECURITY;
ALTER TABLE investors ENABLE ROW LEVEL SECURITY;
ALTER TABLE investor_companies ENABLE ROW LEVEL SECURITY;
ALTER TABLE briefing_history ENABLE ROW LEVEL SECURITY;
ALTER TABLE employee_snapshots ENABLE ROW LEVEL SECURITY;
ALTER TABLE story_clusters ENABLE ROW LEVEL SECURITY;
ALTER TABLE stories ENABLE ROW LEVEL SECURITY;
ALTER TABLE digest_history ENABLE ROW LEVEL SECURITY;
ALTER TABLE outreach_history ENABLE ROW LEVEL SECURITY;
ALTER TABLE audit_logs ENABLE ROW LEVEL SECURITY;
ALTER TABLE job_runs ENABLE ROW LEVEL SECURITY;
ALTER TABLE founders ENABLE ROW LEVEL SECURITY;

-- Public read access (for Lovable with anon key)
CREATE POLICY "Public read" ON watched_companies FOR SELECT USING (true);
CREATE POLICY "Public read" ON company_signals FOR SELECT USING (true);
CREATE POLICY "Public read" ON briefing_history FOR SELECT USING (true);
CREATE POLICY "Public read" ON story_clusters FOR SELECT USING (true);
CREATE POLICY "Public read" ON investors FOR SELECT USING (true);
CREATE POLICY "Public read" ON stories FOR SELECT USING (true);
CREATE POLICY "Public read" ON digest_history FOR SELECT USING (true);
CREATE POLICY "Public read" ON outreach_history FOR SELECT USING (true);
CREATE POLICY "Public read" ON audit_logs FOR SELECT USING (true);
CREATE POLICY "Public read" ON job_runs FOR SELECT USING (true);
CREATE POLICY "Public read" ON founders FOR SELECT USING (true);

-- Service role (used by Python CLI) bypasses RLS automatically

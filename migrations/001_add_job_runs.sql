-- Migration: Add job_runs table for tracking agent execution status
-- Run this in Supabase SQL Editor

-- =============================================================================
-- JOB RUNS (track agent execution status for UI)
-- =============================================================================
CREATE TABLE IF NOT EXISTS job_runs (
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

CREATE INDEX IF NOT EXISTS idx_job_runs_status ON job_runs(status);
CREATE INDEX IF NOT EXISTS idx_job_runs_agent ON job_runs(agent_type);
CREATE INDEX IF NOT EXISTS idx_job_runs_created ON job_runs(created_at DESC);

-- Enable RLS
ALTER TABLE job_runs ENABLE ROW LEVEL SECURITY;

-- Public read access (for Lovable with anon key)
CREATE POLICY "Public read" ON job_runs FOR SELECT USING (true);

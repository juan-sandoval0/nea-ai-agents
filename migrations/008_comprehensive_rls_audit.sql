-- Migration 008: Comprehensive RLS Audit & User-Scoped Policies
-- Phase 3 Security: Enforce row-level security across all tables
-- Run in Supabase SQL Editor.
--
-- Scope:
--   1. Add missing RLS to core data tables
--   2. Create user-scoped policies for history tables (briefing_history, outreach_history)
--   3. Ensure proper service_role access for system operations
--   4. Audit and tighten existing policies

-- =============================================================================
-- PART 1: CORE DATA TABLES (Public Read + Service Write)
-- =============================================================================

-- briefing_companies: Company profile data
ALTER TABLE briefing_companies ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Public read" ON briefing_companies
  FOR SELECT USING (true);

CREATE POLICY "Service write" ON briefing_companies
  FOR ALL USING (auth.role() = 'service_role');

-- briefing_news: News articles for companies
ALTER TABLE briefing_news ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Public read" ON briefing_news
  FOR SELECT USING (true);

CREATE POLICY "Service write" ON briefing_news
  FOR ALL USING (auth.role() = 'service_role');

-- =============================================================================
-- PART 2: HISTORY TABLES (User-Scoped Access)
-- =============================================================================

-- briefing_history: User-generated briefings
-- Each user should only see their own briefings (via user_id column from Phase 3.1)
ALTER TABLE briefing_history ENABLE ROW LEVEL SECURITY;

-- Allow users to read their own briefings
-- NOTE: This assumes authenticated users have auth.uid() matching user_id (Clerk sub claim)
-- For anonymous/pre-Clerk records (user_id IS NULL), fall back to public read
CREATE POLICY "Users read own briefings" ON briefing_history
  FOR SELECT USING (
    user_id IS NULL OR user_id = auth.uid()::text
  );

-- Allow service role full access (for cleanup, admin operations)
CREATE POLICY "Service full access" ON briefing_history
  FOR ALL USING (auth.role() = 'service_role');

-- Allow authenticated users to insert their own briefings
CREATE POLICY "Users insert own briefings" ON briefing_history
  FOR INSERT WITH CHECK (
    user_id = auth.uid()::text OR auth.role() = 'service_role'
  );

-- outreach_history: User-generated outreach messages
-- Same user-scoped pattern as briefing_history
ALTER TABLE outreach_history ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Users read own outreach" ON outreach_history
  FOR SELECT USING (
    user_id IS NULL OR user_id = auth.uid()::text
  );

CREATE POLICY "Service full access" ON outreach_history
  FOR ALL USING (auth.role() = 'service_role');

CREATE POLICY "Users insert own outreach" ON outreach_history
  FOR INSERT WITH CHECK (
    user_id = auth.uid()::text OR auth.role() = 'service_role'
  );

-- digest_history: System-generated digests (not user-scoped yet)
-- TODO: Add user_id column in future migration if digests become per-user
ALTER TABLE digest_history ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Public read" ON digest_history
  FOR SELECT USING (true);

CREATE POLICY "Service write" ON digest_history
  FOR ALL USING (auth.role() = 'service_role');

-- audit_logs: System audit trail (admin/service access only)
ALTER TABLE audit_logs ENABLE ROW LEVEL SECURITY;

-- Only service role can read audit logs (sensitive)
CREATE POLICY "Service full access" ON audit_logs
  FOR ALL USING (auth.role() = 'service_role');

-- =============================================================================
-- PART 3: NEWS AGGREGATOR TABLES (Service-Only)
-- =============================================================================

-- watched_companies: Portfolio & competitor watchlist
ALTER TABLE watched_companies ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Public read" ON watched_companies
  FOR SELECT USING (true);

CREATE POLICY "Service write" ON watched_companies
  FOR ALL USING (auth.role() = 'service_role');

-- investors: Investor profiles
ALTER TABLE investors ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Public read" ON investors
  FOR SELECT USING (true);

CREATE POLICY "Service write" ON investors
  FOR ALL USING (auth.role() = 'service_role');

-- investor_companies: Many-to-many link table
ALTER TABLE investor_companies ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Public read" ON investor_companies
  FOR SELECT USING (true);

CREATE POLICY "Service write" ON investor_companies
  FOR ALL USING (auth.role() = 'service_role');

-- company_signals: Detected signals (funding, hiring, etc.)
ALTER TABLE company_signals ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Public read" ON company_signals
  FOR SELECT USING (true);

CREATE POLICY "Service write" ON company_signals
  FOR ALL USING (auth.role() = 'service_role');

-- employee_snapshots: Headcount tracking over time
ALTER TABLE employee_snapshots ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Public read" ON employee_snapshots
  FOR SELECT USING (true);

CREATE POLICY "Service write" ON employee_snapshots
  FOR ALL USING (auth.role() = 'service_role');

-- stories: News digest stories
ALTER TABLE stories ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Public read" ON stories
  FOR SELECT USING (true);

CREATE POLICY "Service write" ON stories
  FOR ALL USING (auth.role() = 'service_role');

-- =============================================================================
-- PART 4: TIGHTEN EXISTING POLICIES (OPTIONAL CLEANUP)
-- =============================================================================

-- outreach_feedback: Currently "Public insert" — should restrict to authenticated users
-- Drop existing overly-permissive policy
DROP POLICY IF EXISTS "Public insert" ON outreach_feedback;

-- Replace with authenticated-only insert
CREATE POLICY "Authenticated insert" ON outreach_feedback
  FOR INSERT WITH CHECK (
    auth.role() = 'authenticated' OR auth.role() = 'service_role'
  );

-- investor_learned_preferences: Same tightening
DROP POLICY IF EXISTS "Public insert" ON investor_learned_preferences;

CREATE POLICY "Authenticated insert" ON investor_learned_preferences
  FOR INSERT WITH CHECK (
    auth.role() = 'authenticated' OR auth.role() = 'service_role'
  );

-- =============================================================================
-- VERIFICATION QUERIES (Run these after migration to test)
-- =============================================================================

-- Check all tables have RLS enabled:
-- SELECT tablename, rowsecurity
-- FROM pg_tables
-- WHERE schemaname = 'public'
-- ORDER BY tablename;

-- List all policies:
-- SELECT schemaname, tablename, policyname, permissive, roles, cmd, qual
-- FROM pg_policies
-- WHERE schemaname = 'public'
-- ORDER BY tablename, policyname;

-- Test user-scoped access (requires a valid Clerk JWT):
-- SET request.jwt.claims TO '{"sub": "user_abc123"}';
-- SELECT * FROM briefing_history; -- Should only see user_abc123's records
-- SELECT * FROM outreach_history; -- Should only see user_abc123's records

-- =============================================================================
-- NOTES
-- =============================================================================

-- 1. User-scoped policies assume auth.uid() returns the Clerk user ID (sub claim)
--    This is standard when using Supabase's JWT authentication with external providers.
--
-- 2. Anonymous records (user_id IS NULL) remain readable for backward compatibility
--    with pre-Phase 3.1 data. Consider backfilling user_id for old records if needed.
--
-- 3. Service role (SUPABASE_SERVICE_KEY) bypasses RLS entirely, so backend code
--    using service_role credentials can still perform all operations.
--
-- 4. For local development without Clerk, you may need to temporarily set
--    USE_CLERK_AUTH=false and rely on service_role access only.
--
-- 5. Tables NOT covered by this migration (already have RLS from prior migrations):
--    - job_runs (migration 001)
--    - outreach_feedback (migration 002, tightened here)
--    - investor_learned_preferences (migration 002, tightened here)
--    - founders (migration 003)
--    - briefing_competitors (migration 004)
--    - nea_portfolio (migration 005)
--    - briefing_signals (migration 006)

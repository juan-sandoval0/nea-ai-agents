-- Supabase RLS Verification Script
-- Run this in Supabase SQL Editor after applying migration 008
-- to verify all tables have proper RLS policies configured.

-- =============================================================================
-- CHECK 1: All tables have RLS enabled
-- =============================================================================
SELECT
  tablename,
  rowsecurity,
  CASE
    WHEN rowsecurity THEN '✅ Enabled'
    ELSE '❌ MISSING'
  END as status
FROM pg_tables
WHERE schemaname = 'public'
  AND tablename NOT LIKE 'pg_%'
  AND tablename NOT LIKE 'sql_%'
ORDER BY rowsecurity DESC, tablename;

-- Expected: All tables should show rowsecurity = true

-- =============================================================================
-- CHECK 2: Policy inventory per table
-- =============================================================================
SELECT
  tablename,
  COUNT(*) as policy_count,
  string_agg(policyname, ', ' ORDER BY policyname) as policies
FROM pg_policies
WHERE schemaname = 'public'
GROUP BY tablename
ORDER BY tablename;

-- Expected counts:
-- briefing_history: 3 policies (read own, insert own, service full)
-- outreach_history: 3 policies (read own, insert own, service full)
-- audit_logs: 1 policy (service only)
-- Most data tables: 2 policies (public read, service write)

-- =============================================================================
-- CHECK 3: Detailed policy listing
-- =============================================================================
SELECT
  tablename,
  policyname,
  cmd as operation,
  roles,
  permissive,
  substring(qual::text, 1, 80) as condition
FROM pg_policies
WHERE schemaname = 'public'
ORDER BY tablename, policyname;

-- =============================================================================
-- CHECK 4: Find tables WITHOUT RLS enabled
-- =============================================================================
SELECT tablename
FROM pg_tables
WHERE schemaname = 'public'
  AND rowsecurity = false
  AND tablename NOT LIKE 'pg_%'
  AND tablename NOT LIKE 'sql_%';

-- Expected: ZERO rows (all tables should have RLS)

-- =============================================================================
-- CHECK 5: Find overly-permissive policies
-- =============================================================================
-- Look for policies that allow unrestricted access
SELECT
  tablename,
  policyname,
  cmd,
  qual::text as condition
FROM pg_policies
WHERE schemaname = 'public'
  AND (
    qual::text = 'true'  -- Unrestricted
    OR qual IS NULL       -- No condition
  )
  AND policyname NOT LIKE '%Service%'  -- Exclude service role policies
ORDER BY tablename, policyname;

-- Expected: Only "Public read" policies should appear (safe for data tables)
-- History tables should NOT appear here (they should be user-scoped)

-- =============================================================================
-- CHECK 6: User-scoped tables have proper policies
-- =============================================================================
SELECT
  tablename,
  policyname,
  cmd,
  CASE
    WHEN qual::text LIKE '%auth.uid()%' THEN '✅ User-scoped'
    WHEN qual::text LIKE '%service_role%' THEN '✅ Service role'
    ELSE '⚠️ Check policy'
  END as policy_type
FROM pg_policies
WHERE schemaname = 'public'
  AND tablename IN ('briefing_history', 'outreach_history')
ORDER BY tablename, policyname;

-- Expected:
-- briefing_history:
--   - "Users read own briefings" → User-scoped (auth.uid())
--   - "Users insert own briefings" → User-scoped (auth.uid())
--   - "Service full access" → Service role
-- outreach_history: same pattern

-- =============================================================================
-- CHECK 7: Simulate user-scoped access (OPTIONAL - requires Clerk user ID)
-- =============================================================================
-- Uncomment and replace 'user_abc123' with a real Clerk user ID to test

-- SET request.jwt.claims TO '{"sub": "user_abc123"}';
--
-- -- Should only return records where user_id = 'user_abc123' or user_id IS NULL
-- SELECT id, company_name, user_id, created_at
-- FROM briefing_history
-- ORDER BY created_at DESC
-- LIMIT 10;
--
-- SELECT id, company_name, user_id, created_at
-- FROM outreach_history
-- ORDER BY created_at DESC
-- LIMIT 10;
--
-- RESET request.jwt.claims;

-- =============================================================================
-- CHECK 8: Service role bypass test
-- =============================================================================
-- Verify that service role can still see all records
-- (This test assumes you're running as service role in SQL Editor)

SELECT
  'briefing_history' as table_name,
  COUNT(*) as total_records,
  COUNT(CASE WHEN user_id IS NOT NULL THEN 1 END) as with_user_id,
  COUNT(CASE WHEN user_id IS NULL THEN 1 END) as anonymous
FROM briefing_history

UNION ALL

SELECT
  'outreach_history' as table_name,
  COUNT(*) as total_records,
  COUNT(CASE WHEN user_id IS NOT NULL THEN 1 END) as with_user_id,
  COUNT(CASE WHEN user_id IS NULL THEN 1 END) as anonymous
FROM outreach_history;

-- Expected: Service role should see ALL records (RLS bypassed)

-- =============================================================================
-- SUMMARY
-- =============================================================================
-- If all checks pass:
-- ✅ All tables have RLS enabled
-- ✅ User-scoped tables have auth.uid() policies
-- ✅ Data tables have public read + service write
-- ✅ Service role can bypass RLS
-- ✅ No overly-permissive policies on sensitive tables
--
-- Migration 008 is successfully deployed!

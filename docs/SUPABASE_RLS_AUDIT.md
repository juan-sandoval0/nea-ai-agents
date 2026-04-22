# Supabase RLS Security Audit

**Phase 3 Security Requirement**: Comprehensive Row-Level Security audit and remediation.

---

## Executive Summary

**Status**: Migration ready for deployment ✅

**Findings**:
- **15 tables** audited across all agents (briefing, news aggregator, outreach)
- **7 tables** had no RLS enabled (security gap)
- **2 user-scoped tables** (briefing_history, outreach_history) need user_id filtering
- **2 feedback tables** had overly-permissive "Public insert" policies

**Remediation**: Migration 008 created to:
1. Enable RLS on 7 missing tables
2. Add user-scoped policies for history tables
3. Tighten feedback table policies (authenticated users only)
4. Ensure service_role retains full access for backend operations

---

## Table Inventory

### History Tables (User-Scoped)

| Table | RLS Before | User Column | Policy Type |
|-------|-----------|-------------|-------------|
| `briefing_history` | ❌ Missing | `user_id` (Phase 3.1) | User-scoped read/insert |
| `outreach_history` | ❌ Missing | `user_id` (Migration 007) | User-scoped read/insert |
| `digest_history` | ❌ Missing | None (system-generated) | Public read, service write |
| `audit_logs` | ❌ Missing | N/A (admin only) | Service-only (sensitive) |

**Risk**: Without RLS, any authenticated user could read all briefings/outreach from all users.

### Core Data Tables (Public Read + Service Write)

| Table | RLS Before | New Policy |
|-------|-----------|-----------|
| `briefing_companies` | ❌ Missing | Public read, service write |
| `briefing_news` | ❌ Missing | Public read, service write |
| `briefing_signals` | ✅ Migration 006 | Already secure |
| `briefing_competitors` | ✅ Migration 004 | Already secure |
| `founders` | ✅ Migration 003 | Already secure |

**Risk**: Low (these are lookup/reference data, not user-sensitive).

### News Aggregator Tables (Public Read + Service Write)

| Table | RLS Before | New Policy |
|-------|-----------|-----------|
| `watched_companies` | ❌ Missing | Public read, service write |
| `investors` | ❌ Missing | Public read, service write |
| `investor_companies` | ❌ Missing | Public read, service write |
| `company_signals` | ❌ Missing | Public read, service write |
| `employee_snapshots` | ❌ Missing | Public read, service write |
| `stories` | ❌ Missing | Public read, service write |

**Risk**: Low (watchlist and signals are shared across the team).

### Feedback Tables (Authenticated Insert)

| Table | RLS Before | Issue | Fix |
|-------|-----------|-------|-----|
| `outreach_feedback` | ⚠️ Public insert | Allows anonymous writes | Require authenticated role |
| `investor_learned_preferences` | ⚠️ Public insert | Allows anonymous writes | Require authenticated role |

**Risk**: Medium (potential spam/abuse from public inserts).

### Job Tracking Tables

| Table | RLS Before | Policy |
|-------|-----------|--------|
| `job_runs` | ✅ Migration 001 | Already secure |
| `nea_portfolio` | ✅ Migration 005 | Already secure |

---

## Migration 008: RLS Remediation

**File**: `migrations/008_comprehensive_rls_audit.sql`

### Part 1: Core Data Tables
- Enable RLS on `briefing_companies`, `briefing_news`
- Policy: Public read, service write

### Part 2: History Tables (User-Scoped)
- Enable RLS on `briefing_history`, `outreach_history`, `digest_history`, `audit_logs`
- Policy for briefing/outreach:
  - Users can read/insert their own records (`user_id = auth.uid()`)
  - Fallback: NULL user_id records remain public (backward compatibility)
  - Service role has full access (bypasses RLS)
- Policy for digest_history: Public read, service write (not yet user-scoped)
- Policy for audit_logs: Service-only (sensitive)

### Part 3: News Aggregator Tables
- Enable RLS on 6 tables (watched_companies, investors, company_signals, etc.)
- Policy: Public read, service write

### Part 4: Tighten Feedback Tables
- Drop overly-permissive "Public insert" policies
- Replace with "Authenticated insert" (requires `auth.role() = 'authenticated'`)

---

## Deployment Steps

### 1. Backup (Precaution)
```bash
# Supabase dashboard → Database → Backups → Manual Backup
# Or use pg_dump if you have direct database access
```

### 2. Run Migration
```sql
-- Copy and paste migrations/008_comprehensive_rls_audit.sql into:
-- Supabase dashboard → SQL Editor → New Query
-- Click "Run"
```

### 3. Verification Queries

**Check all tables have RLS enabled:**
```sql
SELECT tablename, rowsecurity
FROM pg_tables
WHERE schemaname = 'public'
ORDER BY tablename;
```

Expected: All tables should have `rowsecurity = true`.

**List all policies:**
```sql
SELECT schemaname, tablename, policyname, permissive, roles, cmd
FROM pg_policies
WHERE schemaname = 'public'
ORDER BY tablename, policyname;
```

**Test user-scoped access** (requires valid Clerk JWT):
```sql
-- Simulate authenticated user (replace with real Clerk user ID)
SET request.jwt.claims TO '{"sub": "user_abc123"}';

-- Should only see records where user_id = 'user_abc123' or user_id IS NULL
SELECT id, company_name, user_id FROM briefing_history;
SELECT id, company_name, user_id FROM outreach_history;

-- Reset
RESET request.jwt.claims;
```

### 4. Frontend Testing

After migration, test in production:

1. **Generate a briefing** (should save with user_id)
   - Check Supabase: `SELECT * FROM briefing_history ORDER BY created_at DESC LIMIT 1;`
   - Verify `user_id` column is populated

2. **Generate outreach** (should save with user_id)
   - Check Supabase: `SELECT * FROM outreach_history ORDER BY created_at DESC LIMIT 1;`
   - Verify `user_id` column is populated

3. **List briefings** (should only show current user's records)
   - Log in as User A → generate briefing
   - Log in as User B → should NOT see User A's briefing
   - Log out → should only see public/NULL user_id briefings

4. **Submit outreach feedback** (should require authentication)
   - Try submitting feedback while logged out → should fail with 401
   - Log in → should succeed

---

## Security Considerations

### ✅ Good
- **User-scoped history**: Users can only see their own briefings/outreach
- **Service role bypass**: Backend code (using SUPABASE_SERVICE_KEY) retains full access for system operations
- **Backward compatibility**: Pre-Phase 3.1 records (user_id IS NULL) remain accessible during transition

### ⚠️ Limitations
- **Public read on data tables**: Company profiles, news, signals are readable by anyone
  - **Justification**: These are not user-sensitive; they're lookup data
  - **Future**: Consider restricting to authenticated users if needed

- **Anonymous briefing/outreach access**: Records with user_id IS NULL are publicly readable
  - **Mitigation**: Backfill user_id for historical records, or delete anonymous records

- **Service role is all-powerful**: Any code with SUPABASE_SERVICE_KEY can bypass RLS
  - **Mitigation**: Protect service key, audit backend code carefully

### 🔒 Recommendations
1. **Backfill user_id**: Update historical briefing_history/outreach_history records with user_id if possible
2. **Monitor anonymous inserts**: Alert if new records have user_id IS NULL (indicates auth bypass)
3. **Regular policy audits**: Re-run verification queries quarterly
4. **Rate limiting**: Already implemented (Phase 3) - keep monitoring

---

## Rollback Plan

If migration causes issues:

```sql
-- Disable RLS on affected tables (restore to pre-migration state)
ALTER TABLE briefing_history DISABLE ROW LEVEL SECURITY;
ALTER TABLE outreach_history DISABLE ROW LEVEL SECURITY;
ALTER TABLE digest_history DISABLE ROW LEVEL SECURITY;
ALTER TABLE audit_logs DISABLE ROW LEVEL SECURITY;
ALTER TABLE briefing_companies DISABLE ROW LEVEL SECURITY;
ALTER TABLE briefing_news DISABLE ROW LEVEL SECURITY;
ALTER TABLE watched_companies DISABLE ROW LEVEL SECURITY;
ALTER TABLE investors DISABLE ROW LEVEL SECURITY;
ALTER TABLE investor_companies DISABLE ROW LEVEL SECURITY;
ALTER TABLE company_signals DISABLE ROW LEVEL SECURITY;
ALTER TABLE employee_snapshots DISABLE ROW LEVEL SECURITY;
ALTER TABLE stories DISABLE ROW LEVEL SECURITY;

-- Restore old feedback policies (if needed)
DROP POLICY IF EXISTS "Authenticated insert" ON outreach_feedback;
CREATE POLICY "Public insert" ON outreach_feedback FOR INSERT WITH CHECK (true);

DROP POLICY IF EXISTS "Authenticated insert" ON investor_learned_preferences;
CREATE POLICY "Public insert" ON investor_learned_preferences FOR INSERT WITH CHECK (true);
```

---

## Next Steps

1. ✅ **Review this audit** - Confirm table inventory and policy design
2. ⏳ **Deploy migration 008** - Run in Supabase SQL Editor
3. ⏳ **Run verification queries** - Confirm RLS enabled and policies active
4. ⏳ **Test in production** - Generate briefings/outreach, verify user_id scoping
5. ⏳ **Monitor logs** - Watch for 401/403 errors indicating policy issues
6. 📅 **Future**: Consider adding user_id to digest_history for per-user digests

---

## Related Tasks

- **Task #1**: ✅ Fix outreach user_id bug (commit e6b2b94)
- **Task #8**: 🔄 Supabase RLS audit (this document)
- **Task #9**: ⏳ Rotate GitHub PAT
- **Task #10**: ⏳ Rotate Databricks PAT

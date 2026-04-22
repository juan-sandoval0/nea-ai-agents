# Phase 4 Cleanup Checklist

Post-migration infrastructure cleanup after Railway → Vercel migration (Phase 2.7).

---

## ✅ Completed

- [x] **Task #1**: Fix outreach user_id bug (commit e6b2b94)
- [x] **Task #2**: Fix LangSmith 403 errors (commit 26af08a + manual Vercel env cleanup)
- [x] **Task #5**: Delete frontend API catchall route (commit 3ab4107)

---

## 🔧 Manual Tasks Remaining

### Task #3: Shut Down Railway Service

**Status**: Railway backend decommissioned in Phase 2.7, but service still running

**Steps**:
1. Log into Railway dashboard: https://railway.app/dashboard
2. Find the `nea-ai-agents` project
3. Click on the service/deployment
4. Go to **Settings** → **Danger Zone**
5. Click **Delete Service**
6. Confirm deletion

**Verification**:
- Service no longer appears in Railway dashboard
- No production traffic pointing to Railway URLs
- All /api/* requests handled by Vercel Functions

---

### Task #4: Remove BACKEND_URL from Vercel

**Status**: Env var obsolete now that vercel.json rewrites handle all routing

**Steps**:
1. Go to Vercel dashboard: https://vercel.com/dashboard
2. Select `nea-ai-agents` project
3. Click **Settings** → **Environment Variables**
4. Search for `BACKEND_URL`
5. If found, click **⋮** → **Remove**
6. Confirm removal

**Verification**:
```bash
# Check if BACKEND_URL is referenced anywhere in code
grep -r "BACKEND_URL" --exclude-dir=node_modules --exclude-dir=.git .

# Should only find:
# - This checklist
# - README.md (documentation)
# - Possibly frontend/app/api/[...path]/route.ts comments (deleted in Task #5)
```

**Note**: No redeploy needed - this env var is no longer referenced after Task #5.

---

### Task #6: Archive Old Lovable Repo

**Status**: Original Lovable repo is inactive

**Steps**:
1. Navigate to the Lovable repo on GitHub
   - (URL: ask team for the exact repo URL)
2. Click **Settings** (requires admin access)
3. Scroll to bottom → **Danger Zone**
4. Click **Archive this repository**
5. Confirm: Type repo name and click **Archive**

**Effect**:
- Repo becomes read-only
- No more commits, issues, or PRs
- Still visible for reference
- Can be unarchived if needed

---

### Task #7: Delete Stale Vercel Projects

**Status**: Two old projects from early development are no longer used

**Projects to delete**:
1. `nea-ai-frontend`
2. `nea-ai-frontend-lb28`

**Steps for each**:
1. Go to Vercel dashboard: https://vercel.com/dashboard
2. Find the project (use search if needed)
3. Click on the project
4. Go to **Settings**
5. Scroll to bottom → **Delete Project**
6. Confirm: Type project name and click **Delete**

**Verification**:
- Only the production `nea-ai-agents` project remains
- Production traffic is unaffected
- Old preview deployments are cleaned up

---

## 📊 Progress Summary

| Task | Status | Type | Priority |
|------|--------|------|----------|
| 1. Fix outreach user_id bug | ✅ Complete | Code + DB | High |
| 2. Fix LangSmith 403s | ✅ Complete | Config | High |
| 5. Delete API catchall | ✅ Complete | Code | Medium |
| 3. Shut down Railway | ⏳ Manual | Infrastructure | Medium |
| 4. Remove BACKEND_URL | ⏳ Manual | Config | Medium |
| 6. Archive Lovable repo | ⏳ Manual | GitHub | Low |
| 7. Delete stale Vercel projects | ⏳ Manual | Infrastructure | Low |

---

## 🔐 Security Tasks (Original Phase 3 Scope)

These are separate from Phase 4 cleanup and tracked in their own tasks:

- **Task #8**: Supabase RLS audit
- **Task #9**: Rotate GitHub PAT
- **Task #10**: Rotate Databricks PAT

See individual task descriptions for details.

---

## ⚡ Performance Task (Future)

- **Task #11**: Profile briefing latency (~96s → optimize)

Low priority - tackle after Phase 4 and security tasks are complete.

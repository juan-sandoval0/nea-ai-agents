# NEA AI Agents Migration Plan

Migration from Railway + SQLite to Vercel + Supabase.

## Phase 1: Foundation (Completed)

- 1.1 Supabase schema setup
- 1.2 Vercel deployment configuration
- 1.3 Environment variable migration

## Phase 2: Core Migration

### 2.1-2.3: Vercel monorepo + Supabase-only rewire (Completed)

### 2.4: Task completed (Completed)

### 2.5: Databricks Asset Bundle (Documentation Only)

Databricks Free Edition cannot reach external APIs (Supabase/Anthropic/etc) due to
restricted serverless egress. The bundle (`databricks.yml` and `notebooks/batch/`)
is kept as documentation for potential future use on a paid tier.

### 2.6: Port batch jobs to GitHub Actions (DONE)

**Commit:** a4b5a41

**Summary:** Databricks Asset Bundle kept as documentation-only; batch scheduler is GitHub Actions.

**Files created:**
- `scripts/run_news_refresh.py` - CLI script for news refresh job
- `scripts/run_investor_digest.py` - CLI script for investor digest job
- `.github/workflows/news_refresh.yml` - Cron every 6 hours + manual trigger
- `.github/workflows/investor_digest.yml` - Cron Mondays 16:00 UTC + manual trigger

**Verification required:**
1. Manually trigger each workflow via GitHub Actions UI
2. Confirm job_runs row appears in Supabase with status="completed"
3. Confirm downstream data (briefing_signals, briefing_news, stories) is populated

### 2.7: Decommission Railway (DONE)

**Commit:** 41e770d

**Summary:** Railway and SQLite backend removed. All persistence now via Supabase.

**Changes:**
- Deleted `railway.toml`
- Deleted `data/nea_agents.db` (SQLite file)
- Removed `Database` class from `core/database.py` (kept data models + Supabase functions)
- Removed `get_db()` singleton from `tools/company_tools.py`
- Refactored `core/evaluation.py` to use Supabase read functions
- Removed `_run_news_refresh_job` and `POST /api/news/refresh` from `services/api.py`
- Updated `core/__init__.py` exports

**User action required:**
- Shut down the Railway service in the Railway dashboard

### 2.8: Observability floor (DONE)

**Commit:** 5f584af

**Summary:** Added observability infrastructure for production monitoring.

**Changes:**
- `services/logging_setup.py` - Structured JSON logging + LangSmith setup helper
- `services/rate_limit.py` - Upstash Redis rate limiting (graceful fallback if not configured)
- Updated `api/py/briefing.py` - LangSmith tracing + rate limit (10/min per key)
- Updated `api/py/outreach.py` - LangSmith tracing + rate limit (5/min per key)
- Updated `scripts/run_news_refresh.py` - LangSmith tracing
- Updated `scripts/run_investor_digest.py` - LangSmith tracing
- Updated `README.md` - Vercel log drain documentation

**Environment variables:**
- `LANGSMITH_API_KEY` - Enable LangSmith tracing (optional)
- `LANGSMITH_PROJECT` - LangSmith project name (optional)
- `UPSTASH_REDIS_REST_URL` - Enable rate limiting (optional)
- `UPSTASH_REDIS_REST_TOKEN` - Upstash auth token (optional)

## Phase 3: Production Hardening

### 3.1: Real Authentication (Clerk) - DONE

**Status:** Implemented (pending Clerk account setup)

**Summary:** Dual-mode authentication with feature flag for gradual rollout.

**Files created:**
- `services/auth.py` - JWT verification helper with Clerk JWKS support
- `frontend/middleware.ts` - Clerk route protection
- `supabase/migrations/20260420_phase3_add_user_id.sql` - DB migration for user_id columns

**Files modified:**
- `frontend/app/layout.tsx` - Wrapped with `<ClerkProvider>`
- `frontend/app/api/[...path]/route.ts` - Added Bearer token injection
- `services/api.py` - Dual-mode auth middleware (Clerk or X-NEA-Key)
- `api/py/briefing.py` - Same dual-mode auth
- `api/py/outreach.py` - Same dual-mode auth
- `api/py/outreach-feedback.py` - Same dual-mode auth
- `services/history.py` - Added user_id to BriefingRecord + save_briefing
- `requirements.txt` - Added pyjwt[crypto], httpx

**Environment variables (add to Vercel):**
- `USE_CLERK_AUTH=false` - Feature flag (set to true to enable)
- `NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY` - Clerk public key
- `CLERK_SECRET_KEY` - Clerk secret key
- `CLERK_JWKS_URL` - Clerk JWKS endpoint

**To activate:**
1. Install Clerk: `cd frontend && npm install @clerk/nextjs`
2. Create Clerk account and get credentials
3. Set env vars in Vercel
4. Run DB migration in Supabase SQL Editor
5. Set `USE_CLERK_AUTH=true`

### 3.2: Observability (Structured Logging) - DONE

**Status:** Completed

**Summary:** Replaced all logging.basicConfig with structured JSON logging.

**Files modified:**
- `services/api.py` - Now uses `setup_logging(use_json=True)`
- `api/py/outreach-feedback.py` - Same + added LangSmith setup
- `agents/meeting_briefing/briefing_generator.py` - Human-readable for CLI

**To complete observability:**
1. Set `LANGSMITH_API_KEY` and `LANGSMITH_PROJECT` in Vercel
2. Configure Vercel log drain to Datadog/Axiom/Grafana
3. Build dashboard for job_runs monitoring

### 3.3: Rate Limiting (Per-User) - DONE

**Status:** Implemented (will use user_id when Clerk is enabled)

**Summary:** Rate limits now key by user_id when `USE_CLERK_AUTH=true`.

**Current limits (still per-minute, change to per-hour when ready):**
- Briefing: 10/min per user
- Outreach: 5/min per user

### 3.4: Structured LLM Output - DONE

**Status:** Implemented with feature flag

**Summary:** Added `with_structured_output()` support for briefing generation.

**Files created:**
- `agents/meeting_briefing/models.py` - BriefingLLMOutput Pydantic model

**Files modified:**
- `agents/meeting_briefing/briefing_generator.py` - Feature-flagged structured output
- `services/api.py` - build_response() accepts pre-parsed fields
- `api/py/briefing.py` - Same build_response change

**Environment variable:**
- `USE_STRUCTURED_BRIEFING=false` - Set to true to enable

**To activate:**
1. Set `USE_STRUCTURED_BRIEFING=true` in Vercel
2. Test briefing generation
3. Verify all sections populate correctly

---

## Success Criteria (Phase 3)

- [ ] Logged-out user hitting mutating API gets 401 Unauthorized
- [ ] Logged-in user has user_id in logs, DB rows, and LangSmith traces
- [ ] 11th briefing request in 1 hour returns 429 Too Many Requests
- [ ] Every log line in Vercel shows as valid JSON with request_id
- [ ] LangSmith project shows one trace per briefing with full LLM breakdown
- [ ] Dashboard shows 7 days of batch job runs
- [ ] Changing briefing prompt section numbers does NOT break response

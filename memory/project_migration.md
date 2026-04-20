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

## Phase 3: (Not started)

Awaiting completion of Phase 2.

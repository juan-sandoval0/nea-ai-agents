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

### 2.7: Decommission Railway (Pending)

Blocked until 2.6 is verified in production.

Steps:
- Delete railway.toml
- Delete core/database.py's Database class
- Delete data/nea_agents.db
- Delete _run_news_refresh_job and POST /api/news/refresh from services/api.py
- Run test suite / manual endpoint verification

### 2.8: Observability floor (Pending)

- LangSmith tracing integration
- Structured JSON logging
- Vercel log drain documentation
- Upstash Redis rate limiting

## Phase 3: (Not started)

Awaiting completion of Phase 2.

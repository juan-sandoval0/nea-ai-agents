# Databricks notebook source
# MAGIC %md
# MAGIC # News Refresh
# MAGIC
# MAGIC Scheduled (every 6h) replacement for
# MAGIC `services/api.py::_run_news_refresh_job`, which used `threading.Thread`
# MAGIC on Railway. See Phase 2.6 of the migration plan.

# COMMAND ----------
dbutils.widgets.text("days", "7")
dbutils.widgets.text("refresh_competitors", "true")

# COMMAND ----------
# Bootstrap: secrets → env, repo root → sys.path, diagnostic prints first so
# any failure is visible. Keep in ONE cell — cross-cell state on serverless is
# unreliable.
import os, sys, glob

_SECRET_KEYS = [
    "ANTHROPIC_API_KEY",
    "HARMONIC_API_KEY",
    "OPENAI_API_KEY",
    "PARALLEL_API_KEY",
    "SUPABASE_URL",
    "SUPABASE_SERVICE_KEY",
]
for _k in _SECRET_KEYS:
    os.environ[_k] = dbutils.secrets.get("nea", _k)
print("secrets loaded:", _SECRET_KEYS)

_ctx = dbutils.notebook.entry_point.getDbutils().notebook().getContext()
_nb_path = _ctx.notebookPath().get()
print(f"notebookPath={_nb_path}")
print(f"cwd={os.getcwd()}")

# Candidate 1: walk up from notebook path until we find a directory containing
# services/, agents/, core/.
_candidates = []
_parts = _nb_path.strip("/").split("/")
for _i in range(len(_parts), 0, -1):
    _cand = "/" + "/".join(_parts[:_i])
    _candidates.append(_cand)
# Candidate 2: /Workspace + notebookPath, since serverless mounts WS under /Workspace
_candidates.append("/Workspace" + _nb_path)
for _i in range(len(_parts), 0, -1):
    _cand = "/Workspace/" + "/".join(_parts[:_i])
    _candidates.append(_cand)

_repo_root = None
for _c in _candidates:
    try:
        _entries = set(os.listdir(_c))
        print(f"probe {_c} → has services={'services' in _entries}, agents={'agents' in _entries}")
        if {"services", "agents", "core"}.issubset(_entries):
            _repo_root = _c
            break
    except Exception as _e:
        pass

if not _repo_root:
    raise RuntimeError(
        f"Could not locate repo root from notebookPath={_nb_path}. "
        f"Tried: {_candidates}"
    )

if _repo_root not in sys.path:
    sys.path.insert(0, _repo_root)
print(f"repo_root={_repo_root}")
print(f"services/ listing: {sorted(os.listdir(_repo_root + '/services'))[:10]}")

# COMMAND ----------
# Real work.
import logging

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
logger = logging.getLogger("news_refresh_notebook")

days = int(dbutils.widgets.get("days"))
refresh_competitors = dbutils.widgets.get("refresh_competitors").strip().lower() == "true"
print(f"days={days} refresh_competitors={refresh_competitors}")

from services.job_manager import get_job_manager
from agents.news_aggregator.agent import cmd_check
from agents.news_aggregator.investor_digest import generate_investor_digest

job_manager = get_job_manager()
job = job_manager.create_job("news_aggregator", triggered_by="databricks_scheduled")
job_manager.start_job(job.id)
logger.info("job_runs id=%s", job.id)

try:
    logger.info("Step 1/2: cmd_check(refresh_competitors=%s)", refresh_competitors)
    cmd_check(refresh_competitors=refresh_competitors, quiet=True)

    logger.info("Step 2/2: generate_investor_digest(days=%s)", days)
    digest = generate_investor_digest(days=days)

    story_count = len(digest.stories) if hasattr(digest, "stories") else 0
    result_summary = {
        "story_count": story_count,
        "days": days,
        "refresh_competitors": refresh_competitors,
    }
    job_manager.complete_job(job.id, result_summary)
    logger.info("Completed: %s", result_summary)

except Exception as exc:
    err = f"{type(exc).__name__}: {exc}"
    logger.exception("News refresh failed")
    job_manager.fail_job(job.id, err)
    raise

# COMMAND ----------
dbutils.notebook.exit(f"OK story_count={story_count} job_id={job.id}")

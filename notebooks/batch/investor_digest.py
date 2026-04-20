# Databricks notebook source
# MAGIC %md
# MAGIC # Investor Digest
# MAGIC
# MAGIC Weekly (Mondays 09:00 PT) replacement for the synchronous
# MAGIC `GET /api/digest/weekly` code path
# MAGIC (`agents.news_aggregator.digest.generate_weekly_digest`).
# MAGIC
# MAGIC Pipeline:
# MAGIC 1. `generate_weekly_digest` — produces the WeeklyDigest object the
# MAGIC    frontend weekly-digest view consumes
# MAGIC 2. Persist the digest markdown + stats to the digest history table
# MAGIC    (via the same path the HTTP endpoint uses today)
# MAGIC 3. Record run in `job_runs`

# COMMAND ----------
# MAGIC %md ## Widgets

# COMMAND ----------
dbutils.widgets.text("days", "7")
days = int(dbutils.widgets.get("days"))
print(f"days={days}")

# COMMAND ----------
# MAGIC %md ## Load secrets

# COMMAND ----------
import os

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

# COMMAND ----------
# MAGIC %md ## sys.path

# COMMAND ----------
import sys

_ctx = dbutils.notebook.entry_point.getDbutils().notebook().getContext()
_nb_path = _ctx.notebookPath().get()
_parts = _nb_path.strip("/").split("/")
if "files" in _parts:
    _idx = _parts.index("files")
    _repo_root = "/" + "/".join(_parts[: _idx + 1])
else:
    _repo_root = "/".join(_nb_path.split("/")[:-3])

if _repo_root not in sys.path:
    sys.path.insert(0, _repo_root)
print(f"repo_root={_repo_root}")

# COMMAND ----------
# MAGIC %md ## Generate the weekly digest

# COMMAND ----------
import logging

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
logger = logging.getLogger("investor_digest_notebook")

from services.job_manager import get_job_manager
from agents.news_aggregator.digest import generate_weekly_digest

job_manager = get_job_manager()
job = job_manager.create_job("news_aggregator_weekly_digest", triggered_by="databricks_scheduled")
job_manager.start_job(job.id)
logger.info("Started job_runs row id=%s", job.id)

try:
    logger.info("generate_weekly_digest(days=%s)", days)
    digest = generate_weekly_digest(
        days=days,
        include_industry_highlights=True,
        use_llm_summaries=False,
    )

    featured_count = len(digest.featured_articles) if hasattr(digest, "featured_articles") else 0
    summary_count = len(digest.summary_articles) if hasattr(digest, "summary_articles") else 0
    result_summary = {
        "days": days,
        "featured_count": featured_count,
        "summary_count": summary_count,
    }
    job_manager.complete_job(job.id, result_summary)
    logger.info("Completed: %s", result_summary)

except Exception as exc:
    err = f"{type(exc).__name__}: {exc}"
    logger.exception("Weekly digest generation failed")
    job_manager.fail_job(job.id, err)
    raise

# COMMAND ----------
dbutils.notebook.exit(f"OK featured={featured_count} summary={summary_count} job_id={job.id}")

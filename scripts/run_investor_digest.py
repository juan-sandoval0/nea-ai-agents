#!/usr/bin/env python3
"""
Investor Digest CLI Script for GitHub Actions
==============================================

Weekly digest generation. Runs Mondays at 16:00 UTC (09:00 PT)
via GitHub Actions cron.

Usage:
    python scripts/run_investor_digest.py

Environment variables required:
    ANTHROPIC_API_KEY
    HARMONIC_API_KEY
    OPENAI_API_KEY
    PARALLEL_API_KEY
    SUPABASE_URL
    SUPABASE_SERVICE_KEY

Optional:
    DAYS - override the default 7-day lookback (for testing)
    DRY_RUN - set to "true" to skip actual execution (for testing)
"""

import logging
import os
import sys
import traceback
from pathlib import Path

# Add repo root to sys.path so we can import local modules
REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

# Load .env if present (local development)
from dotenv import load_dotenv
load_dotenv(override=False)

# Configure logging for GitHub Actions log stream
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("run_investor_digest")


def main() -> int:
    """Run the investor digest job. Returns exit code."""

    # Validate required environment variables
    required_vars = [
        "ANTHROPIC_API_KEY",
        "HARMONIC_API_KEY",
        "OPENAI_API_KEY",
        "PARALLEL_API_KEY",
        "SUPABASE_URL",
        "SUPABASE_SERVICE_KEY",
    ]
    missing = [v for v in required_vars if not os.getenv(v)]
    if missing:
        logger.error("Missing required environment variables: %s", missing)
        return 1

    # Configuration
    days = int(os.getenv("DAYS", "7"))
    dry_run = os.getenv("DRY_RUN", "").lower() == "true"

    logger.info("Starting investor digest: days=%d, dry_run=%s", days, dry_run)

    if dry_run:
        logger.info("DRY_RUN enabled - skipping actual execution")
        return 0

    # Import here to avoid import errors if env not configured
    from services.job_manager import get_job_manager
    from agents.news_aggregator.digest import generate_weekly_digest

    job_manager = get_job_manager()
    job = job_manager.create_job("news_aggregator_weekly_digest", triggered_by="github_actions_scheduled")
    job_manager.start_job(job.id)
    logger.info("Created job_runs row: id=%s", job.id)

    try:
        logger.info("generate_weekly_digest(days=%d, include_industry_highlights=True, use_llm_summaries=False)", days)
        digest = generate_weekly_digest(
            days=days,
            include_industry_highlights=True,
            use_llm_summaries=False,
        )

        # Extract counts from digest
        featured_count = len(digest.featured_articles) if hasattr(digest, "featured_articles") else 0
        summary_count = len(digest.summary_articles) if hasattr(digest, "summary_articles") else 0

        result_summary = {
            "days": days,
            "featured_count": featured_count,
            "summary_count": summary_count,
        }

        job_manager.complete_job(job.id, result_summary)
        logger.info("Completed successfully: %s", result_summary)
        return 0

    except Exception as exc:
        error_msg = f"{type(exc).__name__}: {exc}"
        logger.exception("Investor digest generation failed")
        job_manager.fail_job(job.id, error_msg)
        return 1


if __name__ == "__main__":
    sys.exit(main())

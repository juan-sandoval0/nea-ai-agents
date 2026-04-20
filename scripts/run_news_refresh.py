#!/usr/bin/env python3
"""
News Refresh CLI Script for GitHub Actions
==========================================

Scheduled replacement for the Railway threading.Thread background task.
Runs every 6 hours via GitHub Actions cron.

Usage:
    python scripts/run_news_refresh.py

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

from services.logging_setup import setup_logging, setup_langsmith, get_logger

# Configure structured logging (use plain format for GH Actions readability)
# and LangSmith tracing
setup_logging(use_json=False)
setup_langsmith(project="nea-news-refresh")
logger = get_logger("run_news_refresh")


def main() -> int:
    """Run the news refresh job. Returns exit code."""

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
    refresh_competitors = True
    dry_run = os.getenv("DRY_RUN", "").lower() == "true"

    logger.info("Starting news refresh: days=%d, refresh_competitors=%s, dry_run=%s",
                days, refresh_competitors, dry_run)

    if dry_run:
        logger.info("DRY_RUN enabled - skipping actual execution")
        return 0

    # Import here to avoid import errors if env not configured
    from services.job_manager import get_job_manager
    from agents.news_aggregator.agent import cmd_check
    from agents.news_aggregator.investor_digest import generate_investor_digest

    job_manager = get_job_manager()
    job = job_manager.create_job("news_aggregator", triggered_by="github_actions_scheduled")
    job_manager.start_job(job.id)
    logger.info("Created job_runs row: id=%s", job.id)

    try:
        # Step 1: Check all watched companies for new signals
        logger.info("Step 1/2: cmd_check(refresh_competitors=%s, quiet=True)", refresh_competitors)
        cmd_check(refresh_competitors=refresh_competitors, quiet=True)

        # Step 2: Generate investor digest (saves stories to Supabase)
        logger.info("Step 2/2: generate_investor_digest(days=%d)", days)
        digest = generate_investor_digest(days=days)

        # Extract story count from digest
        story_count = len(digest.stories) if hasattr(digest, "stories") else 0

        result_summary = {
            "story_count": story_count,
            "days": days,
            "refresh_competitors": refresh_competitors,
        }

        job_manager.complete_job(job.id, result_summary)
        logger.info("Completed successfully: %s", result_summary)
        return 0

    except Exception as exc:
        error_msg = f"{type(exc).__name__}: {exc}"
        logger.exception("News refresh failed")
        job_manager.fail_job(job.id, error_msg)
        return 1


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""
Stage 1: Generate Agent Outputs
================================

Runs each NEA agent (Outreach, TLDR/Briefing, News Aggregator) on test cases
and saves the input bundle + agent output + context tags as JSON files.

These JSON files are the inputs to Stage 2 (build_judge_prompt) and eventually
Stage 3 (Anthropic Batch API submission).

Output layout:
    evaluation/test_outputs/
        outreach/
            stripe.com_ashley_email.json
            stripe.com_madison_email.json
            ...
        tldr/
            stripe.com.json
            openai.com.json
            ...
        news_aggregator/
            digest_7d.json
            digest_7d.json

Each JSON record has the shape:
    {
      "test_case_id": "<agent>_<company>_<investor>_<format>",
      "agent": "outreach" | "tldr" | "news_aggregator",
      "timestamp": "<ISO-8601>",
      "success": true | false,
      "error": null | "<error message>",
      "company_bundle": { ... },       # get_company_bundle().to_dict()
      "agent_output": { ... },         # serialized agent result
      "context_tags": { ... },         # rubric context variables
    }

Usage:
    # Run all agents on default test cases
    python -m evaluation.generate_outputs

    # Run specific agents only
    python -m evaluation.generate_outputs --agents outreach tldr

    # Use specific companies/investors
    python -m evaluation.generate_outputs --companies stripe.com openai.com
    python -m evaluation.generate_outputs --investors ashley danielle

    # Use cached DB data (skip live API re-ingestion)
    python -m evaluation.generate_outputs --skip-ingest

    # Custom output directory
    python -m evaluation.generate_outputs --output-dir evaluation/test_outputs/run_2
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import logging
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

# ---------------------------------------------------------------------------
# Project root on sys.path so imports work from any cwd
# ---------------------------------------------------------------------------
_PROJECT_ROOT = Path(__file__).parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

# Load .env early so all downstream imports pick up API keys
try:
    from dotenv import load_dotenv
    load_dotenv(_PROJECT_ROOT / ".env")
except ImportError:
    pass

logger = logging.getLogger(__name__)


# =============================================================================
# DEFAULT TEST CASE DEFINITIONS
# =============================================================================

# Companies used for outreach + TLDR test cases
DEFAULT_COMPANIES = [
    "cydelphi.com",
    "novee.security",
    "distyl.ai",
    "saviynt.com",
    "physicalintelligence.company",
    "noma.security",
    "periodic.com",
    "genspark.ai",
]

# Investor profiles to use for outreach test cases
DEFAULT_INVESTORS = [
    "ashley",
    "danielle",
    "madison",
]

# Formats to generate for outreach (usually email; linkedin is similar)
DEFAULT_FORMATS = ["email"]

# News aggregator look-back windows
DEFAULT_DIGEST_DAYS = [7]

# Minimum priority score for news aggregator digest
DEFAULT_MIN_PRIORITY = 40.0


# =============================================================================
# SERIALIZATION HELPERS
# =============================================================================

def _serialize(obj: Any) -> Any:
    """
    Recursively convert dataclasses, sets, and other non-JSON-native types
    to JSON-serializable equivalents.
    """
    if dataclasses.is_dataclass(obj) and not isinstance(obj, type):
        return {k: _serialize(v) for k, v in dataclasses.asdict(obj).items()}
    if isinstance(obj, (list, tuple)):
        return [_serialize(i) for i in obj]
    if isinstance(obj, dict):
        return {k: _serialize(v) for k, v in obj.items()}
    if isinstance(obj, set):
        return [_serialize(i) for i in sorted(obj)]
    if isinstance(obj, Path):
        return str(obj)
    return obj


def _compute_data_richness(bundle_dict: dict) -> str:
    """
    Derive data richness tag from the company bundle.

    Returns:
        "high"   — news + signals + founders all present
        "medium" — exactly 2 of the 3 present
        "low"    — only 1 of 3 present
        "empty"  — none present (or company not found)
    """
    if not bundle_dict or not bundle_dict.get("company_core"):
        return "empty"
    has_news = bool(bundle_dict.get("news"))
    has_signals = bool(bundle_dict.get("key_signals"))
    has_founders = bool(bundle_dict.get("founders"))
    count = sum([has_news, has_signals, has_founders])
    return {3: "high", 2: "medium", 1: "low", 0: "empty"}[count]


def _compute_api_coverage(raw_signals: list, watchlist: list) -> str:
    """Rough coverage tag for news aggregator context."""
    if not watchlist:
        return "empty"
    signals_per_company = len(raw_signals) / max(len(watchlist), 1)
    if signals_per_company >= 5:
        return "high"
    if signals_per_company >= 2:
        return "medium"
    return "low"


# =============================================================================
# OUTREACH AGENT
# =============================================================================

def run_outreach_cases(
    companies: list[str],
    investors: list[str],
    formats: list[str],
    skip_ingest: bool,
    output_dir: Path,
) -> list[dict]:
    """
    Run the outreach agent for all (company, investor, format) combinations
    and save each result as a JSON file.

    Returns a list of summary dicts for reporting.
    """
    from agents.outreach.generator import generate_outreach
    from tools.company_tools import get_company_bundle, normalize_company_id

    output_dir.mkdir(parents=True, exist_ok=True)
    summaries = []

    for company_id in companies:
        for investor_key in investors:
            for output_format in formats:
                test_case_id = f"outreach_{company_id}_{investor_key}_{output_format}"
                logger.info(f"Running {test_case_id}")

                record: dict = {
                    "test_case_id": test_case_id,
                    "agent": "outreach",
                    "timestamp": datetime.utcnow().isoformat(),
                    "company_id": company_id,
                    "investor_key": investor_key,
                    "output_format": output_format,
                    "success": False,
                    "error": None,
                    "company_bundle": None,
                    "agent_output": None,
                    "context_tags": None,
                }

                try:
                    # Step 1: Run the agent
                    gen_result = generate_outreach(
                        company_id=company_id,
                        output_format=output_format,
                        investor_key=investor_key,
                        skip_ingest=skip_ingest,
                    )

                    # Step 2: Fetch company bundle for the judge
                    normalized = normalize_company_id(company_id)
                    bundle = get_company_bundle(normalized)
                    bundle_dict = bundle.to_dict()

                    # Step 3: Build structured agent_output the judge expects
                    agent_output = {
                        "subject": gen_result.get("subject"),
                        "message": gen_result.get("message"),
                        "context_type": gen_result.get("context_type"),
                        "investor_key": gen_result.get("investor_key"),
                        "output_format": gen_result.get("output_format"),
                        "contact_name": gen_result.get("contact_name"),
                        "contact_title": gen_result.get("contact_title"),
                        "contact_linkedin": gen_result.get("contact_linkedin"),
                        "company_name": gen_result.get("company_name"),
                        "data_sources": gen_result.get("data_sources", {}),
                        "generated_at": gen_result.get("generated_at"),
                    }

                    # Step 4: Derive context tags
                    context_tags = {
                        "investor": investor_key,
                        "format": output_format,
                        "data_richness": _compute_data_richness(bundle_dict),
                        # Feedback state: "no_feedback" until the feedback loop
                        # is exercised and promoted samples exist
                        "feedback_state": "no_feedback",
                        # Investor context inferred from context_type
                        "investor_context": gen_result.get("context_type", "general"),
                    }

                    record.update({
                        "success": gen_result.get("success", False),
                        "error": gen_result.get("error"),
                        "company_bundle": bundle_dict,
                        "agent_output": agent_output,
                        "context_tags": context_tags,
                    })

                except Exception as exc:
                    logger.error(f"  FAILED {test_case_id}: {exc}")
                    record["error"] = str(exc)

                # Save to disk regardless of success
                out_path = output_dir / f"{company_id.replace('.', '_')}_{investor_key}_{output_format}.json"
                out_path.write_text(json.dumps(record, indent=2, default=str))

                summaries.append({
                    "test_case_id": test_case_id,
                    "success": record["success"],
                    "error": record.get("error"),
                    "path": str(out_path),
                })

    return summaries


# =============================================================================
# TLDR / MEETING BRIEFING AGENT
# =============================================================================

def run_tldr_cases(
    companies: list[str],
    output_dir: Path,
) -> list[dict]:
    """
    Run the meeting briefing agent for each company and save each result.

    The TLDR judge accepts either a structured dict or raw markdown.
    We capture both: the raw markdown from the agent and the company_bundle
    from the shared SQLite DB for factual grounding.

    Returns a list of summary dicts for reporting.
    """
    from agents.meeting_briefing.agent import MeetingBriefingAgent
    from tools.company_tools import get_company_bundle, normalize_company_id

    output_dir.mkdir(parents=True, exist_ok=True)
    summaries = []
    agent = MeetingBriefingAgent()

    for company_id in companies:
        test_case_id = f"tldr_{company_id}"
        logger.info(f"Running {test_case_id}")

        record: dict = {
            "test_case_id": test_case_id,
            "agent": "tldr",
            "timestamp": datetime.utcnow().isoformat(),
            "company_id": company_id,
            "success": False,
            "error": None,
            "company_bundle": None,
            "agent_output": None,
            "context_tags": None,
        }

        try:
            # Step 1: Run briefing agent
            run_result = agent.prepare_briefing(company_id)

            # Step 2: Build company_bundle from what the agent actually retrieved.
            # The TLDR agent calls Harmonic directly (never writes to SQLite), so
            # get_company_bundle() would return empty data and the judge would flag
            # every claim as a hallucination. Instead we use the Harmonic data the
            # agent had, supplemented by SQLite for founders/competitors (which are
            # written there during enrichment).
            retrieved = run_result.get("retrieved_content") or {}
            company_raw = retrieved.get("company_raw")  # HarmonicCompany dict, raw_data stripped

            normalized = normalize_company_id(company_id)
            bundle = get_company_bundle(normalized)
            sqlite_dict = bundle.to_dict()

            # Build structured key_signals from Harmonic metric fields
            key_signals = []
            if company_raw:
                hc = company_raw.get("headcount_change_90d")
                wt = company_raw.get("web_traffic_change_30d")
                fl_amount = company_raw.get("funding_last_amount")
                fl_date = company_raw.get("funding_last_date")
                if hc is not None:
                    sign = "+" if hc > 0 else ""
                    key_signals.append({
                        "signal_type": "headcount",
                        "description": f"Headcount change 90d: {sign}{hc:.1f}%",
                        "source": "Harmonic",
                        "observed_at": datetime.utcnow().date().isoformat(),
                    })
                if wt is not None:
                    sign = "+" if wt > 0 else ""
                    key_signals.append({
                        "signal_type": "web_traffic",
                        "description": f"Web traffic change 30d: {sign}{wt:.1f}%",
                        "source": "Harmonic",
                        "observed_at": datetime.utcnow().date().isoformat(),
                    })
                if fl_amount and fl_date:
                    key_signals.append({
                        "signal_type": "funding",
                        "description": f"Last round: ${fl_amount:,.0f} ({fl_date})",
                        "source": "Harmonic",
                        "observed_at": fl_date,
                    })

            bundle_dict = {
                "company_core": company_raw,
                "founders": sqlite_dict.get("founders") or [],
                "key_signals": key_signals,
                "news": [],  # Harmonic has no news endpoint; metric changes are in signals
                "competitors": sqlite_dict.get("competitors") or [],
            }

            # Step 3: Build agent_output the TLDR judge accepts
            # The judge accepts: markdown string OR structured sections dict.
            # We pass both; the builder will prefer structured if available.
            agent_output = {
                "markdown": run_result.get("briefing_markdown") or "",
                "company_name": run_result.get("company_name"),
                "run_id": run_result.get("run_id"),
                "success": run_result.get("success", False),
                "error": run_result.get("error"),
                "retrieval_counts": run_result.get("retrieval_counts", {}),
                "retrieval_doc_ids": run_result.get("retrieval_doc_ids", {}),
                "total_elapsed_ms": run_result.get("total_elapsed_ms"),
                # Structured sections — populate if the agent returns them;
                # fallback to None so the judge knows to parse from markdown.
                "tldr": None,
                "why_it_matters": None,
                "company_snapshot": None,
                "founders": None,
                "signals": None,
                "news": None,
                "meeting_prep": None,
            }

            # Step 4: Derive context tags
            context_tags = {
                "company": company_id,
                # Which data sources were populated
                "data_sources": _describe_data_sources(bundle_dict),
                "tldr_type": "standard",
            }

            record.update({
                "success": run_result.get("success", False),
                "error": run_result.get("error"),
                "company_bundle": bundle_dict,
                "agent_output": agent_output,
                "context_tags": context_tags,
            })

        except Exception as exc:
            logger.error(f"  FAILED {test_case_id}: {exc}")
            record["error"] = str(exc)

        # Save to disk
        out_path = output_dir / f"{company_id.replace('.', '_')}.json"
        out_path.write_text(json.dumps(record, indent=2, default=str))

        summaries.append({
            "test_case_id": test_case_id,
            "success": record["success"],
            "error": record.get("error"),
            "path": str(out_path),
        })

    return summaries


def _describe_data_sources(bundle_dict: dict) -> str:
    """Build a comma-separated string of which data sources are present."""
    sources = []
    if bundle_dict and bundle_dict.get("company_core"):
        sources.append("harmonic")
    if bundle_dict and bundle_dict.get("news"):
        sources.append("news")
    if bundle_dict and bundle_dict.get("key_signals"):
        sources.append("signals")
    if bundle_dict and bundle_dict.get("founders"):
        sources.append("founders")
    return ",".join(sources) if sources else "none"


# =============================================================================
# NEWS AGGREGATOR AGENT
# =============================================================================

def _serialize_signal(sig) -> dict:
    """Serialize a CompanySignal to a plain dict for JSON storage."""
    return {
        "id": sig.id,
        "company_id": sig.company_id,
        "signal_type": sig.signal_type,
        "headline": sig.headline,
        "description": sig.description,
        "source_url": sig.source_url,
        "source_name": sig.source_name,
        "published_date": sig.published_date,
        "relevance_score": sig.relevance_score,
        "sentiment": sig.sentiment,
        "synopsis": sig.synopsis,
        "detected_at": sig.detected_at,
        # score_breakdown omitted (internal; not needed by the judge)
    }


def _serialize_watched_company(company) -> dict:
    """Serialize a WatchedCompany to a plain dict for JSON storage."""
    return {
        "id": company.id,
        "company_id": company.company_id,
        "company_name": company.company_name,
        "category": company.category,
        "parent_company_id": company.parent_company_id,
        "industry_tags": company.industry_tags or [],
        "is_active": company.is_active,
        "added_at": company.added_at,
    }


def _serialize_story(story) -> dict:
    """Serialize an InvestorDigest Story to a plain dict."""
    return {
        "story_id": story.story_id,
        "primary_url": story.primary_url,
        "primary_title": story.primary_title,
        "classification": story.classification,
        "company_id": story.company_id,
        "company_name": story.company_name,
        "company_category": story.company_category,
        "parent_company_name": story.parent_company_name,
        "industry_tags": story.industry_tags,
        "priority_score": story.priority_score,
        "priority_reasons": story.priority_reasons,
        "synopsis": story.synopsis,
        "published_date": story.published_date,
        "source_count": story.source_count,
        "max_engagement": story.max_engagement,
        "sentiment": {
            "label": story.sentiment.label,
            "score": story.sentiment.score,
            "keywords_hit": story.sentiment.keywords_hit,
        } if story.sentiment else None,
        "other_urls": story.other_urls,
    }


def run_news_aggregator_cases(
    digest_days_list: list[int],
    min_priority: float,
    investor_id: Optional[str],
    output_dir: Path,
) -> list[dict]:
    """
    Run the news aggregator agent for each lookback window and save results.

    Raw signals (ALL signals from DB before priority filtering) are captured
    so the judge can evaluate filter quality (S2) and recall (D2).

    Returns a list of summary dicts for reporting.
    """
    from agents.news_aggregator.investor_digest import generate_investor_digest
    from agents.news_aggregator.database import get_signals, get_companies

    output_dir.mkdir(parents=True, exist_ok=True)
    summaries = []

    # Fetch raw signals and watchlist ONCE (shared across day variants)
    logger.info("Fetching raw signals from DB (unfiltered)...")
    try:
        raw_signals = get_signals(limit=1000)  # All signals, no min_score filter
        watchlist = get_companies(active_only=False)
    except Exception as exc:
        logger.error(f"Failed to fetch raw signals / watchlist: {exc}")
        raw_signals = []
        watchlist = []

    raw_signals_serialized = [_serialize_signal(s) for s in raw_signals]
    watchlist_serialized = [_serialize_watched_company(c) for c in watchlist]

    for days in digest_days_list:
        test_case_id = f"news_aggregator_{days}d"
        logger.info(f"Running {test_case_id}")

        record: dict = {
            "test_case_id": test_case_id,
            "agent": "news_aggregator",
            "timestamp": datetime.utcnow().isoformat(),
            "days": days,
            "min_priority": min_priority,
            "investor_id": investor_id,
            "success": False,
            "error": None,
            "raw_signals": raw_signals_serialized,
            "watchlist": watchlist_serialized,
            "agent_output": None,
            "context_tags": None,
        }

        try:
            digest = generate_investor_digest(
                days=days,
                min_priority_score=min_priority,
                investor_id=investor_id,
            )

            # Serialize the digest
            all_stories = digest.store.stories if digest.store else []
            agent_output = {
                "start_date": digest.start_date,
                "end_date": digest.end_date,
                "generated_at": digest.generated_at,
                "total_stories": digest.total_stories,
                "total_articles": digest.total_articles,
                "companies_covered": digest.companies_covered,
                "industry_filter": digest.industry_filter,
                "stories": [_serialize_story(s) for s in all_stories],
                # Full markdown for judges who prefer to read the rendered output
                "markdown": digest.to_markdown(),
                # Industry summary
                "industry_summary": digest.get_industry_summary(),
                # Timing (useful for performance analysis, not scoring)
                "timing": {
                    "total_ms": digest.timing.total_time_ms if digest.timing else None,
                },
            }

            context_tags = {
                "days": days,
                "investor_id": investor_id,
                "min_priority": min_priority,
                "api_coverage": _compute_api_coverage(raw_signals, watchlist),
            }

            record.update({
                "success": True,
                "agent_output": agent_output,
                "context_tags": context_tags,
            })

        except Exception as exc:
            logger.error(f"  FAILED {test_case_id}: {exc}")
            record["error"] = str(exc)

        out_path = output_dir / f"digest_{days}d.json"
        out_path.write_text(json.dumps(record, indent=2, default=str))

        summaries.append({
            "test_case_id": test_case_id,
            "success": record["success"],
            "error": record.get("error"),
            "path": str(out_path),
        })

    return summaries


# =============================================================================
# MAIN ENTRYPOINT
# =============================================================================

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Stage 1 — Generate agent outputs for LLM-as-a-Judge evaluation",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Run all agents, default companies/investors
  python -m evaluation.generate_outputs

  # Run only outreach (faster)
  python -m evaluation.generate_outputs --agents outreach

  # Use cached DB data (no live API calls)
  python -m evaluation.generate_outputs --skip-ingest

  # Custom companies
  python -m evaluation.generate_outputs --companies stripe.com anduril.com
        """,
    )

    parser.add_argument(
        "--agents",
        nargs="+",
        choices=["outreach", "tldr", "news_aggregator"],
        default=["outreach", "tldr", "news_aggregator"],
        help="Which agents to run (default: all three)",
    )
    parser.add_argument(
        "--companies",
        nargs="+",
        default=DEFAULT_COMPANIES,
        help="Company domains to evaluate (outreach + tldr)",
    )
    parser.add_argument(
        "--investors",
        nargs="+",
        default=DEFAULT_INVESTORS,
        help="Investor profile keys to use for outreach",
    )
    parser.add_argument(
        "--formats",
        nargs="+",
        choices=["email", "linkedin"],
        default=DEFAULT_FORMATS,
        help="Output formats for outreach (default: email)",
    )
    parser.add_argument(
        "--digest-days",
        nargs="+",
        type=int,
        default=DEFAULT_DIGEST_DAYS,
        help="Look-back windows (days) for news aggregator digest",
    )
    parser.add_argument(
        "--min-priority",
        type=float,
        default=DEFAULT_MIN_PRIORITY,
        help="Minimum priority score for news aggregator digest",
    )
    parser.add_argument(
        "--investor-id",
        default=None,
        help="Filter news aggregator by investor ID (default: all investors)",
    )
    parser.add_argument(
        "--skip-ingest",
        action="store_true",
        help="Skip live API data ingestion; use cached DB data only",
    )
    parser.add_argument(
        "--output-dir",
        default="evaluation/test_outputs",
        help="Root directory for output JSON files (default: evaluation/test_outputs)",
    )
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Enable DEBUG logging",
    )

    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    output_root = Path(args.output_dir)
    all_summaries: list[dict] = []

    print("=" * 65)
    print("  NEA EVALUATION — Stage 1: Generate Agent Outputs")
    print("=" * 65)
    print(f"  Agents:    {', '.join(args.agents)}")
    print(f"  Companies: {', '.join(args.companies)}")
    if "outreach" in args.agents:
        print(f"  Investors: {', '.join(args.investors)}")
    print(f"  Output:    {output_root}")
    print(f"  Skip ingest: {args.skip_ingest}")
    print("=" * 65)
    print()

    # --- Outreach ---
    if "outreach" in args.agents:
        print("[1/3] Outreach Agent")
        print("-" * 40)
        try:
            summaries = run_outreach_cases(
                companies=args.companies,
                investors=args.investors,
                formats=args.formats,
                skip_ingest=args.skip_ingest,
                output_dir=output_root / "outreach",
            )
            all_summaries.extend(summaries)
            ok = sum(1 for s in summaries if s["success"])
            print(f"  Done: {ok}/{len(summaries)} succeeded\n")
        except Exception as exc:
            logger.error(f"Outreach agent run failed: {exc}")
            print(f"  ERROR: {exc}\n")

    # --- TLDR / Meeting Briefing ---
    if "tldr" in args.agents:
        print("[2/3] TLDR / Meeting Briefing Agent")
        print("-" * 40)
        try:
            summaries = run_tldr_cases(
                companies=args.companies,
                output_dir=output_root / "tldr",
            )
            all_summaries.extend(summaries)
            ok = sum(1 for s in summaries if s["success"])
            print(f"  Done: {ok}/{len(summaries)} succeeded\n")
        except Exception as exc:
            logger.error(f"TLDR agent run failed: {exc}")
            print(f"  ERROR: {exc}\n")

    # --- News Aggregator ---
    if "news_aggregator" in args.agents:
        print("[3/3] News Aggregator Agent")
        print("-" * 40)
        try:
            summaries = run_news_aggregator_cases(
                digest_days_list=args.digest_days,
                min_priority=args.min_priority,
                investor_id=args.investor_id,
                output_dir=output_root / "news_aggregator",
            )
            all_summaries.extend(summaries)
            ok = sum(1 for s in summaries if s["success"])
            print(f"  Done: {ok}/{len(summaries)} succeeded\n")
        except Exception as exc:
            logger.error(f"News aggregator run failed: {exc}")
            print(f"  ERROR: {exc}\n")

    # --- Summary ---
    total = len(all_summaries)
    succeeded = sum(1 for s in all_summaries if s["success"])
    failed = total - succeeded

    print("=" * 65)
    print(f"  SUMMARY: {succeeded}/{total} test cases succeeded")
    if failed:
        print(f"  FAILURES ({failed}):")
        for s in all_summaries:
            if not s["success"]:
                print(f"    - {s['test_case_id']}: {s.get('error', 'unknown error')}")
    print("=" * 65)
    print(f"\n  Output files written to: {output_root.resolve()}")
    print()

    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())

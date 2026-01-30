#!/usr/bin/env python3
"""
Evaluation Harness for Meeting Briefing Agent
==============================================
Runs the agent on specified company URLs and logs results to LangSmith.

Usage:
    # With tracing enabled
    LANGSMITH_TRACING=true LANGSMITH_API_KEY=xxx python -m agents.meeting_briefing.eval_harness --urls stripe.com airbnb.com

    # Without tracing (local only)
    python -m agents.meeting_briefing.eval_harness --urls stripe.com

    # Save results to file
    python -m agents.meeting_briefing.eval_harness --urls stripe.com airbnb.com --output results.json
"""

import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

# Add project root to path for imports
PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from agents.meeting_briefing.agent import MeetingBriefingAgent
from observability.langsmith import tracing_enabled, get_project_name, get_langsmith_client

# Default URLs for evaluation (company domains via Harmonic API)
DEFAULT_EVAL_URLS = ["stripe.com", "airbnb.com", "openai.com"]


def run_evaluation(
    urls: list[str] = None,
    output_file: str = None,
    verbose: bool = True
) -> dict:
    """
    Run the meeting briefing agent on specified company URLs.

    Args:
        urls: List of company URLs to evaluate (defaults to DEFAULT_EVAL_URLS)
        output_file: Optional path to save results as JSON
        verbose: Whether to print progress

    Returns:
        Dict with evaluation results
    """
    urls = urls or DEFAULT_EVAL_URLS
    eval_id = datetime.now().strftime("%Y%m%d_%H%M%S")

    if verbose:
        print("=" * 70)
        print("MEETING BRIEFING AGENT - EVALUATION HARNESS")
        print("=" * 70)
        print(f"Evaluation ID: {eval_id}")
        print(f"URLs: {', '.join(urls)}")
        print(f"Tracing enabled: {tracing_enabled()}")
        if tracing_enabled():
            print(f"LangSmith project: {get_project_name()}")
        print("=" * 70)
        print()

    # Initialize agent
    agent = MeetingBriefingAgent()

    results = {
        "eval_id": eval_id,
        "timestamp": datetime.now().isoformat(),
        "tracing_enabled": tracing_enabled(),
        "project_name": get_project_name() if tracing_enabled() else None,
        "urls_evaluated": urls,
        "runs": [],
        "summary": {
            "total": len(urls),
            "success": 0,
            "failed": 0,
            "total_elapsed_ms": 0,
            "avg_elapsed_ms": 0,
        }
    }

    # Run on each URL
    for i, url in enumerate(urls, 1):
        if verbose:
            print(f"[{i}/{len(urls)}] Processing: {url}")
            print("-" * 50)

        try:
            run_result = agent.prepare_briefing(url)

            results["runs"].append({
                "url": run_result["url"],
                "company_name": run_result["company_name"],
                "run_id": run_result["run_id"],
                "timestamp": run_result["timestamp"],
                "success": run_result["success"],
                "error": run_result["error"],
                "retrieval_counts": run_result["retrieval_counts"],
                "retrieval_doc_ids": run_result["retrieval_doc_ids"],
                "step_timings_ms": run_result["step_timings_ms"],
                "total_elapsed_ms": run_result["total_elapsed_ms"],
                "output_markdown": run_result["briefing_markdown"],
            })

            if run_result["success"]:
                results["summary"]["success"] += 1
                if verbose:
                    print(f"  Company: {run_result['company_name']}")
                    print(f"  Status: SUCCESS")
                    print(f"  Retrieval counts: {run_result['retrieval_counts']}")
                    print(f"  Elapsed: {run_result['total_elapsed_ms']}ms")
            else:
                results["summary"]["failed"] += 1
                if verbose:
                    print(f"  Status: FAILED")
                    print(f"  Error: {run_result['error']}")

            results["summary"]["total_elapsed_ms"] += run_result["total_elapsed_ms"]

        except Exception as e:
            results["summary"]["failed"] += 1
            results["runs"].append({
                "url": url,
                "company_name": None,
                "run_id": None,
                "timestamp": datetime.now().isoformat(),
                "success": False,
                "error": str(e),
                "retrieval_counts": None,
                "retrieval_doc_ids": None,
                "step_timings_ms": None,
                "total_elapsed_ms": None,
                "output_markdown": None,
            })
            if verbose:
                print(f"  Status: EXCEPTION")
                print(f"  Error: {e}")

        if verbose:
            print()

    # Calculate averages
    successful_runs = [r for r in results["runs"] if r["success"]]
    if successful_runs:
        results["summary"]["avg_elapsed_ms"] = int(
            results["summary"]["total_elapsed_ms"] / len(successful_runs)
        )

    # Print summary
    if verbose:
        print("=" * 70)
        print("EVALUATION SUMMARY")
        print("=" * 70)
        print(f"Total runs: {results['summary']['total']}")
        print(f"Successful: {results['summary']['success']}")
        print(f"Failed: {results['summary']['failed']}")
        print(f"Total time: {results['summary']['total_elapsed_ms']}ms")
        print(f"Avg time per run: {results['summary']['avg_elapsed_ms']}ms")

        if tracing_enabled():
            print()
            print(f"View runs in LangSmith:")
            print(f"  https://smith.langchain.com/o/default/projects/{get_project_name()}")

    # Log to LangSmith as experiment metadata if enabled
    if tracing_enabled():
        _log_experiment_to_langsmith(results)

    # Save to file if requested
    if output_file:
        output_path = Path(output_file)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        # Save full results (including markdown) to JSON
        with open(output_path, "w") as f:
            json.dump(results, f, indent=2)

        if verbose:
            print(f"\nResults saved to: {output_path}")

        # Also save a summary without the full markdown for easier viewing
        summary_path = output_path.with_suffix(".summary.json")
        summary_results = {
            **results,
            "runs": [
                {k: v for k, v in r.items() if k != "output_markdown"}
                for r in results["runs"]
            ]
        }
        with open(summary_path, "w") as f:
            json.dump(summary_results, f, indent=2)

        if verbose:
            print(f"Summary saved to: {summary_path}")

    return results


def _log_experiment_to_langsmith(results: dict):
    """Log experiment results to LangSmith with tags for filtering."""
    client = get_langsmith_client()
    if not client:
        return

    try:
        # Tag all runs in this evaluation for easy filtering
        eval_tag = f"eval_{results['eval_id']}"

        # We could use LangSmith datasets/experiments API here
        # For MVP, the individual runs are already logged with metadata
        # This is a placeholder for future dataset integration

        pass

    except Exception as e:
        print(f"Warning: Could not log experiment metadata to LangSmith: {e}")


def main():
    parser = argparse.ArgumentParser(
        description="Run evaluation harness for meeting briefing agent"
    )
    parser.add_argument(
        "--output", "-o",
        type=str,
        help="Output file path for results JSON"
    )
    parser.add_argument(
        "--urls", "-u",
        type=str,
        nargs="+",
        help="Company URLs to evaluate (default: stripe.com, airbnb.com, openai.com)"
    )
    parser.add_argument(
        "--quiet", "-q",
        action="store_true",
        help="Suppress verbose output"
    )

    args = parser.parse_args()

    results = run_evaluation(
        urls=args.urls,
        output_file=args.output,
        verbose=not args.quiet
    )

    # Exit with error code if any failures
    if results["summary"]["failed"] > 0:
        sys.exit(1)


if __name__ == "__main__":
    main()

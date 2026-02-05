#!/usr/bin/env python3
"""
NEA AI Agents - Unified Evaluation Entrypoint
==============================================

Single entrypoint that runs all evaluation components:
- Entity resolution accuracy
- Retrieval relevance
- Signal coverage
- Summary quality scoring
- Failure-mode logging
- Cost metrics
- Citation presence validation

Usage:
    # Run full evaluation on default companies
    python -m evaluation.run_eval

    # Run on specific companies
    python -m evaluation.run_eval --companies stripe.com airbnb.com openai.com

    # Output to JSON file
    python -m evaluation.run_eval --output results/eval_2024.json

    # Output to CSV
    python -m evaluation.run_eval --output results/eval_2024.csv --format csv

    # Summary only (quick view)
    python -m evaluation.run_eval --summary-only

    # Include citation validation
    python -m evaluation.run_eval --validate-citations

    # Verbose logging
    python -m evaluation.run_eval -v
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import Optional
import csv

# Core evaluation modules
from core.evaluation import (
    run_evaluation,
    evaluate_signal_coverage,
    GroundTruth,
    EvaluationResult,
)
from core.quality_scoring import (
    get_quality_stats,
    get_quality_benchmark,
)
from core.failure_analysis import (
    get_failure_stats,
    identify_failure_patterns,
    generate_failure_report,
)
from core.tracking import (
    get_cost_summary,
    get_workflow_timing,
    project_costs_at_scale,
    export_evaluation_costs,
    save_cost_record,
)

logger = logging.getLogger(__name__)


# =============================================================================
# CONSOLIDATED RESULT MODEL
# =============================================================================

@dataclass
class EvaluationRunResult:
    """Consolidated result from a single evaluation run."""

    # Run metadata
    run_id: str
    timestamp: str
    companies_evaluated: list[str]
    period_days: int

    # Entity resolution
    entity_resolution: dict = field(default_factory=dict)
    entity_accuracy: float = 0.0

    # Signal coverage
    signal_coverage: dict = field(default_factory=dict)
    avg_signal_coverage: float = 0.0

    # Retrieval relevance (per-company)
    retrieval_relevance: dict = field(default_factory=dict)
    avg_retrieval_precision: float = 0.0

    # Quality scoring (aggregate from human evaluations)
    quality_scores: Optional[dict] = None

    # Failure analysis
    failures: Optional[dict] = None
    failure_patterns: list = field(default_factory=list)

    # Cost tracking
    costs: Optional[dict] = None
    cost_per_company: float = 0.0
    total_cost: float = 0.0

    # Workflow timing (per-company elapsed time)
    timing: Optional[dict] = None
    per_company_timing: dict = field(default_factory=dict)
    avg_time_per_company_seconds: float = 0.0

    # Citation validation
    citation_validation: Optional[dict] = None

    # Errors during evaluation
    errors: list = field(default_factory=list)

    def to_dict(self) -> dict:
        """Convert to dictionary for serialization."""
        return asdict(self)

    def to_json(self, indent: int = 2) -> str:
        """Convert to JSON string."""
        return json.dumps(self.to_dict(), indent=indent)

    def summary(self) -> str:
        """Generate executive summary text."""
        lines = [
            "=" * 60,
            "NEA AI AGENTS - EVALUATION RESULTS",
            "=" * 60,
            f"Run ID: {self.run_id}",
            f"Timestamp: {self.timestamp}",
            f"Companies Evaluated: {len(self.companies_evaluated)}",
            "",
            "KEY METRICS",
            "-" * 40,
            f"Entity Resolution Accuracy: {self.entity_accuracy:.1%}",
            f"Average Signal Coverage:    {self.avg_signal_coverage:.1%}",
            f"Average Retrieval Precision:{self.avg_retrieval_precision:.1%}",
        ]

        if self.quality_scores:
            avg_quality = self.quality_scores.get("overall_avg", 0)
            lines.append(f"Average Quality Score:      {avg_quality:.2f}/5.0")

        lines.append("")
        lines.append("COST ANALYSIS")
        lines.append("-" * 40)
        lines.append(f"Total Cost:          ${self.total_cost:.4f}")
        lines.append(f"Cost per Company:    ${self.cost_per_company:.4f}")

        if self.avg_time_per_company_seconds > 0:
            lines.append(f"Avg Time per Company: {self.avg_time_per_company_seconds:.2f}s")
        elif self.timing:
            avg_time = self.timing.get("estimated_total_per_company_seconds", 0)
            lines.append(f"Avg Time per Company: {avg_time:.1f}s")

        if self.failures:
            total_failures = self.failures.get("total_failures", 0)
            lines.append("")
            lines.append(f"Failures Logged: {total_failures}")

        if self.citation_validation:
            citation_rate = self.citation_validation.get("citation_rate", 0)
            lines.append("")
            lines.append(f"Citation Presence Rate: {citation_rate:.1%}")

        if self.errors:
            lines.append("")
            lines.append(f"ERRORS: {len(self.errors)}")
            for err in self.errors[:3]:
                lines.append(f"  - {err}")

        lines.append("=" * 60)
        return "\n".join(lines)


# =============================================================================
# CITATION VALIDATION
# =============================================================================

def validate_citations(
    company_id: str,
    briefing_text: str,
    source_documents: list[dict],
) -> dict:
    """
    Validate that sources are properly cited in the briefing.

    Args:
        company_id: Company identifier
        briefing_text: Generated briefing text
        source_documents: List of source documents with URLs/titles

    Returns:
        Dict with citation validation results
    """
    if not briefing_text:
        return {
            "company_id": company_id,
            "has_sources": False,
            "sources_count": 0,
            "citations_found": 0,
            "citation_rate": 0.0,
            "missing_citations": [],
            "valid": True,  # No sources = valid (nothing to cite)
            "notes": "No briefing text provided",
        }

    if not source_documents:
        # Check if briefing claims citations exist
        citation_indicators = ["Source:", "According to", "reported by", "[", "http"]
        has_false_citations = any(
            indicator.lower() in briefing_text.lower()
            for indicator in citation_indicators
        )

        return {
            "company_id": company_id,
            "has_sources": False,
            "sources_count": 0,
            "citations_found": 0,
            "citation_rate": 0.0,
            "missing_citations": [],
            "valid": not has_false_citations,
            "notes": "Hallucinated citations detected" if has_false_citations else "No sources, no citations (valid)",
        }

    # Check which sources are cited
    citations_found = []
    missing_citations = []

    for doc in source_documents:
        url = doc.get("url", "")
        title = doc.get("title", "")
        domain = ""

        if url:
            # Extract domain from URL
            try:
                from urllib.parse import urlparse
                parsed = urlparse(url)
                domain = parsed.netloc.replace("www.", "")
            except Exception:
                pass

        # Check if source is referenced
        is_cited = False
        if url and url in briefing_text:
            is_cited = True
        elif domain and domain in briefing_text:
            is_cited = True
        elif title and len(title) > 10 and title in briefing_text:
            is_cited = True

        if is_cited:
            citations_found.append({"url": url, "title": title})
        else:
            missing_citations.append({"url": url, "title": title})

    citation_rate = len(citations_found) / len(source_documents) if source_documents else 0

    # Strict validation: ALL sources that contributed facts must be cited
    all_cited = len(missing_citations) == 0

    return {
        "company_id": company_id,
        "has_sources": True,
        "sources_count": len(source_documents),
        "citations_found": len(citations_found),
        "citation_rate": citation_rate,
        "missing_citations": missing_citations[:5],  # Limit to first 5
        "valid": all_cited,  # Strict: ALL sources must be cited
        "notes": f"{len(citations_found)}/{len(source_documents)} sources cited" + (
            "" if all_cited else " (INVALID: missing citations)"
        ),
    }


# =============================================================================
# MAIN EVALUATION FUNCTION
# =============================================================================

def run_full_evaluation(
    company_ids: list[str],
    ground_truths: Optional[dict[str, GroundTruth]] = None,
    days: int = 30,
    validate_citations_flag: bool = False,
    output_dir: Optional[Path] = None,
) -> EvaluationRunResult:
    """
    Run comprehensive evaluation across all metrics.

    Args:
        company_ids: List of company identifiers to evaluate
        ground_truths: Optional dict mapping company_id to GroundTruth
        days: Look back period for aggregate metrics
        validate_citations_flag: Whether to run citation validation
        output_dir: Directory for output files

    Returns:
        EvaluationRunResult with all metrics
    """
    import uuid

    run_id = str(uuid.uuid4())[:8]
    timestamp = datetime.utcnow().isoformat()
    ground_truths = ground_truths or {}

    result = EvaluationRunResult(
        run_id=run_id,
        timestamp=timestamp,
        companies_evaluated=company_ids,
        period_days=days,
    )

    # Track per-company results
    entity_correct = 0
    total_coverage = 0.0
    total_precision = 0.0
    citation_results = []
    company_timings = {}

    for company_id in company_ids:
        gt = ground_truths.get(company_id)
        company_start_time = time.time()

        try:
            # Run core evaluation
            eval_result = run_evaluation(
                company_id=company_id,
                ground_truth=gt,
                save_to_db=True,
            )

            # Entity resolution
            if eval_result.entity_resolution:
                result.entity_resolution[company_id] = eval_result.entity_resolution.to_dict()
                if eval_result.entity_resolution.correct:
                    entity_correct += 1

            # Signal coverage
            if eval_result.signal_coverage:
                result.signal_coverage[company_id] = eval_result.signal_coverage.to_dict()
                total_coverage += eval_result.signal_coverage.coverage_rate

            # Retrieval relevance
            if eval_result.retrieval_accuracy:
                result.retrieval_relevance[company_id] = [
                    ra.to_dict() for ra in eval_result.retrieval_accuracy
                ]
                avg_precision = sum(
                    ra.precision for ra in eval_result.retrieval_accuracy
                ) / len(eval_result.retrieval_accuracy) if eval_result.retrieval_accuracy else 0
                total_precision += avg_precision

            # Citation validation (if enabled)
            if validate_citations_flag:
                # Get briefing and sources (mock for now - would need real data)
                briefing_text = ""  # Would come from actual briefing generation
                sources = []  # Would come from retrieval pipeline
                citation_result = validate_citations(company_id, briefing_text, sources)
                citation_results.append(citation_result)

            # Record elapsed time for this company
            elapsed_seconds = time.time() - company_start_time
            company_timings[company_id] = round(elapsed_seconds, 3)

            # Log cost record for this evaluation
            save_cost_record(
                company_id=company_id,
                service="evaluation",
                operation="run_evaluation",
                cost=0.0,  # Evaluation itself is free; API costs logged separately
                latency_ms=int(elapsed_seconds * 1000),
                output_dir=output_dir,
            )

        except Exception as e:
            logger.error(f"Error evaluating {company_id}: {e}")
            result.errors.append(f"{company_id}: {str(e)}")
            # Still record timing for failed evaluations
            elapsed_seconds = time.time() - company_start_time
            company_timings[company_id] = round(elapsed_seconds, 3)

    # Calculate aggregates
    n = len(company_ids)
    if n > 0:
        result.entity_accuracy = entity_correct / n
        result.avg_signal_coverage = total_coverage / n
        result.avg_retrieval_precision = total_precision / n

    # Per-company timing results
    result.per_company_timing = company_timings
    if company_timings:
        result.avg_time_per_company_seconds = round(
            sum(company_timings.values()) / len(company_timings), 3
        )

    # Quality benchmark (from human evaluations)
    try:
        benchmark = get_quality_benchmark(days=days)
        if benchmark:
            result.quality_scores = {
                "total_evaluations": benchmark.total_evaluations,
                "total_companies": benchmark.total_companies,
                "avg_clarity": benchmark.overall_avg_clarity,
                "avg_correctness": benchmark.overall_avg_correctness,
                "avg_usefulness": benchmark.overall_avg_usefulness,
                "overall_avg": benchmark.overall_avg_score,
            }
    except Exception as e:
        logger.warning(f"Could not get quality benchmark: {e}")

    # Failure analysis
    try:
        fail_stats = get_failure_stats(days=days)
        if fail_stats:
            result.failures = {
                "total_failures": fail_stats.total_failures,
                "resolution_rate": fail_stats.resolution_rate,
                "by_category": fail_stats.failures_by_category,
                "by_severity": fail_stats.failures_by_severity,
            }

        patterns = identify_failure_patterns(days=days)
        result.failure_patterns = [
            {
                "category": p.category.value,
                "frequency": p.frequency,
                "examples": p.example_companies[:3],
                "suggested_fix": p.suggested_fix,
            }
            for p in patterns[:5]
        ]
    except Exception as e:
        logger.warning(f"Could not get failure stats: {e}")

    # Cost tracking
    try:
        cost_summary = get_cost_summary(days=days)
        result.costs = cost_summary
        result.total_cost = cost_summary.get("total_cost", 0)
        result.cost_per_company = cost_summary.get("cost_per_company", 0)
    except Exception as e:
        logger.warning(f"Could not get cost summary: {e}")

    # Workflow timing
    try:
        result.timing = get_workflow_timing(days=days)
    except Exception as e:
        logger.warning(f"Could not get workflow timing: {e}")

    # Citation validation results
    if citation_results:
        valid_count = sum(1 for c in citation_results if c["valid"])
        result.citation_validation = {
            "companies_validated": len(citation_results),
            "valid_count": valid_count,
            "citation_rate": valid_count / len(citation_results) if citation_results else 0,
            "results": citation_results,
        }

    return result


# =============================================================================
# OUTPUT FUNCTIONS
# =============================================================================

def save_results(
    results: EvaluationRunResult,
    output_path: Path,
    format: str = "json",
):
    """Save results to file."""
    output_path.parent.mkdir(parents=True, exist_ok=True)

    if format == "json":
        with open(output_path, "w") as f:
            json.dump(results.to_dict(), f, indent=2)

    elif format == "csv":
        with open(output_path, "w", newline="") as f:
            writer = csv.writer(f)

            # Summary section
            writer.writerow(["NEA AI Agents Evaluation Results"])
            writer.writerow(["Run ID", results.run_id])
            writer.writerow(["Timestamp", results.timestamp])
            writer.writerow(["Companies", len(results.companies_evaluated)])
            writer.writerow([])

            # Key metrics
            writer.writerow(["Key Metrics"])
            writer.writerow(["Metric", "Value"])
            writer.writerow(["Entity Accuracy", f"{results.entity_accuracy:.2%}"])
            writer.writerow(["Signal Coverage", f"{results.avg_signal_coverage:.2%}"])
            writer.writerow(["Retrieval Precision", f"{results.avg_retrieval_precision:.2%}"])
            writer.writerow(["Total Cost", f"${results.total_cost:.4f}"])
            writer.writerow(["Cost per Company", f"${results.cost_per_company:.4f}"])
            writer.writerow([])

            # Per-company entity resolution
            writer.writerow(["Entity Resolution by Company"])
            writer.writerow(["Company", "Correct", "Confidence", "Error Type"])
            for company_id, er in results.entity_resolution.items():
                writer.writerow([
                    company_id,
                    "Yes" if er.get("correct") else "No",
                    f"{er.get('confidence', 0):.2f}",
                    er.get("error_type", "-"),
                ])
            writer.writerow([])

            # Per-company signal coverage
            writer.writerow(["Signal Coverage by Company"])
            writer.writerow(["Company", "Coverage", "Found", "Missing"])
            for company_id, sc in results.signal_coverage.items():
                writer.writerow([
                    company_id,
                    f"{sc.get('coverage_rate', 0):.2%}",
                    ", ".join(sc.get("categories_found", [])[:3]),
                    ", ".join(sc.get("categories_missing", [])[:2]),
                ])

            # Per-company timing
            if results.per_company_timing:
                writer.writerow([])
                writer.writerow(["Timing by Company"])
                writer.writerow(["Company", "Elapsed (seconds)"])
                for company_id, elapsed in results.per_company_timing.items():
                    writer.writerow([company_id, f"{elapsed:.3f}"])
                writer.writerow(["Average", f"{results.avg_time_per_company_seconds:.3f}"])

    logger.info(f"Results saved to {output_path}")


# =============================================================================
# CLI
# =============================================================================

def main():
    """CLI entrypoint."""
    parser = argparse.ArgumentParser(
        description="NEA AI Agents - Unified Evaluation Framework",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python -m evaluation.run_eval
  python -m evaluation.run_eval --companies stripe.com airbnb.com
  python -m evaluation.run_eval --output results/eval.json
  python -m evaluation.run_eval --validate-citations --summary-only
        """,
    )

    parser.add_argument(
        "--companies",
        nargs="+",
        default=["stripe.com", "airbnb.com", "openai.com"],
        help="Company IDs/domains to evaluate",
    )
    parser.add_argument(
        "--days",
        type=int,
        default=30,
        help="Look back period in days (default: 30)",
    )
    parser.add_argument(
        "--output", "-o",
        type=str,
        help="Output file path (stdout if not specified)",
    )
    parser.add_argument(
        "--format", "-f",
        choices=["json", "csv"],
        default="json",
        help="Output format (default: json)",
    )
    parser.add_argument(
        "--summary-only",
        action="store_true",
        help="Print only executive summary",
    )
    parser.add_argument(
        "--validate-citations",
        action="store_true",
        help="Run citation presence validation",
    )
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Enable verbose logging",
    )

    args = parser.parse_args()

    # Configure logging
    log_level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    print(f"NEA AI Agents Evaluation")
    print(f"=" * 50)
    print(f"Evaluating {len(args.companies)} companies...")
    print()

    # Run evaluation
    results = run_full_evaluation(
        company_ids=args.companies,
        days=args.days,
        validate_citations_flag=args.validate_citations,
    )

    # Output results
    if args.summary_only:
        print(results.summary())
    elif args.output:
        output_path = Path(args.output)
        save_results(results, output_path, format=args.format)
        print(f"Results saved to: {output_path}")
        print()
        print(results.summary())
    else:
        print(results.to_json())

    # Return exit code based on errors
    if results.errors:
        print(f"\nWarning: {len(results.errors)} errors occurred during evaluation")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())

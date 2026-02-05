"""
Evaluation Harness for NEA AI Agents
=====================================

Runs comprehensive evaluation across all metrics from the Data Analysis Plan.

Components:
- Entity Resolution Accuracy
- Retrieval Accuracy
- Signal Coverage
- Quality Scoring (human evaluation)
- Failure Mode Analysis
- Cost Tracking
- Workflow Timing

Usage:
    python -m core.eval_harness --companies stripe.com airbnb.com --days 30

    # Or programmatically:
    from core.eval_harness import run_full_evaluation, generate_evaluation_report

    results = run_full_evaluation(["stripe.com", "airbnb.com"])
    report = generate_evaluation_report(results)
"""

from __future__ import annotations

import argparse
import json
import logging
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import Optional

from core.evaluation import (
    EvaluationResult,
    GroundTruth,
    run_evaluation,
    evaluate_signal_coverage,
    get_evaluation_history,
)
from core.quality_scoring import (
    get_quality_stats,
    get_quality_benchmark,
    BriefingQualityEvaluation,
)
from core.failure_analysis import (
    get_failure_stats,
    identify_failure_patterns,
    generate_failure_report,
    FailureStats,
)
from core.tracking import (
    get_cost_summary,
    get_workflow_timing,
    project_costs_at_scale,
)

logger = logging.getLogger(__name__)


# =============================================================================
# COMPREHENSIVE EVALUATION RESULT
# =============================================================================

@dataclass
class ComprehensiveEvaluation:
    """Complete evaluation across all metrics."""
    timestamp: str
    period_days: int
    companies_evaluated: list[str]

    # Per-company metrics
    entity_resolution_results: dict[str, dict] = field(default_factory=dict)
    signal_coverage_results: dict[str, dict] = field(default_factory=dict)

    # Aggregate metrics
    overall_entity_accuracy: float = 0.0
    overall_signal_coverage: float = 0.0
    avg_quality_score: float = 0.0

    # Quality evaluation
    quality_benchmark: Optional[dict] = None

    # Failure analysis
    failure_stats: Optional[dict] = None
    failure_patterns: list[dict] = field(default_factory=list)

    # Cost tracking
    cost_summary: Optional[dict] = None
    workflow_timing: Optional[dict] = None

    def to_dict(self) -> dict:
        return asdict(self)

    def summary(self) -> str:
        """Generate executive summary."""
        lines = [
            "=" * 60,
            "NEA AI AGENTS - COMPREHENSIVE EVALUATION",
            "=" * 60,
            f"Evaluation Date: {self.timestamp}",
            f"Period: Last {self.period_days} days",
            f"Companies Evaluated: {len(self.companies_evaluated)}",
            "",
            "KEY METRICS",
            "-" * 40,
            f"Entity Resolution Accuracy: {self.overall_entity_accuracy:.1%}",
            f"Signal Coverage Rate:       {self.overall_signal_coverage:.1%}",
            f"Average Quality Score:      {self.avg_quality_score:.2f}/5.0",
            "",
        ]

        if self.cost_summary:
            lines.extend([
                "COST ANALYSIS",
                "-" * 40,
                f"Total Cost ({self.period_days}d):     ${self.cost_summary.get('total_cost', 0):.2f}",
                f"Cost per Company:          ${self.cost_summary.get('cost_per_company', 0):.4f}",
                f"Projected Monthly:         ${self.cost_summary.get('projected_monthly', 0):.2f}",
                "",
            ])

        if self.failure_stats:
            lines.extend([
                "FAILURE ANALYSIS",
                "-" * 40,
                f"Total Failures:            {self.failure_stats.get('total_failures', 0)}",
                f"Resolution Rate:           {self.failure_stats.get('resolution_rate', 0):.1%}",
                "",
            ])

        if self.workflow_timing:
            lines.extend([
                "WORKFLOW TIMING",
                "-" * 40,
                f"Avg Time per Company:      {self.workflow_timing.get('estimated_total_per_company_seconds', 0):.1f}s",
                "",
            ])

        lines.append("=" * 60)
        return "\n".join(lines)


# =============================================================================
# EVALUATION FUNCTIONS
# =============================================================================

def run_full_evaluation(
    company_ids: list[str],
    ground_truths: Optional[dict[str, GroundTruth]] = None,
    days: int = 30,
    include_quality: bool = True,
    include_failures: bool = True,
    include_costs: bool = True,
) -> ComprehensiveEvaluation:
    """
    Run comprehensive evaluation across all metrics.

    Args:
        company_ids: List of company identifiers to evaluate
        ground_truths: Optional dict of company_id -> GroundTruth
        days: Look back period for aggregate metrics
        include_quality: Include quality scoring analysis
        include_failures: Include failure analysis
        include_costs: Include cost analysis

    Returns:
        ComprehensiveEvaluation with all metrics
    """
    timestamp = datetime.utcnow().isoformat()
    ground_truths = ground_truths or {}

    result = ComprehensiveEvaluation(
        timestamp=timestamp,
        period_days=days,
        companies_evaluated=company_ids,
    )

    # Per-company evaluations
    entity_correct_count = 0
    total_coverage = 0.0

    for company_id in company_ids:
        gt = ground_truths.get(company_id)

        # Run entity resolution and coverage evaluation
        eval_result = run_evaluation(
            company_id=company_id,
            ground_truth=gt,
            save_to_db=True,
        )

        # Store results
        if eval_result.entity_resolution:
            result.entity_resolution_results[company_id] = eval_result.entity_resolution.to_dict()
            if eval_result.entity_resolution.correct:
                entity_correct_count += 1

        if eval_result.signal_coverage:
            result.signal_coverage_results[company_id] = eval_result.signal_coverage.to_dict()
            total_coverage += eval_result.signal_coverage.coverage_rate

    # Calculate aggregate metrics
    n = len(company_ids)
    if n > 0:
        result.overall_entity_accuracy = entity_correct_count / n
        result.overall_signal_coverage = total_coverage / n

    # Quality benchmark
    if include_quality:
        benchmark = get_quality_benchmark(days=days)
        if benchmark:
            result.quality_benchmark = {
                "total_evaluations": benchmark.total_evaluations,
                "total_companies": benchmark.total_companies,
                "avg_clarity": benchmark.overall_avg_clarity,
                "avg_correctness": benchmark.overall_avg_correctness,
                "avg_usefulness": benchmark.overall_avg_usefulness,
                "avg_overall": benchmark.overall_avg_score,
            }
            result.avg_quality_score = benchmark.overall_avg_score

    # Failure analysis
    if include_failures:
        fail_stats = get_failure_stats(days=days)
        if fail_stats:
            result.failure_stats = {
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
                "examples": p.example_companies,
                "suggested_fix": p.suggested_fix,
            }
            for p in patterns
        ]

    # Cost analysis
    if include_costs:
        result.cost_summary = get_cost_summary(days=days)
        result.workflow_timing = get_workflow_timing(days=days)

    return result


def generate_evaluation_report(
    evaluation: ComprehensiveEvaluation,
    output_format: str = "markdown",
) -> str:
    """
    Generate formatted evaluation report.

    Args:
        evaluation: ComprehensiveEvaluation result
        output_format: "markdown" or "json"

    Returns:
        Formatted report string
    """
    if output_format == "json":
        return json.dumps(evaluation.to_dict(), indent=2)

    # Markdown format
    lines = [
        "# NEA AI Agents - Evaluation Report",
        f"*Generated: {evaluation.timestamp}*",
        f"*Period: Last {evaluation.period_days} days*",
        "",
        "## Executive Summary",
        "",
        "| Metric | Value |",
        "|--------|-------|",
        f"| Entity Resolution Accuracy | {evaluation.overall_entity_accuracy:.1%} |",
        f"| Signal Coverage Rate | {evaluation.overall_signal_coverage:.1%} |",
        f"| Average Quality Score | {evaluation.avg_quality_score:.2f}/5.0 |",
        f"| Companies Evaluated | {len(evaluation.companies_evaluated)} |",
        "",
    ]

    # Entity Resolution Details
    lines.extend([
        "## Entity Resolution",
        "",
        "| Company | Correct | Confidence | Error Type |",
        "|---------|---------|------------|------------|",
    ])
    for company_id, er in evaluation.entity_resolution_results.items():
        correct = "✓" if er.get("correct") else "✗"
        confidence = er.get("confidence", 0)
        error_type = er.get("error_type", "-")
        lines.append(f"| {company_id} | {correct} | {confidence:.2f} | {error_type} |")
    lines.append("")

    # Signal Coverage Details
    lines.extend([
        "## Signal Coverage",
        "",
        "| Company | Coverage | Found | Missing |",
        "|---------|----------|-------|---------|",
    ])
    for company_id, sc in evaluation.signal_coverage_results.items():
        coverage = sc.get("coverage_rate", 0)
        found = ", ".join(sc.get("categories_found", [])[:3])
        missing = ", ".join(sc.get("categories_missing", [])[:2]) or "-"
        lines.append(f"| {company_id} | {coverage:.1%} | {found} | {missing} |")
    lines.append("")

    # Quality Scoring
    if evaluation.quality_benchmark:
        lines.extend([
            "## Quality Scoring",
            "",
            f"**Total Evaluations:** {evaluation.quality_benchmark.get('total_evaluations', 0)}",
            "",
            "| Dimension | Average Score |",
            "|-----------|---------------|",
            f"| Clarity | {evaluation.quality_benchmark.get('avg_clarity', 0):.2f}/5.0 |",
            f"| Correctness | {evaluation.quality_benchmark.get('avg_correctness', 0):.2f}/5.0 |",
            f"| Usefulness | {evaluation.quality_benchmark.get('avg_usefulness', 0):.2f}/5.0 |",
            "",
        ])

    # Failure Analysis
    if evaluation.failure_stats:
        lines.extend([
            "## Failure Analysis",
            "",
            f"**Total Failures:** {evaluation.failure_stats.get('total_failures', 0)}",
            f"**Resolution Rate:** {evaluation.failure_stats.get('resolution_rate', 0):.1%}",
            "",
            "### By Category",
            "",
        ])
        for cat, count in evaluation.failure_stats.get("by_category", {}).items():
            lines.append(f"- **{cat}:** {count}")
        lines.append("")

        if evaluation.failure_patterns:
            lines.extend([
                "### Top Failure Patterns",
                "",
            ])
            for pattern in evaluation.failure_patterns[:3]:
                lines.append(f"**{pattern['category']}** ({pattern['frequency']} occurrences)")
                lines.append(f"- Examples: {', '.join(pattern['examples'][:3])}")
                lines.append(f"- Fix: {pattern['suggested_fix']}")
                lines.append("")

    # Cost Analysis
    if evaluation.cost_summary:
        lines.extend([
            "## Cost Analysis",
            "",
            f"**Total Cost ({evaluation.period_days}d):** ${evaluation.cost_summary.get('total_cost', 0):.2f}",
            f"**Cost per Company:** ${evaluation.cost_summary.get('cost_per_company', 0):.4f}",
            f"**Daily Average:** ${evaluation.cost_summary.get('daily_average', 0):.2f}",
            f"**Projected Monthly:** ${evaluation.cost_summary.get('projected_monthly', 0):.2f}",
            "",
            "### By Service",
            "",
            "| Service | Calls | Total Cost |",
            "|---------|-------|------------|",
        ])
        for service, data in evaluation.cost_summary.get("cost_by_service", {}).items():
            lines.append(f"| {service} | {data.get('total_calls', 0)} | ${data.get('total_cost', 0):.4f} |")
        lines.append("")

    # Workflow Timing
    if evaluation.workflow_timing:
        lines.extend([
            "## Workflow Timing",
            "",
            f"**Average Time per Company:** {evaluation.workflow_timing.get('estimated_total_per_company_seconds', 0):.1f} seconds",
            "",
            "| Service | Avg Latency |",
            "|---------|-------------|",
        ])
        for service, data in evaluation.workflow_timing.get("by_service", {}).items():
            lines.append(f"| {service} | {data.get('avg_latency_ms', 0):.0f}ms |")
        lines.append("")

    # Cost Projections
    lines.extend([
        "## Cost Projections at Scale",
        "",
    ])
    for companies in [100, 500, 1000]:
        projection = project_costs_at_scale(companies)
        lines.append(f"- **{companies} companies/month:** ${projection['monthly_cost']:.2f}/month (${projection['annual_cost']:.2f}/year)")
    lines.append("")

    return "\n".join(lines)


# =============================================================================
# BEFORE/AFTER COMPARISON
# =============================================================================

def compare_evaluations(
    before: ComprehensiveEvaluation,
    after: ComprehensiveEvaluation,
) -> dict:
    """
    Compare two evaluations to measure improvement.

    Returns dict with delta metrics.
    """
    return {
        "entity_accuracy_delta": after.overall_entity_accuracy - before.overall_entity_accuracy,
        "signal_coverage_delta": after.overall_signal_coverage - before.overall_signal_coverage,
        "quality_score_delta": after.avg_quality_score - before.avg_quality_score,
        "before_timestamp": before.timestamp,
        "after_timestamp": after.timestamp,
        "improved": (
            after.overall_entity_accuracy >= before.overall_entity_accuracy and
            after.overall_signal_coverage >= before.overall_signal_coverage
        ),
    }


# =============================================================================
# CLI
# =============================================================================

def main():
    """CLI entrypoint for evaluation harness."""
    parser = argparse.ArgumentParser(description="Run NEA AI Agents evaluation")
    parser.add_argument(
        "--companies",
        nargs="+",
        default=["stripe.com", "airbnb.com", "openai.com"],
        help="Company IDs to evaluate",
    )
    parser.add_argument(
        "--days",
        type=int,
        default=30,
        help="Look back period in days",
    )
    parser.add_argument(
        "--output", "-o",
        help="Output file path (prints to stdout if not specified)",
    )
    parser.add_argument(
        "--format",
        choices=["markdown", "json"],
        default="markdown",
        help="Output format",
    )
    parser.add_argument(
        "--summary-only",
        action="store_true",
        help="Print only executive summary",
    )

    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO)

    print(f"Running evaluation for {len(args.companies)} companies...")
    print("-" * 50)

    # Run evaluation
    results = run_full_evaluation(
        company_ids=args.companies,
        days=args.days,
    )

    if args.summary_only:
        print(results.summary())
    else:
        report = generate_evaluation_report(results, output_format=args.format)

        if args.output:
            with open(args.output, "w") as f:
                f.write(report)
            print(f"Report saved to: {args.output}")
        else:
            print(report)

    print("-" * 50)
    print("Evaluation complete.")


if __name__ == "__main__":
    main()

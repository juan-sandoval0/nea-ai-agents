"""
NEA AI Agents Evaluation Framework
===================================

Comprehensive evaluation for VC workflow automation agents.

Usage:
    python -m evaluation.run_eval --companies stripe.com airbnb.com
"""

from core.evaluation import (
    evaluate_entity_resolution,
    evaluate_retrieval_accuracy,
    evaluate_signal_coverage,
    run_evaluation,
    GroundTruth,
)
from core.quality_scoring import (
    submit_quality_score,
    get_quality_stats,
    get_quality_benchmark,
)
from core.failure_analysis import (
    FailureCategory,
    log_failure,
    get_failure_stats,
    generate_failure_report,
)
from core.tracking import (
    get_cost_summary,
    project_costs_at_scale,
    export_cost_summary,
    export_evaluation_costs,
)

__all__ = [
    "evaluate_entity_resolution",
    "evaluate_retrieval_accuracy",
    "evaluate_signal_coverage",
    "run_evaluation",
    "GroundTruth",
    "submit_quality_score",
    "get_quality_stats",
    "get_quality_benchmark",
    "FailureCategory",
    "log_failure",
    "get_failure_stats",
    "generate_failure_report",
    "get_cost_summary",
    "project_costs_at_scale",
    "export_cost_summary",
    "export_evaluation_costs",
]

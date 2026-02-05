"""
Quality Scoring Framework for NEA AI Agents
============================================

Human evaluator quality scoring on three dimensions:
- Clarity (1-5): How clear and well-organized is the presentation?
- Correctness (1-5): Is the information factually accurate?
- Usefulness (1-5): How useful is this for investment decisions?

Usage:
    from core.quality_scoring import (
        QualityScore,
        BriefingQualityEvaluation,
        submit_quality_score,
        get_quality_stats,
    )

    # Submit a quality score
    submit_quality_score(
        company_id="stripe.com",
        evaluator="ana",
        clarity=4,
        correctness=5,
        usefulness=4,
        comments="Good overview, missing recent news"
    )

    # Get aggregate stats
    stats = get_quality_stats("stripe.com")
"""

from __future__ import annotations

import json
import logging
import sqlite3
from dataclasses import dataclass, field, asdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional
from enum import IntEnum

logger = logging.getLogger(__name__)

DEFAULT_DB_PATH = Path(__file__).parent.parent / "data" / "nea_agents.db"


# =============================================================================
# SCORING DEFINITIONS
# =============================================================================

class ScoreLevel(IntEnum):
    """Quality score levels (1-5)."""
    POOR = 1
    BELOW_AVERAGE = 2
    AVERAGE = 3
    GOOD = 4
    EXCELLENT = 5


CLARITY_RUBRIC = {
    1: "Disorganized, hard to follow, missing sections",
    2: "Some structure but confusing, inconsistent formatting",
    3: "Acceptable organization, could be clearer",
    4: "Well-organized, easy to scan, good formatting",
    5: "Excellent structure, professional quality, perfectly scannable",
}

CORRECTNESS_RUBRIC = {
    1: "Multiple factual errors, wrong company data",
    2: "Some errors in key facts (funding, team, dates)",
    3: "Minor inaccuracies, mostly correct",
    4: "Accurate with trivial issues only",
    5: "Completely accurate, verified against sources",
}

USEFULNESS_RUBRIC = {
    1: "Not useful for investment decision, missing key info",
    2: "Limited value, missing important context",
    3: "Somewhat useful, covers basics",
    4: "Useful for meeting prep, actionable insights",
    5: "Highly valuable, comprehensive, ready for partner meeting",
}


# =============================================================================
# DATA MODELS
# =============================================================================

@dataclass
class QualityScore:
    """A single quality score submission."""
    company_id: str
    evaluator: str
    clarity: int          # 1-5
    correctness: int      # 1-5
    usefulness: int       # 1-5
    comments: Optional[str] = None
    briefing_version: Optional[str] = None  # To track which version was evaluated
    timestamp: str = field(default_factory=lambda: datetime.utcnow().isoformat())

    def __post_init__(self):
        # Validate scores are 1-5
        for score_name in ["clarity", "correctness", "usefulness"]:
            score = getattr(self, score_name)
            if not 1 <= score <= 5:
                raise ValueError(f"{score_name} must be between 1 and 5, got {score}")

    @property
    def average_score(self) -> float:
        """Calculate average of three dimensions."""
        return (self.clarity + self.correctness + self.usefulness) / 3

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class BriefingQualityEvaluation:
    """Aggregate quality evaluation for a briefing."""
    company_id: str
    num_evaluations: int
    avg_clarity: float
    avg_correctness: float
    avg_usefulness: float
    avg_overall: float
    std_clarity: float = 0.0
    std_correctness: float = 0.0
    std_usefulness: float = 0.0
    evaluators: list[str] = field(default_factory=list)
    comments: list[str] = field(default_factory=list)

    def summary(self) -> str:
        """Generate human-readable summary."""
        return f"""Quality Evaluation: {self.company_id}
Evaluations: {self.num_evaluations}
Average Scores:
  Clarity:     {self.avg_clarity:.2f}/5.0 (±{self.std_clarity:.2f})
  Correctness: {self.avg_correctness:.2f}/5.0 (±{self.std_correctness:.2f})
  Usefulness:  {self.avg_usefulness:.2f}/5.0 (±{self.std_usefulness:.2f})
  Overall:     {self.avg_overall:.2f}/5.0

Evaluators: {', '.join(self.evaluators)}"""


@dataclass
class QualityBenchmark:
    """Quality benchmarks across all evaluated companies."""
    total_evaluations: int
    total_companies: int
    overall_avg_clarity: float
    overall_avg_correctness: float
    overall_avg_usefulness: float
    overall_avg_score: float
    top_companies: list[tuple[str, float]]  # (company_id, avg_score)
    bottom_companies: list[tuple[str, float]]


# =============================================================================
# DATABASE OPERATIONS
# =============================================================================

def _init_quality_schema(db_path: Path = DEFAULT_DB_PATH):
    """Initialize quality scoring tables."""
    conn = sqlite3.connect(str(db_path))
    try:
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS quality_scores (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                company_id TEXT NOT NULL,
                evaluator TEXT NOT NULL,
                clarity INTEGER NOT NULL,
                correctness INTEGER NOT NULL,
                usefulness INTEGER NOT NULL,
                comments TEXT,
                briefing_version TEXT,
                timestamp TEXT NOT NULL,
                UNIQUE(company_id, evaluator, timestamp)
            )
        """)
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_quality_company ON quality_scores(company_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_quality_evaluator ON quality_scores(evaluator)")
        conn.commit()
    finally:
        conn.close()


def submit_quality_score(
    company_id: str,
    evaluator: str,
    clarity: int,
    correctness: int,
    usefulness: int,
    comments: Optional[str] = None,
    briefing_version: Optional[str] = None,
    db_path: Path = DEFAULT_DB_PATH,
) -> QualityScore:
    """
    Submit a quality score for a briefing.

    Args:
        company_id: Target company identifier
        evaluator: Name/ID of the human evaluator
        clarity: Score 1-5 for presentation clarity
        correctness: Score 1-5 for factual accuracy
        usefulness: Score 1-5 for investment decision utility
        comments: Optional free-form feedback
        briefing_version: Optional version identifier

    Returns:
        The submitted QualityScore
    """
    score = QualityScore(
        company_id=company_id,
        evaluator=evaluator,
        clarity=clarity,
        correctness=correctness,
        usefulness=usefulness,
        comments=comments,
        briefing_version=briefing_version,
    )

    _init_quality_schema(db_path)

    conn = sqlite3.connect(str(db_path))
    try:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO quality_scores
            (company_id, evaluator, clarity, correctness, usefulness, comments, briefing_version, timestamp)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            score.company_id,
            score.evaluator,
            score.clarity,
            score.correctness,
            score.usefulness,
            score.comments,
            score.briefing_version,
            score.timestamp,
        ))
        conn.commit()
        logger.info(f"Submitted quality score for {company_id} by {evaluator}")
    finally:
        conn.close()

    return score


def get_quality_scores(
    company_id: str,
    db_path: Path = DEFAULT_DB_PATH,
) -> list[QualityScore]:
    """Get all quality scores for a company."""
    _init_quality_schema(db_path)

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    try:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT * FROM quality_scores
            WHERE company_id = ?
            ORDER BY timestamp DESC
        """, (company_id,))

        scores = []
        for row in cursor.fetchall():
            scores.append(QualityScore(
                company_id=row["company_id"],
                evaluator=row["evaluator"],
                clarity=row["clarity"],
                correctness=row["correctness"],
                usefulness=row["usefulness"],
                comments=row["comments"],
                briefing_version=row["briefing_version"],
                timestamp=row["timestamp"],
            ))
        return scores
    finally:
        conn.close()


def get_quality_stats(
    company_id: str,
    db_path: Path = DEFAULT_DB_PATH,
) -> Optional[BriefingQualityEvaluation]:
    """
    Get aggregate quality statistics for a company.

    Returns:
        BriefingQualityEvaluation with averages and std devs, or None if no scores
    """
    scores = get_quality_scores(company_id, db_path)
    if not scores:
        return None

    n = len(scores)
    clarities = [s.clarity for s in scores]
    correctnesses = [s.correctness for s in scores]
    usefulnesses = [s.usefulness for s in scores]

    def mean(lst):
        return sum(lst) / len(lst) if lst else 0.0

    def std(lst):
        if len(lst) < 2:
            return 0.0
        m = mean(lst)
        return (sum((x - m) ** 2 for x in lst) / len(lst)) ** 0.5

    avg_clarity = mean(clarities)
    avg_correctness = mean(correctnesses)
    avg_usefulness = mean(usefulnesses)
    avg_overall = (avg_clarity + avg_correctness + avg_usefulness) / 3

    return BriefingQualityEvaluation(
        company_id=company_id,
        num_evaluations=n,
        avg_clarity=avg_clarity,
        avg_correctness=avg_correctness,
        avg_usefulness=avg_usefulness,
        avg_overall=avg_overall,
        std_clarity=std(clarities),
        std_correctness=std(correctnesses),
        std_usefulness=std(usefulnesses),
        evaluators=list(set(s.evaluator for s in scores)),
        comments=[s.comments for s in scores if s.comments],
    )


def get_quality_benchmark(
    days: int = 30,
    db_path: Path = DEFAULT_DB_PATH,
) -> Optional[QualityBenchmark]:
    """
    Get quality benchmarks across all evaluated companies.

    Args:
        days: Look back period
        db_path: Database path

    Returns:
        QualityBenchmark with aggregate stats
    """
    _init_quality_schema(db_path)

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    try:
        cursor = conn.cursor()
        cutoff = (datetime.utcnow() - timedelta(days=days)).isoformat()

        # Get aggregate stats
        cursor.execute("""
            SELECT
                COUNT(*) as total_evaluations,
                COUNT(DISTINCT company_id) as total_companies,
                AVG(clarity) as avg_clarity,
                AVG(correctness) as avg_correctness,
                AVG(usefulness) as avg_usefulness
            FROM quality_scores
            WHERE timestamp >= ?
        """, (cutoff,))
        row = cursor.fetchone()

        if not row or row["total_evaluations"] == 0:
            return None

        # Get top companies
        cursor.execute("""
            SELECT company_id, AVG((clarity + correctness + usefulness) / 3.0) as avg_score
            FROM quality_scores
            WHERE timestamp >= ?
            GROUP BY company_id
            ORDER BY avg_score DESC
            LIMIT 5
        """, (cutoff,))
        top_companies = [(r["company_id"], r["avg_score"]) for r in cursor.fetchall()]

        # Get bottom companies
        cursor.execute("""
            SELECT company_id, AVG((clarity + correctness + usefulness) / 3.0) as avg_score
            FROM quality_scores
            WHERE timestamp >= ?
            GROUP BY company_id
            ORDER BY avg_score ASC
            LIMIT 5
        """, (cutoff,))
        bottom_companies = [(r["company_id"], r["avg_score"]) for r in cursor.fetchall()]

        avg_overall = (row["avg_clarity"] + row["avg_correctness"] + row["avg_usefulness"]) / 3

        return QualityBenchmark(
            total_evaluations=row["total_evaluations"],
            total_companies=row["total_companies"],
            overall_avg_clarity=row["avg_clarity"],
            overall_avg_correctness=row["avg_correctness"],
            overall_avg_usefulness=row["avg_usefulness"],
            overall_avg_score=avg_overall,
            top_companies=top_companies,
            bottom_companies=bottom_companies,
        )
    finally:
        conn.close()


# =============================================================================
# SCORING HELPERS
# =============================================================================

def get_score_rubric() -> dict:
    """Return the scoring rubric for reference."""
    return {
        "clarity": CLARITY_RUBRIC,
        "correctness": CORRECTNESS_RUBRIC,
        "usefulness": USEFULNESS_RUBRIC,
    }


def validate_score(dimension: str, score: int) -> tuple[bool, str]:
    """
    Validate a score and return guidance.

    Returns:
        Tuple of (is_valid, guidance_text)
    """
    if not 1 <= score <= 5:
        return False, f"Score must be 1-5, got {score}"

    rubrics = {
        "clarity": CLARITY_RUBRIC,
        "correctness": CORRECTNESS_RUBRIC,
        "usefulness": USEFULNESS_RUBRIC,
    }

    rubric = rubrics.get(dimension)
    if rubric:
        return True, rubric.get(score, "")
    return True, ""

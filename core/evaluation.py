"""
Evaluation Metrics for NEA AI Agents
====================================

Implements the Data Analysis Plan metrics:
- Entity Resolution Accuracy
- Retrieval Accuracy
- Signal Coverage
- Comparative Pipeline Evaluation

Usage:
    from core.evaluation import (
        EvaluationResult,
        evaluate_entity_resolution,
        evaluate_retrieval_accuracy,
        evaluate_signal_coverage,
        run_evaluation,
    )

    # Run full evaluation on a company
    result = run_evaluation("stripe.com", ground_truth=ground_truth_data)
    print(result.summary())
"""

from __future__ import annotations

import json
import logging
import sqlite3
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import Optional, Literal
from enum import Enum

logger = logging.getLogger(__name__)

# Database path for evaluation results
DEFAULT_DB_PATH = Path(__file__).parent.parent / "data" / "nea_agents.db"


# =============================================================================
# SIGNAL COVERAGE CATEGORIES
# =============================================================================

class SignalCategory(str, Enum):
    """Categories of signals the agent should extract."""
    PRODUCT = "product"           # Product characteristics
    PRICING = "pricing"           # Pricing models
    TEAM = "team"                 # Team composition
    NEWS = "news"                 # Recent news
    FUNDING = "funding"           # Funding information
    TRACTION = "traction"         # Web traffic, growth metrics
    WEBSITE = "website"           # Website updates


SIGNAL_TYPE_TO_CATEGORY = {
    # Harmonic signals
    "web_traffic": SignalCategory.TRACTION,
    "hiring": SignalCategory.TEAM,
    "funding": SignalCategory.FUNDING,
    # Tavily signals
    "website_product": SignalCategory.PRODUCT,
    "website_pricing": SignalCategory.PRICING,
    "website_team": SignalCategory.TEAM,
    "website_news": SignalCategory.NEWS,
    "website_update": SignalCategory.WEBSITE,
    # Parallel Search signals
    "acquisition": SignalCategory.FUNDING,
    "team_change": SignalCategory.TEAM,
    "product_launch": SignalCategory.PRODUCT,
    "partnership": SignalCategory.NEWS,
    "news_coverage": SignalCategory.NEWS,
}


# =============================================================================
# DATA MODELS
# =============================================================================

@dataclass
class EntityResolutionResult:
    """Result of entity resolution evaluation."""
    company_id: str
    intended_company: str              # What company we wanted
    resolved_company: Optional[str]    # What company we got
    correct: bool                      # Did we get the right one?
    confidence: float                  # 0.0 to 1.0
    error_type: Optional[str] = None   # "naming_ambiguity", "domain_mismatch", etc.
    details: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class RetrievalAccuracyResult:
    """Result of retrieval accuracy evaluation."""
    company_id: str
    source: str                        # "tavily", "parallel", "harmonic"
    total_retrieved: int               # Total items retrieved
    relevant_count: int                # Items actually about target company
    irrelevant_count: int              # Items NOT about target company
    precision: float                   # relevant / total
    irrelevant_items: list[dict] = field(default_factory=list)  # Details of wrong items

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class SignalCoverageResult:
    """Result of signal coverage evaluation."""
    company_id: str
    categories_expected: list[str]     # Categories we should have
    categories_found: list[str]        # Categories we actually extracted
    categories_missing: list[str]      # Categories we failed to extract
    coverage_rate: float               # found / expected (0.0 to 1.0)
    signal_details: dict = field(default_factory=dict)  # Per-category details

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class EvaluationResult:
    """Complete evaluation result for a company."""
    company_id: str
    timestamp: str
    entity_resolution: Optional[EntityResolutionResult] = None
    retrieval_accuracy: dict[str, RetrievalAccuracyResult] = field(default_factory=dict)
    signal_coverage: Optional[SignalCoverageResult] = None
    overall_score: float = 0.0  # Weighted composite score

    def to_dict(self) -> dict:
        result = {
            "company_id": self.company_id,
            "timestamp": self.timestamp,
            "overall_score": self.overall_score,
        }
        if self.entity_resolution:
            result["entity_resolution"] = self.entity_resolution.to_dict()
        if self.retrieval_accuracy:
            result["retrieval_accuracy"] = {
                k: v.to_dict() for k, v in self.retrieval_accuracy.items()
            }
        if self.signal_coverage:
            result["signal_coverage"] = self.signal_coverage.to_dict()
        return result

    def summary(self) -> str:
        """Generate human-readable summary."""
        lines = [
            f"=== Evaluation: {self.company_id} ===",
            f"Timestamp: {self.timestamp}",
            f"Overall Score: {self.overall_score:.2f}",
            "",
        ]

        if self.entity_resolution:
            lines.append("Entity Resolution:")
            lines.append(f"  Correct: {self.entity_resolution.correct}")
            lines.append(f"  Confidence: {self.entity_resolution.confidence:.2f}")
            if self.entity_resolution.error_type:
                lines.append(f"  Error Type: {self.entity_resolution.error_type}")
            lines.append("")

        if self.retrieval_accuracy:
            lines.append("Retrieval Accuracy:")
            for source, result in self.retrieval_accuracy.items():
                lines.append(f"  {source}: {result.precision:.2f} ({result.relevant_count}/{result.total_retrieved})")
            lines.append("")

        if self.signal_coverage:
            lines.append("Signal Coverage:")
            lines.append(f"  Coverage Rate: {self.signal_coverage.coverage_rate:.2f}")
            lines.append(f"  Found: {', '.join(self.signal_coverage.categories_found)}")
            if self.signal_coverage.categories_missing:
                lines.append(f"  Missing: {', '.join(self.signal_coverage.categories_missing)}")

        return "\n".join(lines)


# =============================================================================
# GROUND TRUTH DATA MODEL
# =============================================================================

@dataclass
class GroundTruth:
    """Ground truth data for a company (from official sources)."""
    company_id: str
    company_name: str
    domain: str
    description: Optional[str] = None
    founding_date: Optional[str] = None
    hq: Optional[str] = None
    employee_count: Optional[int] = None
    total_funding: Optional[float] = None
    founders: list[str] = field(default_factory=list)
    industry: Optional[str] = None
    source: str = "manual"  # "pitchbook", "harmonic_verified", "manual"

    @classmethod
    def from_dict(cls, data: dict) -> GroundTruth:
        return cls(**data)


# =============================================================================
# ENTITY RESOLUTION EVALUATION
# =============================================================================

def evaluate_entity_resolution(
    company_id: str,
    ground_truth: Optional[GroundTruth] = None,
    retrieved_data: Optional[dict] = None,
) -> EntityResolutionResult:
    """
    Evaluate whether the agent correctly identified the intended company.

    Checks:
    - Company name matches (fuzzy)
    - Domain matches
    - No confusion with similarly named entities

    Args:
        company_id: The company identifier used for lookup
        ground_truth: Optional ground truth data for comparison
        retrieved_data: The data retrieved by the agent

    Returns:
        EntityResolutionResult with accuracy assessment
    """
    if retrieved_data is None:
        # Fetch from database
        from core.database import Database
        db = Database()
        company = db.get_company(company_id)
        if company:
            retrieved_data = {
                "company_name": company.company_name,
                "domain": company_id,
            }

    if retrieved_data is None:
        return EntityResolutionResult(
            company_id=company_id,
            intended_company=ground_truth.company_name if ground_truth else company_id,
            resolved_company=None,
            correct=False,
            confidence=0.0,
            error_type="not_found",
        )

    resolved_name = retrieved_data.get("company_name", "Unknown")

    # If no ground truth, we can only do basic validation
    if ground_truth is None:
        return EntityResolutionResult(
            company_id=company_id,
            intended_company=company_id,
            resolved_company=resolved_name,
            correct=True,  # Assume correct if we got something
            confidence=0.5,  # Low confidence without ground truth
            details={"note": "No ground truth provided for validation"},
        )

    # Compare with ground truth
    correct = False
    confidence = 0.0
    error_type = None
    details = {}

    # Check name similarity
    name_match = _fuzzy_name_match(resolved_name, ground_truth.company_name)
    details["name_similarity"] = name_match

    # Check domain match
    domain_match = _domain_matches(company_id, ground_truth.domain)
    details["domain_match"] = domain_match

    if name_match >= 0.8 and domain_match:
        correct = True
        confidence = min(1.0, (name_match + (1.0 if domain_match else 0.0)) / 2)
    elif name_match >= 0.8:
        correct = True
        confidence = name_match * 0.8  # Reduce confidence if domain doesn't match
    elif domain_match:
        # Domain matches but name is different - could be rebrand or error
        correct = True
        confidence = 0.6
        error_type = "name_mismatch"
    else:
        correct = False
        confidence = name_match * 0.5
        error_type = "naming_ambiguity"

    return EntityResolutionResult(
        company_id=company_id,
        intended_company=ground_truth.company_name,
        resolved_company=resolved_name,
        correct=correct,
        confidence=confidence,
        error_type=error_type,
        details=details,
    )


def _fuzzy_name_match(name1: str, name2: str) -> float:
    """Calculate fuzzy similarity between two company names."""
    if not name1 or not name2:
        return 0.0

    # Normalize names
    n1 = name1.lower().strip()
    n2 = name2.lower().strip()

    # Exact match
    if n1 == n2:
        return 1.0

    # Remove common suffixes
    suffixes = [" inc", " inc.", " llc", " ltd", " corp", " corporation", " co", " co."]
    for suffix in suffixes:
        n1 = n1.replace(suffix, "")
        n2 = n2.replace(suffix, "")

    if n1 == n2:
        return 0.95

    # Check if one contains the other
    if n1 in n2 or n2 in n1:
        return 0.85

    # Simple character-level similarity (Jaccard on character bigrams)
    def bigrams(s):
        return set(s[i:i+2] for i in range(len(s) - 1))

    b1, b2 = bigrams(n1), bigrams(n2)
    if not b1 or not b2:
        return 0.0

    intersection = len(b1 & b2)
    union = len(b1 | b2)
    return intersection / union if union > 0 else 0.0


def _domain_matches(domain1: str, domain2: str) -> bool:
    """Check if two domains refer to the same company."""
    if not domain1 or not domain2:
        return False

    # Normalize domains
    d1 = domain1.lower().replace("www.", "").replace("https://", "").replace("http://", "").strip("/")
    d2 = domain2.lower().replace("www.", "").replace("https://", "").replace("http://", "").strip("/")

    return d1 == d2


# =============================================================================
# RETRIEVAL ACCURACY EVALUATION
# =============================================================================

def evaluate_retrieval_accuracy(
    company_id: str,
    source: str,
    retrieved_items: list[dict],
    ground_truth_name: Optional[str] = None,
) -> RetrievalAccuracyResult:
    """
    Evaluate what proportion of retrieved content references the target company.

    Args:
        company_id: Target company identifier
        source: Data source ("tavily", "parallel", "harmonic")
        retrieved_items: List of retrieved items with 'content' or 'headline' fields
        ground_truth_name: Optional verified company name

    Returns:
        RetrievalAccuracyResult with precision metrics
    """
    if not retrieved_items:
        return RetrievalAccuracyResult(
            company_id=company_id,
            source=source,
            total_retrieved=0,
            relevant_count=0,
            irrelevant_count=0,
            precision=1.0,  # No items = no errors
        )

    # Get company name for matching
    company_name = ground_truth_name
    if not company_name:
        from core.database import Database
        db = Database()
        company = db.get_company(company_id)
        company_name = company.company_name if company else company_id.split(".")[0]

    relevant_count = 0
    irrelevant_items = []

    for item in retrieved_items:
        content = item.get("content", "") or item.get("headline", "") or item.get("description", "")
        url = item.get("url", "")

        if _content_references_company(content, url, company_name, company_id):
            relevant_count += 1
        else:
            irrelevant_items.append({
                "content_preview": content[:200] if content else "",
                "url": url,
                "reason": "Company name not found in content",
            })

    total = len(retrieved_items)
    irrelevant_count = total - relevant_count
    precision = relevant_count / total if total > 0 else 1.0

    return RetrievalAccuracyResult(
        company_id=company_id,
        source=source,
        total_retrieved=total,
        relevant_count=relevant_count,
        irrelevant_count=irrelevant_count,
        precision=precision,
        irrelevant_items=irrelevant_items,
    )


def _content_references_company(
    content: str,
    url: str,
    company_name: str,
    domain: str,
) -> bool:
    """Check if content or URL references the target company."""
    if not content and not url:
        return False

    content_lower = (content or "").lower()
    url_lower = (url or "").lower()
    name_lower = company_name.lower()
    domain_lower = domain.lower().replace("www.", "")

    # Check URL contains domain
    if domain_lower in url_lower:
        return True

    # Check content contains company name
    if name_lower in content_lower:
        return True

    # Check for common variations
    name_parts = name_lower.split()
    if len(name_parts) > 1 and name_parts[0] in content_lower:
        return True

    return False


# =============================================================================
# SIGNAL COVERAGE EVALUATION
# =============================================================================

def evaluate_signal_coverage(
    company_id: str,
    expected_categories: Optional[list[str]] = None,
) -> SignalCoverageResult:
    """
    Evaluate which signal categories were successfully extracted.

    Args:
        company_id: Target company identifier
        expected_categories: List of expected categories (defaults to all)

    Returns:
        SignalCoverageResult with coverage metrics
    """
    from core.database import Database
    db = Database()

    # Default: expect all categories
    if expected_categories is None:
        expected_categories = [c.value for c in SignalCategory]

    # Get signals from database
    signals = db.get_signals(company_id)
    founders = db.get_founders(company_id)
    news = db.get_news(company_id)
    company = db.get_company(company_id)

    # Determine which categories we found
    found_categories = set()
    signal_details = {}

    # Check signals
    for signal in signals:
        category = SIGNAL_TYPE_TO_CATEGORY.get(signal.signal_type)
        if category:
            found_categories.add(category.value)
            if category.value not in signal_details:
                signal_details[category.value] = []
            signal_details[category.value].append({
                "type": signal.signal_type,
                "source": signal.source,
            })

    # Check founders (team coverage)
    if founders:
        found_categories.add(SignalCategory.TEAM.value)
        signal_details[SignalCategory.TEAM.value] = signal_details.get(SignalCategory.TEAM.value, [])
        signal_details[SignalCategory.TEAM.value].append({
            "type": "founders",
            "count": len(founders),
        })

    # Check news
    if news:
        found_categories.add(SignalCategory.NEWS.value)
        signal_details[SignalCategory.NEWS.value] = signal_details.get(SignalCategory.NEWS.value, [])
        signal_details[SignalCategory.NEWS.value].append({
            "type": "news_articles",
            "count": len(news),
        })

    # Check company core for funding
    if company and company.total_funding:
        found_categories.add(SignalCategory.FUNDING.value)
        signal_details[SignalCategory.FUNDING.value] = signal_details.get(SignalCategory.FUNDING.value, [])
        signal_details[SignalCategory.FUNDING.value].append({
            "type": "funding_total",
            "value": company.total_funding,
        })

    # Check company core for product info
    if company and company.products:
        found_categories.add(SignalCategory.PRODUCT.value)
        signal_details[SignalCategory.PRODUCT.value] = signal_details.get(SignalCategory.PRODUCT.value, [])
        signal_details[SignalCategory.PRODUCT.value].append({
            "type": "product_description",
            "source": "harmonic",
        })

    # Calculate coverage
    found_list = list(found_categories)
    missing_list = [c for c in expected_categories if c not in found_categories]
    coverage_rate = len(found_list) / len(expected_categories) if expected_categories else 0.0

    return SignalCoverageResult(
        company_id=company_id,
        categories_expected=expected_categories,
        categories_found=found_list,
        categories_missing=missing_list,
        coverage_rate=coverage_rate,
        signal_details=signal_details,
    )


# =============================================================================
# FULL EVALUATION
# =============================================================================

def run_evaluation(
    company_id: str,
    ground_truth: Optional[GroundTruth] = None,
    include_retrieval: bool = True,
    save_to_db: bool = True,
) -> EvaluationResult:
    """
    Run complete evaluation for a company.

    Args:
        company_id: Target company identifier
        ground_truth: Optional ground truth data
        include_retrieval: Whether to evaluate retrieval accuracy
        save_to_db: Whether to save results to database

    Returns:
        Complete EvaluationResult
    """
    timestamp = datetime.utcnow().isoformat()

    result = EvaluationResult(
        company_id=company_id,
        timestamp=timestamp,
    )

    # Entity resolution
    result.entity_resolution = evaluate_entity_resolution(
        company_id=company_id,
        ground_truth=ground_truth,
    )

    # Signal coverage
    result.signal_coverage = evaluate_signal_coverage(company_id=company_id)

    # Calculate overall score (weighted average)
    scores = []
    weights = []

    if result.entity_resolution:
        scores.append(1.0 if result.entity_resolution.correct else 0.0)
        weights.append(0.3)  # 30% weight for entity resolution

    if result.signal_coverage:
        scores.append(result.signal_coverage.coverage_rate)
        weights.append(0.4)  # 40% weight for coverage

    if result.retrieval_accuracy:
        avg_precision = sum(r.precision for r in result.retrieval_accuracy.values()) / len(result.retrieval_accuracy)
        scores.append(avg_precision)
        weights.append(0.3)  # 30% weight for retrieval accuracy

    if scores and weights:
        result.overall_score = sum(s * w for s, w in zip(scores, weights)) / sum(weights)

    # Save to database
    if save_to_db:
        _save_evaluation_result(result)

    return result


def _save_evaluation_result(result: EvaluationResult):
    """Save evaluation result to database."""
    conn = sqlite3.connect(str(DEFAULT_DB_PATH))
    try:
        cursor = conn.cursor()

        # Create table if not exists
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS evaluation_results (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                company_id TEXT NOT NULL,
                timestamp TEXT NOT NULL,
                overall_score REAL,
                entity_correct INTEGER,
                entity_confidence REAL,
                coverage_rate REAL,
                result_json TEXT NOT NULL
            )
        """)

        cursor.execute("""
            INSERT INTO evaluation_results
            (company_id, timestamp, overall_score, entity_correct, entity_confidence, coverage_rate, result_json)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (
            result.company_id,
            result.timestamp,
            result.overall_score,
            1 if result.entity_resolution and result.entity_resolution.correct else 0,
            result.entity_resolution.confidence if result.entity_resolution else 0.0,
            result.signal_coverage.coverage_rate if result.signal_coverage else 0.0,
            json.dumps(result.to_dict()),
        ))

        conn.commit()
        logger.info(f"Saved evaluation result for {result.company_id}")
    finally:
        conn.close()


def get_evaluation_history(
    company_id: Optional[str] = None,
    limit: int = 100,
) -> list[dict]:
    """Get evaluation history from database."""
    conn = sqlite3.connect(str(DEFAULT_DB_PATH))
    conn.row_factory = sqlite3.Row
    try:
        cursor = conn.cursor()

        if company_id:
            cursor.execute("""
                SELECT * FROM evaluation_results
                WHERE company_id = ?
                ORDER BY timestamp DESC
                LIMIT ?
            """, (company_id, limit))
        else:
            cursor.execute("""
                SELECT * FROM evaluation_results
                ORDER BY timestamp DESC
                LIMIT ?
            """, (limit,))

        return [dict(row) for row in cursor.fetchall()]
    except sqlite3.OperationalError:
        return []  # Table doesn't exist yet
    finally:
        conn.close()

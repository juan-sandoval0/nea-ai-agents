"""
Failure Mode Analysis for NEA AI Agents
========================================

Documents and categorizes system failures for improvement tracking.

Failure Categories:
- NAMING_AMBIGUITY: Multiple companies share similar names
- DOMAIN_MAPPING: Wrong domain-to-company mapping
- MISSING_HARMONIC: Harmonic data incomplete or unavailable
- TANGENTIAL_CONTENT: Retrieved content only loosely related
- API_ERROR: External API failures
- DATA_QUALITY: Poor quality source data
- LLM_HALLUCINATION: LLM generated unsupported content

Usage:
    from core.failure_analysis import (
        FailureCategory,
        log_failure,
        get_failure_stats,
        get_failure_examples,
    )

    # Log a failure
    log_failure(
        company_id="stripe.com",
        category=FailureCategory.NAMING_AMBIGUITY,
        description="Confused with Stripe Payments LLC",
        details={"retrieved_name": "Stripe Payments LLC"}
    )

    # Get failure patterns
    stats = get_failure_stats()
"""

from __future__ import annotations

import json
import logging
import sqlite3
from dataclasses import dataclass, field, asdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional
from enum import Enum

logger = logging.getLogger(__name__)

DEFAULT_DB_PATH = Path(__file__).parent.parent / "data" / "nea_agents.db"


# =============================================================================
# FAILURE CATEGORIES
# =============================================================================

class FailureCategory(str, Enum):
    """Categories of system failures."""
    NAMING_AMBIGUITY = "naming_ambiguity"       # Multiple companies with similar names
    DOMAIN_MAPPING = "domain_mapping"           # Wrong domain-to-company mapping
    MISSING_HARMONIC = "missing_harmonic"       # Harmonic data incomplete/unavailable
    TANGENTIAL_CONTENT = "tangential_content"   # Retrieved content loosely related
    API_ERROR = "api_error"                     # External API failures
    DATA_QUALITY = "data_quality"               # Poor quality source data
    LLM_HALLUCINATION = "llm_hallucination"     # LLM generated unsupported content
    ENTITY_NOT_FOUND = "entity_not_found"       # Company not found in any source
    TIMEOUT = "timeout"                         # Operation timed out
    RATE_LIMIT = "rate_limit"                   # API rate limit hit
    OTHER = "other"                             # Uncategorized failures


CATEGORY_DESCRIPTIONS = {
    FailureCategory.NAMING_AMBIGUITY: "Multiple companies share similar names, causing confusion",
    FailureCategory.DOMAIN_MAPPING: "Website domain mapped to wrong company entity",
    FailureCategory.MISSING_HARMONIC: "Harmonic database missing or has incomplete data for company",
    FailureCategory.TANGENTIAL_CONTENT: "Retrieved content mentions company but isn't directly about it",
    FailureCategory.API_ERROR: "External API returned error or unexpected response",
    FailureCategory.DATA_QUALITY: "Source data is outdated, inconsistent, or malformed",
    FailureCategory.LLM_HALLUCINATION: "LLM generated facts not supported by source data",
    FailureCategory.ENTITY_NOT_FOUND: "Company could not be found in any data source",
    FailureCategory.TIMEOUT: "Operation exceeded time limit",
    FailureCategory.RATE_LIMIT: "API rate limit exceeded",
    FailureCategory.OTHER: "Failure doesn't fit other categories",
}


# =============================================================================
# DATA MODELS
# =============================================================================

@dataclass
class FailureRecord:
    """A single failure record."""
    company_id: str
    category: FailureCategory
    description: str
    severity: str = "medium"  # "low", "medium", "high", "critical"
    source: Optional[str] = None  # "harmonic", "tavily", "parallel", "llm"
    details: dict = field(default_factory=dict)
    timestamp: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    resolved: bool = False
    resolution_notes: Optional[str] = None

    def to_dict(self) -> dict:
        d = asdict(self)
        d["category"] = self.category.value
        return d


@dataclass
class FailureStats:
    """Aggregate failure statistics."""
    total_failures: int
    failures_by_category: dict[str, int]
    failures_by_severity: dict[str, int]
    failures_by_source: dict[str, int]
    most_affected_companies: list[tuple[str, int]]
    resolution_rate: float  # Percentage of resolved failures
    period_days: int


@dataclass
class FailurePattern:
    """Identified pattern in failures."""
    category: FailureCategory
    frequency: int
    example_companies: list[str]
    common_characteristics: list[str]
    suggested_fix: Optional[str] = None


# =============================================================================
# DATABASE OPERATIONS
# =============================================================================

def _init_failure_schema(db_path: Path = DEFAULT_DB_PATH):
    """Initialize failure tracking tables."""
    conn = sqlite3.connect(str(db_path))
    try:
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS failure_records (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                company_id TEXT NOT NULL,
                category TEXT NOT NULL,
                description TEXT NOT NULL,
                severity TEXT DEFAULT 'medium',
                source TEXT,
                details TEXT DEFAULT '{}',
                timestamp TEXT NOT NULL,
                resolved INTEGER DEFAULT 0,
                resolution_notes TEXT
            )
        """)
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_failure_company ON failure_records(company_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_failure_category ON failure_records(category)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_failure_timestamp ON failure_records(timestamp)")
        conn.commit()
    finally:
        conn.close()


def log_failure(
    company_id: str,
    category: FailureCategory,
    description: str,
    severity: str = "medium",
    source: Optional[str] = None,
    details: Optional[dict] = None,
    db_path: Path = DEFAULT_DB_PATH,
) -> int:
    """
    Log a failure record.

    Args:
        company_id: Target company identifier
        category: Failure category
        description: Human-readable description of the failure
        severity: "low", "medium", "high", or "critical"
        source: Data source where failure occurred
        details: Additional structured details

    Returns:
        ID of the created failure record
    """
    if severity not in ("low", "medium", "high", "critical"):
        severity = "medium"

    record = FailureRecord(
        company_id=company_id,
        category=category,
        description=description,
        severity=severity,
        source=source,
        details=details or {},
    )

    _init_failure_schema(db_path)

    conn = sqlite3.connect(str(db_path))
    try:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO failure_records
            (company_id, category, description, severity, source, details, timestamp, resolved)
            VALUES (?, ?, ?, ?, ?, ?, ?, 0)
        """, (
            record.company_id,
            record.category.value,
            record.description,
            record.severity,
            record.source,
            json.dumps(record.details),
            record.timestamp,
        ))
        conn.commit()
        failure_id = cursor.lastrowid
        logger.warning(f"Logged failure [{category.value}] for {company_id}: {description}")
        return failure_id
    finally:
        conn.close()


def resolve_failure(
    failure_id: int,
    resolution_notes: str,
    db_path: Path = DEFAULT_DB_PATH,
):
    """Mark a failure as resolved."""
    _init_failure_schema(db_path)

    conn = sqlite3.connect(str(db_path))
    try:
        cursor = conn.cursor()
        cursor.execute("""
            UPDATE failure_records
            SET resolved = 1, resolution_notes = ?
            WHERE id = ?
        """, (resolution_notes, failure_id))
        conn.commit()
        logger.info(f"Resolved failure {failure_id}")
    finally:
        conn.close()


def get_failures(
    company_id: Optional[str] = None,
    category: Optional[FailureCategory] = None,
    severity: Optional[str] = None,
    unresolved_only: bool = False,
    days: int = 30,
    limit: int = 100,
    db_path: Path = DEFAULT_DB_PATH,
) -> list[FailureRecord]:
    """
    Get failure records with optional filters.

    Args:
        company_id: Filter by company
        category: Filter by failure category
        severity: Filter by severity level
        unresolved_only: Only return unresolved failures
        days: Look back period
        limit: Maximum records to return

    Returns:
        List of FailureRecord objects
    """
    _init_failure_schema(db_path)

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    try:
        cursor = conn.cursor()
        cutoff = (datetime.utcnow() - timedelta(days=days)).isoformat()

        query = "SELECT * FROM failure_records WHERE timestamp >= ?"
        params = [cutoff]

        if company_id:
            query += " AND company_id = ?"
            params.append(company_id)
        if category:
            query += " AND category = ?"
            params.append(category.value)
        if severity:
            query += " AND severity = ?"
            params.append(severity)
        if unresolved_only:
            query += " AND resolved = 0"

        query += " ORDER BY timestamp DESC LIMIT ?"
        params.append(limit)

        cursor.execute(query, params)

        records = []
        for row in cursor.fetchall():
            records.append(FailureRecord(
                company_id=row["company_id"],
                category=FailureCategory(row["category"]),
                description=row["description"],
                severity=row["severity"],
                source=row["source"],
                details=json.loads(row["details"] or "{}"),
                timestamp=row["timestamp"],
                resolved=bool(row["resolved"]),
                resolution_notes=row["resolution_notes"],
            ))
        return records
    finally:
        conn.close()


def get_failure_stats(
    days: int = 30,
    db_path: Path = DEFAULT_DB_PATH,
) -> Optional[FailureStats]:
    """
    Get aggregate failure statistics.

    Args:
        days: Look back period

    Returns:
        FailureStats with aggregated data, or None if no failures
    """
    _init_failure_schema(db_path)

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    try:
        cursor = conn.cursor()
        cutoff = (datetime.utcnow() - timedelta(days=days)).isoformat()

        # Total count
        cursor.execute("""
            SELECT COUNT(*) as total FROM failure_records WHERE timestamp >= ?
        """, (cutoff,))
        total = cursor.fetchone()["total"]

        if total == 0:
            return None

        # By category
        cursor.execute("""
            SELECT category, COUNT(*) as count
            FROM failure_records
            WHERE timestamp >= ?
            GROUP BY category
            ORDER BY count DESC
        """, (cutoff,))
        by_category = {row["category"]: row["count"] for row in cursor.fetchall()}

        # By severity
        cursor.execute("""
            SELECT severity, COUNT(*) as count
            FROM failure_records
            WHERE timestamp >= ?
            GROUP BY severity
        """, (cutoff,))
        by_severity = {row["severity"]: row["count"] for row in cursor.fetchall()}

        # By source
        cursor.execute("""
            SELECT source, COUNT(*) as count
            FROM failure_records
            WHERE timestamp >= ? AND source IS NOT NULL
            GROUP BY source
        """, (cutoff,))
        by_source = {row["source"]: row["count"] for row in cursor.fetchall()}

        # Most affected companies
        cursor.execute("""
            SELECT company_id, COUNT(*) as count
            FROM failure_records
            WHERE timestamp >= ?
            GROUP BY company_id
            ORDER BY count DESC
            LIMIT 10
        """, (cutoff,))
        most_affected = [(row["company_id"], row["count"]) for row in cursor.fetchall()]

        # Resolution rate
        cursor.execute("""
            SELECT
                SUM(CASE WHEN resolved = 1 THEN 1 ELSE 0 END) as resolved,
                COUNT(*) as total
            FROM failure_records
            WHERE timestamp >= ?
        """, (cutoff,))
        row = cursor.fetchone()
        resolution_rate = row["resolved"] / row["total"] if row["total"] > 0 else 0.0

        return FailureStats(
            total_failures=total,
            failures_by_category=by_category,
            failures_by_severity=by_severity,
            failures_by_source=by_source,
            most_affected_companies=most_affected,
            resolution_rate=resolution_rate,
            period_days=days,
        )
    finally:
        conn.close()


def get_failure_examples(
    category: FailureCategory,
    limit: int = 5,
    db_path: Path = DEFAULT_DB_PATH,
) -> list[FailureRecord]:
    """
    Get representative examples for a failure category.

    Useful for documentation and debugging.
    """
    return get_failures(
        category=category,
        limit=limit,
        db_path=db_path,
    )


def identify_failure_patterns(
    days: int = 30,
    db_path: Path = DEFAULT_DB_PATH,
) -> list[FailurePattern]:
    """
    Identify patterns in failures to guide improvements.

    Returns:
        List of FailurePattern objects with suggestions
    """
    stats = get_failure_stats(days=days, db_path=db_path)
    if not stats:
        return []

    patterns = []
    for category_str, count in stats.failures_by_category.items():
        if count < 2:  # Need at least 2 failures to be a pattern
            continue

        category = FailureCategory(category_str)
        examples = get_failure_examples(category, limit=3, db_path=db_path)

        # Extract common characteristics
        characteristics = []
        sources = set()
        severities = set()
        for ex in examples:
            if ex.source:
                sources.add(ex.source)
            severities.add(ex.severity)

        if sources:
            characteristics.append(f"Sources: {', '.join(sources)}")
        if len(severities) == 1:
            characteristics.append(f"Consistent severity: {list(severities)[0]}")

        # Generate suggested fix based on category
        suggested_fix = _get_suggested_fix(category)

        patterns.append(FailurePattern(
            category=category,
            frequency=count,
            example_companies=[ex.company_id for ex in examples],
            common_characteristics=characteristics,
            suggested_fix=suggested_fix,
        ))

    # Sort by frequency
    patterns.sort(key=lambda p: p.frequency, reverse=True)
    return patterns


def _get_suggested_fix(category: FailureCategory) -> str:
    """Get suggested fix for a failure category."""
    fixes = {
        FailureCategory.NAMING_AMBIGUITY: "Add company domain verification step before data retrieval",
        FailureCategory.DOMAIN_MAPPING: "Cross-reference domain with Harmonic company ID",
        FailureCategory.MISSING_HARMONIC: "Add fallback to alternative data sources (Pitchbook, Crunchbase)",
        FailureCategory.TANGENTIAL_CONTENT: "Tighten content relevance filtering in retrieval pipeline",
        FailureCategory.API_ERROR: "Add retry logic with exponential backoff",
        FailureCategory.DATA_QUALITY: "Implement data validation and freshness checks",
        FailureCategory.LLM_HALLUCINATION: "Add fact-checking step against source data",
        FailureCategory.ENTITY_NOT_FOUND: "Expand search to include LinkedIn company pages",
        FailureCategory.TIMEOUT: "Increase timeout limits or add async processing",
        FailureCategory.RATE_LIMIT: "Implement request queuing and rate limiting",
        FailureCategory.OTHER: "Review and categorize for specific improvements",
    }
    return fixes.get(category, "Review failure details for improvement opportunities")


# =============================================================================
# FAILURE SUMMARY REPORT
# =============================================================================

def generate_failure_report(
    days: int = 30,
    db_path: Path = DEFAULT_DB_PATH,
) -> str:
    """
    Generate a human-readable failure analysis report.

    Returns:
        Markdown-formatted report
    """
    stats = get_failure_stats(days=days, db_path=db_path)
    if not stats:
        return f"No failures recorded in the last {days} days."

    patterns = identify_failure_patterns(days=days, db_path=db_path)

    lines = [
        f"# Failure Analysis Report",
        f"*Period: Last {days} days*",
        "",
        f"## Summary",
        f"- **Total Failures:** {stats.total_failures}",
        f"- **Resolution Rate:** {stats.resolution_rate:.1%}",
        "",
        "## By Category",
    ]

    for cat, count in sorted(stats.failures_by_category.items(), key=lambda x: -x[1]):
        desc = CATEGORY_DESCRIPTIONS.get(FailureCategory(cat), "")
        lines.append(f"- **{cat}:** {count} ({desc})")

    lines.extend([
        "",
        "## By Severity",
    ])
    for sev, count in stats.failures_by_severity.items():
        lines.append(f"- {sev}: {count}")

    lines.extend([
        "",
        "## Most Affected Companies",
    ])
    for company, count in stats.most_affected_companies[:5]:
        lines.append(f"- {company}: {count} failures")

    if patterns:
        lines.extend([
            "",
            "## Identified Patterns & Suggested Fixes",
        ])
        for p in patterns[:5]:
            lines.append(f"\n### {p.category.value} ({p.frequency} occurrences)")
            lines.append(f"**Examples:** {', '.join(p.example_companies)}")
            if p.common_characteristics:
                lines.append(f"**Characteristics:** {'; '.join(p.common_characteristics)}")
            lines.append(f"**Suggested Fix:** {p.suggested_fix}")

    return "\n".join(lines)

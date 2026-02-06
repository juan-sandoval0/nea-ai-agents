"""Relevance scoring algorithm for company signals."""

import json
from typing import Dict, Any


# Scoring weights
COMPANY_TYPE_SCORES = {
    "portfolio": 50,
    "competitor": 30
}

SIGNAL_IMPORTANCE_SCORES = {
    "funding": 40,
    "acquisition": 40,
    "team_change_c_suite": 35,
    "team_change_vp": 25,
    "team_change": 20,
    "product_launch": 20,
    "partnership": 15,
    "news_coverage": 10
}

C_SUITE_TITLES = ["ceo", "cto", "cfo", "coo", "cmo", "cpo", "chief"]
VP_TITLES = ["vp", "vice president", "svp", "evp"]


def detect_seniority(title: str) -> str:
    """Detect seniority level from job title."""
    if not title:
        return "other"
    title_lower = title.lower()
    if any(t in title_lower for t in C_SUITE_TITLES):
        return "c_suite"
    if any(t in title_lower for t in VP_TITLES):
        return "vp"
    if "director" in title_lower:
        return "director"
    if "manager" in title_lower:
        return "manager"
    return "other"


def calculate_signal_importance(signal_type: str, raw_data: Dict[str, Any] = None) -> int:
    """Calculate signal importance score (max 40)."""
    raw_data = raw_data or {}

    if signal_type == "team_change":
        title = raw_data.get("title", "")
        seniority = raw_data.get("seniority") or detect_seniority(title)
        if seniority == "c_suite":
            return SIGNAL_IMPORTANCE_SCORES["team_change_c_suite"]
        elif seniority == "vp":
            return SIGNAL_IMPORTANCE_SCORES["team_change_vp"]
        else:
            return SIGNAL_IMPORTANCE_SCORES["team_change"]

    return SIGNAL_IMPORTANCE_SCORES.get(signal_type, 10)


def calculate_context_bonus(signal_type: str, raw_data: Dict[str, Any] = None) -> int:
    """Calculate context bonus (max 10)."""
    raw_data = raw_data or {}
    bonus = 0

    if signal_type == "funding":
        amount = raw_data.get("amount", 0)
        if amount and amount > 50_000_000:
            bonus += 5

    notable_companies = raw_data.get("notable_companies", [])
    if notable_companies:
        bonus += 5

    return min(bonus, 10)


def score_signal(
    category: str,
    signal_type: str,
    raw_data: Dict[str, Any] = None
) -> tuple[int, Dict[str, Any]]:
    """Calculate total relevance score for a signal."""
    raw_data = raw_data or {}

    company_type_score = COMPANY_TYPE_SCORES.get(category, 30)
    importance_score = calculate_signal_importance(signal_type, raw_data)
    context_bonus = calculate_context_bonus(signal_type, raw_data)

    total = min(company_type_score + importance_score + context_bonus, 100)

    breakdown = {
        "company_type": company_type_score,
        "signal_importance": importance_score,
        "context_bonus": context_bonus,
        "total": total
    }

    return total, breakdown


def format_score_breakdown(breakdown: Dict[str, Any]) -> str:
    """Format score breakdown as JSON string."""
    return json.dumps(breakdown)

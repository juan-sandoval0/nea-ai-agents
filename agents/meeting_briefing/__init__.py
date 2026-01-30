"""Meeting Briefing Agent - Company intelligence and retrieval for VC meeting prep.

This module provides tools for:
- Ingesting company data from Harmonic API into structured database tables
- Generating meeting briefings from database tables
- Managing company profiles, founders, signals, and news

Usage:
    # Ingest company data
    from tools import ingest_company
    ingest_company("stripe.com")

    # Generate briefing
    from agents.meeting_briefing import generate_briefing
    result = generate_briefing("stripe.com")
    print(result["markdown"])

CLI Commands:
    # Ingest company data
    python -m tools.company_tools --company_url stripe.com

    # Generate briefing
    python -m agents.meeting_briefing.briefing_generator --company_url stripe.com
"""

# Re-export from shared modules for convenience
from core.database import (
    Database,
    CompanyCore,
    Founder,
    KeySignal,
    NewsArticle,
    CompanyBundle,
)

from tools.company_tools import (
    get_company_profile,
    get_founders,
    get_recent_news,
    get_key_signals,
    ingest_company,
    get_company_bundle,
)

from agents.meeting_briefing.briefing_generator import generate_briefing

__all__ = [
    # Database models (from core)
    "Database",
    "CompanyCore",
    "Founder",
    "KeySignal",
    "NewsArticle",
    "CompanyBundle",
    # Canonical tools (from tools)
    "get_company_profile",
    "get_founders",
    "get_recent_news",
    "get_key_signals",
    "ingest_company",
    "get_company_bundle",
    # Briefing generator
    "generate_briefing",
]

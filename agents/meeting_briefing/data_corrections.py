"""
Manual Data Corrections
=======================

Manual corrections for company data quality issues.
This module provides overrides for known data quality problems
in upstream data sources (Harmonic, etc.)

Usage:
    from agents.meeting_briefing.data_corrections import get_corrected_founders

    corrections = get_corrected_founders("example.com")
    if corrections:
        # Use corrections instead of API data
        founders = corrections
"""

from __future__ import annotations
from typing import Optional

# =============================================================================
# FOUNDER CORRECTIONS
# =============================================================================

# Map of domain -> list of founder corrections
# Each correction is a dict with: name, title (optional), linkedin_url (optional)
FOUNDER_CORRECTIONS: dict[str, list[dict]] = {
    # Example format:
    # "example.com": [
    #     {"name": "John Doe", "title": "CEO & Co-Founder", "linkedin_url": "https://linkedin.com/in/johndoe"},
    #     {"name": "Jane Smith", "title": "CTO & Co-Founder"},
    # ],
}


def get_corrected_founders(domain: str) -> Optional[list[dict]]:
    """
    Get manual founder corrections for a company domain.

    Args:
        domain: Company domain (e.g., "stripe.com")

    Returns:
        List of founder dicts if corrections exist, None otherwise.
        Each dict has keys: name, title (optional), linkedin_url (optional)
    """
    # Normalize domain
    domain = domain.lower().strip()
    if domain.startswith("www."):
        domain = domain[4:]

    return FOUNDER_CORRECTIONS.get(domain)

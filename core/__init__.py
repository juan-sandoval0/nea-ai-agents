"""Core shared components for NEA AI Agents.

This module provides shared infrastructure used by multiple agents:
- Database: SQLite database with company data models
- Clients: External API clients (Harmonic, etc.)
- Tracking: Engagement tracking (usage, API calls, feedback)
"""

from core.database import (
    Database,
    CompanyCore,
    Founder,
    NewsArticle,
    KeySignal,
    CompanyBundle,
    DEFAULT_DB_PATH,
)

from core.tracking import (
    Tracker,
    get_tracker,
    UsageEvent,
    APICall,
)

__all__ = [
    # Database
    "Database",
    "CompanyCore",
    "Founder",
    "NewsArticle",
    "KeySignal",
    "CompanyBundle",
    "DEFAULT_DB_PATH",
    # Tracking
    "Tracker",
    "get_tracker",
    "UsageEvent",
    "APICall",
]

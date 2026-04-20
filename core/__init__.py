"""Core shared components for NEA AI Agents.

This module provides shared infrastructure used by multiple agents:
- Data models: CompanyCore, Founder, NewsArticle, KeySignal, CompanyBundle
- Supabase sync/read functions for persistence
- Clients: External API clients (Harmonic, etc.)
- Tracking: Engagement tracking (usage, API calls, feedback)
"""

from core.database import (
    CompanyCore,
    Founder,
    NewsArticle,
    KeySignal,
    CompanyBundle,
    CompetitorSnapshot,
    get_company_bundle_from_supabase,
    sync_company_to_supabase,
    sync_founders_to_supabase,
    sync_news_to_supabase,
    sync_signals_to_supabase,
    sync_competitors_to_supabase,
    read_company_from_supabase,
    read_founders_from_supabase,
    read_news_from_supabase,
    read_signals_from_supabase,
    read_competitors_from_supabase,
)

from core.tracking import (
    Tracker,
    get_tracker,
    UsageEvent,
    APICall,
)

__all__ = [
    # Data Models
    "CompanyCore",
    "Founder",
    "NewsArticle",
    "KeySignal",
    "CompanyBundle",
    "CompetitorSnapshot",
    # Supabase functions
    "get_company_bundle_from_supabase",
    "sync_company_to_supabase",
    "sync_founders_to_supabase",
    "sync_news_to_supabase",
    "sync_signals_to_supabase",
    "sync_competitors_to_supabase",
    "read_company_from_supabase",
    "read_founders_from_supabase",
    "read_news_from_supabase",
    "read_signals_from_supabase",
    "read_competitors_from_supabase",
    # Tracking
    "Tracker",
    "get_tracker",
    "UsageEvent",
    "APICall",
]

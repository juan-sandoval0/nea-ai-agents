#!/usr/bin/env python
"""
NewsAPI Integration Demo Script
================================
Run: python demo_newsapi.py

Requires NEWSAPI_API_KEY, HARMONIC_API_KEY, TAVILY_API_KEY in .env
"""

import os
import sys

# Load env vars
from pathlib import Path
from dotenv import load_dotenv
load_dotenv(Path(__file__).parent / ".env")

from core.clients.newsapi import NewsApiClient
from core.database import Database
from tools.company_tools import get_recent_news, get_key_signals, ingest_company

DIVIDER = "=" * 70


def demo_concept_resolution():
    """Show how concept URI disambiguation works."""
    print(f"\n{DIVIDER}")
    print("1. CONCEPT URI RESOLUTION")
    print(f"{DIVIDER}\n")

    client = NewsApiClient()

    test_cases = ["Stripe", "Mercor", "Physical Intelligence"]
    for name in test_cases:
        uri = client._resolve_concept_uri(name)
        status = f"→ {uri}" if uri else "→ None (will use keyword fallback)"
        print(f"  {name:30s} {status}")

    print("\n  Key point: 'Stripe' resolves to the company entity, not 'flag stripe'.")
    print("  Smaller companies fall back to keyword + category/source filters.")


def demo_article_search():
    """Show article search results for different companies."""
    print(f"\n{DIVIDER}")
    print("2. ARTICLE SEARCH QUALITY")
    print(f"{DIVIDER}\n")

    client = NewsApiClient()

    for name in ["Stripe", "Physical Intelligence"]:
        articles = client.search_articles(name, days_back=30)
        print(f"  {name}: {len(articles)} articles (30 days)")
        for a in articles[:5]:
            print(f"    • {a.title[:80]}")
            print(f"      {a.source_name} | {a.published_date or 'no date'}")
        print()


def demo_event_signals():
    """Show event detection and signal classification."""
    print(f"\n{DIVIDER}")
    print("3. EVENT → SIGNAL MAPPING")
    print(f"{DIVIDER}\n")

    client = NewsApiClient()

    events = client.get_events("Stripe", days_back=30)
    print(f"  Stripe: {len(events)} events detected\n")
    for e in events[:10]:
        print(f"    [{e.to_signal_type():15s}] {e.title[:70]}")
        print(f"    {'':17s} date: {e.event_date or 'unknown'}")


def demo_full_pipeline():
    """Show the full ingest_company pipeline with news + signals."""
    print(f"\n{DIVIDER}")
    print("4. FULL PIPELINE: ingest_company('stripe.com')")
    print(f"{DIVIDER}\n")

    # Clear existing data for a clean demo
    db = Database()
    db.clear_company_data("stripe.com")

    result = ingest_company("stripe.com")

    print(f"  Company:  {result['company_name']}")
    print(f"  Profile:  {'✓' if result['company_core'] else '✗'}")
    print(f"  Founders: {result['founders_count']}")
    print(f"  Signals:  {result['signals_count']}")
    print(f"  News:     {result['news_count']}")
    if result["errors"]:
        print(f"  Errors:   {result['errors']}")

    # Show signal breakdown by source
    signals = db.get_signals("stripe.com")
    sources = {}
    for s in signals:
        sources.setdefault(s.source, []).append(s)

    print(f"\n  Signal breakdown:")
    for source, sigs in sorted(sources.items()):
        print(f"    {source}: {len(sigs)} signals")
        for s in sigs[:3]:
            print(f"      [{s.signal_type}] {s.description[:65]}")

    # Show sample news
    news = db.get_news("stripe.com", limit=5)
    print(f"\n  Sample news articles ({len(news)} shown of {result['news_count']}):")
    for n in news:
        print(f"    • {n.article_headline[:70]}")
        print(f"      {n.outlet} | {n.published_date or 'no date'}")


def demo_deduplication():
    """Show that re-ingestion doesn't create duplicates."""
    print(f"\n{DIVIDER}")
    print("5. DEDUPLICATION")
    print(f"{DIVIDER}\n")

    db = Database()

    # Count before
    news_before = db.get_news("stripe.com", limit=1000)
    count_before = len(news_before)

    # Re-ingest
    articles = get_recent_news("stripe.com", days=30)

    # Count after
    news_after = db.get_news("stripe.com", limit=1000)
    count_after = len(news_after)

    print(f"  Before re-ingest: {count_before} articles")
    print(f"  After re-ingest:  {count_after} articles")
    print(f"  Duplicates added: {count_after - count_before}")
    print(f"  INSERT OR IGNORE working: {'✓' if count_after == count_before else '✗'}")


if __name__ == "__main__":
    print(f"\n{'#' * 70}")
    print("#  NewsAPI (EventRegistry) Integration Demo")
    print(f"{'#' * 70}")

    demo_concept_resolution()
    demo_article_search()
    demo_event_signals()
    demo_full_pipeline()
    demo_deduplication()

    print(f"\n{DIVIDER}")
    print("DEMO COMPLETE")
    print(f"{DIVIDER}\n")

"""
Shared Company Tools
====================

Tools for fetching, storing, and retrieving company data.
Used by multiple agents for company intelligence.

Implemented Sources:
- Harmonic: Company profiles, founders, signals

NOT YET Implemented Sources:
- Tavily: Website updates
- Swarm: Founder background enrichment
- News API: Media/news ingestion

Usage:
    from tools.company_tools import (
        get_company_profile,
        get_founders,
        get_recent_news,
        get_key_signals,
        ingest_company,
        get_company_bundle,
    )

    # Ingest all data for a company
    result = ingest_company("stripe.com")

    # Get complete bundle for briefing
    bundle = get_company_bundle("stripe.com")
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Optional

from core.database import (
    Database,
    CompanyCore,
    Founder,
    NewsArticle,
    KeySignal,
    CompanyBundle,
)
from core.clients.harmonic import HarmonicClient, HarmonicCompany, HarmonicAPIError
from core.clients.tavily import TavilyClient, TavilyAPIError
from core.tracking import get_tracker

logger = logging.getLogger(__name__)

# =============================================================================
# CONFIGURATION
# =============================================================================

# Singleton database instance
_db: Optional[Database] = None


def get_db() -> Database:
    """Get or create database instance."""
    global _db
    if _db is None:
        _db = Database()
    return _db


# Singleton Harmonic client
_harmonic_client: Optional[HarmonicClient] = None


def get_harmonic_client() -> HarmonicClient:
    """Get or create Harmonic client instance."""
    global _harmonic_client
    if _harmonic_client is None:
        _harmonic_client = HarmonicClient()
    return _harmonic_client


# Singleton Tavily client
_tavily_client: Optional[TavilyClient] = None


def get_tavily_client() -> Optional[TavilyClient]:
    """Get or create Tavily client instance. Returns None if API key not set."""
    global _tavily_client
    if _tavily_client is None:
        try:
            _tavily_client = TavilyClient()
        except ValueError:
            logger.info("TAVILY_API_KEY not set - website intelligence disabled")
            return None
    return _tavily_client


# =============================================================================
# URL PARSING UTILITIES
# =============================================================================

def parse_company_url(url: str) -> tuple[str, str]:
    """
    Parse company URL to determine type and normalize.

    Args:
        url: Company website URL or LinkedIn URL

    Returns:
        Tuple of (url_type, normalized_url) where url_type is:
        - "company_domain": Company website (e.g., stripe.com)
        - "company_linkedin": Company LinkedIn URL
        - "person_linkedin": Person LinkedIn URL
    """
    from urllib.parse import urlparse

    url = url.strip()
    if not url.startswith(("http://", "https://")):
        url = "https://" + url

    parsed = urlparse(url)
    host = parsed.netloc.lower().replace("www.", "")
    path = parsed.path.rstrip("/")

    if "linkedin.com" in host:
        if "/company/" in path:
            return ("company_linkedin", url)
        elif "/in/" in path:
            return ("person_linkedin", url)
        else:
            return ("company_linkedin", url)
    else:
        domain = host
        return ("company_domain", domain)


def normalize_company_id(url: str) -> str:
    """
    Normalize URL to a consistent company_id.

    Args:
        url: Any form of company URL

    Returns:
        Normalized company_id (domain without protocol)
    """
    url_type, normalized = parse_company_url(url)
    if url_type == "company_domain":
        return normalized
    return normalized


# =============================================================================
# TOOL 1: get_company_profile
# =============================================================================

def get_company_profile(company_id: str) -> CompanyCore:
    """
    Fetch company snapshot data from Harmonic and write to company_core table.

    STATUS: IMPLEMENTED (Harmonic)

    Args:
        company_id: Company URL or domain

    Returns:
        CompanyCore object with populated fields

    Raises:
        ValueError: If company not found
    """
    client = get_harmonic_client()
    db = get_db()

    url_type, normalized = parse_company_url(company_id)
    normalized_id = normalize_company_id(company_id)

    company: Optional[HarmonicCompany] = None

    try:
        if url_type == "company_domain":
            company = client.lookup_company(domain=normalized)
        elif url_type == "company_linkedin":
            company = client.lookup_company(linkedin_url=normalized)
        elif url_type == "person_linkedin":
            person = client.lookup_person(normalized)
            if person and person.raw_data:
                experience = person.raw_data.get("experience", []) or []
                for exp in experience:
                    if exp.get("is_current_position"):
                        company_urn = exp.get("company_urn")
                        if company_urn and "company:" in company_urn:
                            company_id_from_urn = company_urn.split("company:")[-1]
                            company = client.get_company(company_id_from_urn)
                            break
    except HarmonicAPIError as e:
        logger.error(f"Harmonic API error for {company_id}: {e}")
        raise ValueError(f"Failed to fetch company from Harmonic: {e}")

    if not company:
        raise ValueError(f"Company not found in Harmonic for: {company_id}")

    # Build source map
    source_map = {
        "company_name": "harmonic",
        "founding_date": "harmonic",
        "hq": "harmonic",
        "employee_count": "harmonic",
        "total_funding": "harmonic",
        "products": "harmonic",
        "customers": "harmonic",
        "last_round_date": "harmonic",
        "last_round_funding": "harmonic",
        "web_traffic_trend": "pending_key_signals",
        "hiring_firing": "pending_key_signals",
        "website_update": "pending_tavily",
        "arr_apr": "not_available",
    }

    # Build HQ from location components
    hq = None
    hq_parts = []
    if company.city:
        hq_parts.append(company.city)
    if company.state:
        hq_parts.append(company.state)
    if company.country and company.country not in ("United States", "US", "USA"):
        hq_parts.append(company.country)
    if hq_parts:
        hq = ", ".join(hq_parts)

    # Format web traffic
    web_traffic_trend = None
    if company.web_traffic_change_30d is not None:
        sign = "+" if company.web_traffic_change_30d > 0 else ""
        web_traffic_trend = f"{sign}{company.web_traffic_change_30d:.1f}% (30d)"

    # Format headcount change
    hiring_firing = None
    if company.headcount_change_90d is not None:
        sign = "+" if company.headcount_change_90d > 0 else ""
        hiring_firing = f"{sign}{company.headcount_change_90d:.1f}% (90d)"

    # Use description for products
    products = company.description
    customers = company.customer_type

    # Preserve existing website_update from DB (populated by Tavily during signal ingestion)
    existing_website_update = None
    try:
        existing = db.get_company(normalized_id)
        if existing and existing.website_update:
            existing_website_update = existing.website_update
    except Exception:
        pass

    # Create CompanyCore object
    company_core = CompanyCore(
        company_id=normalized_id,
        company_name=company.name,
        founding_date=company.founded_date,
        hq=hq,
        employee_count=company.headcount,
        total_funding=company.funding_total,
        products=products,
        customers=customers,
        arr_apr=None,
        last_round_date=company.funding_last_date,
        last_round_funding=company.funding_last_amount,
        web_traffic_trend=web_traffic_trend,
        website_update=existing_website_update,
        hiring_firing=hiring_firing,
        observed_at=datetime.utcnow().isoformat(),
        source_map=source_map,
    )

    db.upsert_company(company_core)
    logger.info(f"Fetched and stored company profile: {company.name} ({normalized_id})")
    return company_core


# =============================================================================
# TOOL 2: get_founders
# =============================================================================

def get_founders(company_id: str) -> list[Founder]:
    """
    Fetch founders from Harmonic and write to founders table.

    STATUS: IMPLEMENTED (Harmonic) - background pending Swarm

    Args:
        company_id: Company URL or domain

    Returns:
        List of Founder objects

    Raises:
        ValueError: If company not found
    """
    client = get_harmonic_client()
    db = get_db()

    normalized_id = normalize_company_id(company_id)

    url_type, normalized = parse_company_url(company_id)
    company: Optional[HarmonicCompany] = None

    try:
        if url_type == "company_domain":
            company = client.lookup_company(domain=normalized)
        elif url_type == "company_linkedin":
            company = client.lookup_company(linkedin_url=normalized)
        elif url_type == "person_linkedin":
            person = client.lookup_person(normalized)
            if person and person.raw_data:
                experience = person.raw_data.get("experience", []) or []
                for exp in experience:
                    if exp.get("is_current_position"):
                        company_urn = exp.get("company_urn")
                        if company_urn and "company:" in company_urn:
                            company_id_from_urn = company_urn.split("company:")[-1]
                            company = client.get_company(company_id_from_urn)
                            break
    except HarmonicAPIError as e:
        logger.error(f"Harmonic API error for {company_id}: {e}")
        raise ValueError(f"Failed to fetch company from Harmonic: {e}")

    if not company:
        raise ValueError(f"Company not found in Harmonic for: {company_id}")

    founders_list: list[Founder] = []
    seen_names: set[str] = set()

    # Check for manual corrections first (local import to avoid circular dependency)
    from agents.meeting_briefing.data_corrections import get_corrected_founders
    if company.domain:
        corrected = get_corrected_founders(company.domain)
        if corrected:
            # Clear existing founders before inserting corrections
            db.delete_founders(normalized_id)
            for f in corrected:
                founder = Founder(
                    company_id=normalized_id,
                    name=f["name"],
                    role_title=f.get("title"),
                    linkedin_url=f.get("linkedin_url"),
                    background=None,
                    observed_at=datetime.utcnow().isoformat(),
                    source="manual_correction",
                )
                founders_list.append(founder)
            db.upsert_founders(founders_list)
            logger.info(f"Using manual corrections for {normalized_id}: {len(founders_list)} founders")
            return founders_list

    # Get founders from company's 'people' array
    people_array = company.raw_data.get("people", [])

    founder_urns = []
    executive_urns = []

    for p in people_array:
        role_type = p.get("role_type")
        person_urn = p.get("person", "")
        title = p.get("title", "")

        if role_type == "FOUNDER" and person_urn:
            founder_urns.append((person_urn, title))
        elif role_type == "EXECUTIVE" and person_urn:
            # Check if this is a founding-level executive
            title_lower = title.lower()
            is_founder_title = any(t in title_lower for t in ["co-founder", "cofounder", "founder"])
            is_top_exec = title_lower in ["ceo", "president"]  # Exact match only
            if is_founder_title or is_top_exec:
                executive_urns.append((person_urn, title))

    # Use founders if available, otherwise fall back to key executives
    urns_to_fetch = founder_urns if founder_urns else executive_urns

    # Fetch details for each person
    for person_urn, title in urns_to_fetch:
        if "person:" in person_urn:
            person_id = person_urn.split("person:")[-1]
            try:
                person = client.get_person(person_id)
                if person and person.name not in seen_names:
                    founder = Founder(
                        company_id=normalized_id,
                        name=person.name,
                        role_title=title or person.title,
                        linkedin_url=person.linkedin_url,
                        background=None,
                        observed_at=datetime.utcnow().isoformat(),
                        source="harmonic",
                    )
                    founders_list.append(founder)
                    seen_names.add(person.name)
            except HarmonicAPIError as e:
                logger.warning(f"Could not fetch person {person_id}: {e}")

    if founders_list:
        db.upsert_founders(founders_list)
        logger.info(f"Fetched and stored {len(founders_list)} founders for {normalized_id}")
    else:
        logger.warning(f"No founders found for {normalized_id}")

    return founders_list


# =============================================================================
# TOOL 3: get_recent_news
# =============================================================================

def get_recent_news(company_id: str, days: int = 30) -> list[NewsArticle]:
    """
    Fetch recent news articles for a company.

    STATUS: NOT IMPLEMENTED (News API pending)

    Args:
        company_id: Company URL or domain
        days: Number of days to look back (unused)

    Returns:
        Empty list (source not yet implemented)
    """
    normalized_id = normalize_company_id(company_id)
    logger.info(f"get_recent_news called for {normalized_id} - News API not yet implemented")
    return []


# =============================================================================
# TOOL 4: get_key_signals
# =============================================================================

def get_key_signals(company_id: str) -> list[KeySignal]:
    """
    Aggregate event-like signals and write to key_signals table.

    STATUS: PARTIALLY IMPLEMENTED
    - web_traffic_trend: Harmonic (IMPLEMENTED)
    - hiring_firing: Harmonic (IMPLEMENTED)
    - website_update: Tavily (NOT IMPLEMENTED)

    Args:
        company_id: Company URL or domain

    Returns:
        List of KeySignal objects from implemented sources
    """
    client = get_harmonic_client()
    db = get_db()

    normalized_id = normalize_company_id(company_id)

    url_type, normalized = parse_company_url(company_id)
    company: Optional[HarmonicCompany] = None

    try:
        if url_type == "company_domain":
            company = client.lookup_company(domain=normalized)
        elif url_type == "company_linkedin":
            company = client.lookup_company(linkedin_url=normalized)
        elif url_type == "person_linkedin":
            person = client.lookup_person(normalized)
            if person and person.raw_data:
                experience = person.raw_data.get("experience", []) or []
                for exp in experience:
                    if exp.get("is_current_position"):
                        company_urn = exp.get("company_urn")
                        if company_urn and "company:" in company_urn:
                            company_id_from_urn = company_urn.split("company:")[-1]
                            company = client.get_company(company_id_from_urn)
                            break
    except HarmonicAPIError as e:
        logger.error(f"Harmonic API error for {company_id}: {e}")
        raise ValueError(f"Failed to fetch company from Harmonic: {e}")

    if not company:
        raise ValueError(f"Company not found in Harmonic for: {company_id}")

    signals: list[KeySignal] = []
    now = datetime.utcnow().isoformat()

    # Signal: Web Traffic Trend
    if company.web_traffic_change_30d is not None:
        trend = company.web_traffic_change_30d
        if trend > 20:
            description = f"Strong traffic growth: +{trend:.1f}% in 30 days"
        elif trend > 0:
            description = f"Traffic growing: +{trend:.1f}% in 30 days"
        elif trend > -20:
            description = f"Traffic declining: {trend:.1f}% in 30 days"
        else:
            description = f"Significant traffic decline: {trend:.1f}% in 30 days"

        signals.append(KeySignal(
            company_id=normalized_id,
            signal_type="web_traffic",
            description=description,
            observed_at=now,
            source="harmonic",
        ))

    # Signal: Hiring/Firing
    if company.headcount_change_90d is not None:
        change = company.headcount_change_90d
        if change > 10:
            description = f"Rapid hiring: +{change:.1f}% headcount in 90 days ({company.headcount:,} employees)"
        elif change > 0:
            description = f"Growing team: +{change:.1f}% headcount in 90 days ({company.headcount:,} employees)"
        elif change > -10:
            description = f"Team contraction: {change:.1f}% headcount in 90 days ({company.headcount:,} employees)"
        else:
            description = f"Significant layoffs: {change:.1f}% headcount in 90 days ({company.headcount:,} employees)"

        signals.append(KeySignal(
            company_id=normalized_id,
            signal_type="hiring",
            description=description,
            observed_at=now,
            source="harmonic",
        ))

    # Signal: Funding
    if company.funding_last_date and company.funding_last_amount:
        description = f"Last funding: ${company.funding_last_amount:,.0f} on {company.funding_last_date}"
        if company.funding_stage:
            description += f" ({company.funding_stage})"

        signals.append(KeySignal(
            company_id=normalized_id,
            signal_type="funding",
            description=description,
            observed_at=now,
            source="harmonic",
        ))

    # Signal: Website Intelligence (Tavily)
    tavily = get_tavily_client()
    if tavily is not None:
        try:
            domain = normalized_id  # normalized_id is already a domain
            intel = tavily.analyze_company_website(domain)

            # Map Tavily signal types to our signal_type naming
            type_map = {
                "product_update": "website_product",
                "pricing_change": "website_pricing",
                "team_change": "website_team",
                "partnership": "website_news",
                "funding_news": "website_news",
                "general_update": "website_update",
            }

            for sig in intel.signals:
                signal_type = type_map.get(sig["type"], "website_update")
                desc = sig["description"]
                if sig.get("url"):
                    desc += f" (source: {sig['url']})"
                signals.append(KeySignal(
                    company_id=normalized_id,
                    signal_type=signal_type,
                    description=desc,
                    observed_at=now,
                    source="tavily",
                ))

            # Update website_update field on CompanyCore
            if intel.signals:
                type_labels = list({sig["type"].replace("_", " ") for sig in intel.signals})
                summary = f"{len(intel.signals)} website changes detected (30d): {', '.join(type_labels[:3])}"
                conn = db._get_connection()
                try:
                    conn.execute(
                        "UPDATE company_core SET website_update = ? WHERE company_id = ?",
                        (summary, normalized_id),
                    )
                    conn.commit()
                finally:
                    conn.close()
                logger.info(f"Tavily: {len(intel.signals)} signals for {normalized_id}")
            elif intel.answer_summary:
                conn = db._get_connection()
                try:
                    conn.execute(
                        "UPDATE company_core SET website_update = ? WHERE company_id = ?",
                        (intel.answer_summary[:200], normalized_id),
                    )
                    conn.commit()
                finally:
                    conn.close()
        except TavilyAPIError as e:
            logger.warning(f"Tavily analysis failed for {normalized_id}: {e}")
            signals.append(KeySignal(
                company_id=normalized_id,
                signal_type="website_update",
                description="Website intelligence temporarily unavailable",
                observed_at=now,
                source="tavily",
            ))
    else:
        signals.append(KeySignal(
            company_id=normalized_id,
            signal_type="website_update",
            description="Website change detection not yet available (TAVILY_API_KEY not set)",
            observed_at=now,
            source="pending_tavily",
        ))

    if signals:
        db.upsert_signals(signals)
        logger.info(f"Fetched and stored {len(signals)} signals for {normalized_id}")

    return signals


# =============================================================================
# TOOL 5: ingest_company
# =============================================================================

def ingest_company(company_id: str, user: Optional[str] = None) -> dict:
    """
    Single entrypoint for company data ingestion.

    Orchestrates all data fetching and database writes.
    NO LLM calls - pure data ingestion.

    Args:
        company_id: Company URL or domain
        user: Optional user identifier for tracking

    Returns:
        Dict with ingestion results
    """
    normalized_id = normalize_company_id(company_id)
    tracker = get_tracker()

    results = {
        "company_id": normalized_id,
        "company_name": None,
        "company_core": False,
        "founders_count": 0,
        "signals_count": 0,
        "news_count": 0,
        "errors": [],
    }

    # 1. Fetch company profile
    try:
        company_core = get_company_profile(company_id)
        results["company_name"] = company_core.company_name
        results["company_core"] = True
    except Exception as e:
        results["errors"].append(f"Company profile: {str(e)}")
        logger.error(f"Failed to ingest company profile for {company_id}: {e}")
        return results

    # 2. Fetch founders
    try:
        founders = get_founders(company_id)
        results["founders_count"] = len(founders)
    except Exception as e:
        results["errors"].append(f"Founders: {str(e)}")
        logger.error(f"Failed to ingest founders for {company_id}: {e}")

    # 3. Fetch key signals
    try:
        signals = get_key_signals(company_id)
        results["signals_count"] = len(signals)
    except Exception as e:
        results["errors"].append(f"Signals: {str(e)}")
        logger.error(f"Failed to ingest signals for {company_id}: {e}")

    # 4. Fetch recent news (NOT IMPLEMENTED)
    try:
        news = get_recent_news(company_id)
        results["news_count"] = len(news)
    except Exception as e:
        results["errors"].append(f"News: {str(e)}")
        logger.error(f"Failed to ingest news for {company_id}: {e}")

    logger.info(
        f"Ingestion complete for {results['company_name']}: "
        f"founders={results['founders_count']}, "
        f"signals={results['signals_count']}, "
        f"news={results['news_count']}"
    )

    # Track usage
    tracker.log_usage(
        company_id=normalized_id,
        action="ingest",
        user=user,
        metadata={
            "founders_count": results["founders_count"],
            "signals_count": results["signals_count"],
            "errors": results["errors"],
        }
    )

    return results


# =============================================================================
# TOOL 6: get_company_bundle
# =============================================================================

def get_company_bundle(company_id: str) -> CompanyBundle:
    """
    Read-only database accessor for briefing generation.

    Returns all stored data for a company. Does NOT fetch from APIs.

    Args:
        company_id: Company URL or domain

    Returns:
        CompanyBundle with all available data from database
    """
    db = get_db()
    normalized_id = normalize_company_id(company_id)
    return db.get_company_bundle(normalized_id)

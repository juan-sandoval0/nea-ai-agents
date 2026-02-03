"""
Shared Company Tools
====================

Tools for fetching, storing, and retrieving company data.
Used by multiple agents for company intelligence.

Implemented Sources:
- Harmonic: Company profiles, founders, signals
- Swarm: Founder background enrichment
- Tavily: Website intelligence/updates
- NewsAPI (EventRegistry): News articles, event signals

Usage:
    from tools.company_tools import (
        get_company_profile,
        get_founders,
        get_recent_news,
        get_key_signals,
        enrich_founder_backgrounds,
        ingest_company,
        get_company_bundle,
    )

    # Ingest all data for a company
    result = ingest_company("stripe.com")

    # Enrich founder backgrounds with Swarm data
    enriched = enrich_founder_backgrounds("stripe.com")

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
from core.clients.swarm import SwarmClient, SwarmAPIError
from core.clients.newsapi import NewsApiClient, NewsApiError
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


# Singleton Swarm client
_swarm_client: Optional[SwarmClient] = None


def get_swarm_client() -> Optional[SwarmClient]:
    """Get or create Swarm client instance. Returns None if API key not set."""
    global _swarm_client
    if _swarm_client is None:
        try:
            _swarm_client = SwarmClient()
        except ValueError:
            logger.info("SWARM_API_KEY not set - founder background enrichment disabled")
            return None
    return _swarm_client


# Singleton NewsAPI client
_newsapi_client: Optional[NewsApiClient] = None


def get_newsapi_client() -> Optional[NewsApiClient]:
    """Get or create NewsAPI client instance. Returns None if API key not set."""
    global _newsapi_client
    if _newsapi_client is None:
        try:
            _newsapi_client = NewsApiClient()
        except ValueError:
            logger.info("NEWSAPI_API_KEY not set - news ingestion disabled")
            return None
    return _newsapi_client


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
# HELPER: Summarize founder background with LLM
# =============================================================================

def _summarize_founder_background(
    name: str,
    role_title: str,
    raw_background: str,
    company_name: str,
) -> str:
    """
    Use OpenAI to create a concise founder background summary.

    Args:
        name: Founder name
        role_title: Current role at the company
        raw_background: Raw background text from Swarm
        company_name: Current company name (to exclude from summary)

    Returns:
        Concise 2-4 sentence summary focused on prior experience
    """
    import os
    from langchain_openai import ChatOpenAI
    from langchain_core.messages import SystemMessage, HumanMessage

    # Skip if no OpenAI key
    if not os.getenv("OPENAI_API_KEY"):
        logger.warning("OPENAI_API_KEY not set - skipping LLM summarization")
        return raw_background

    system_prompt = """You are a VC research assistant creating concise founder backgrounds.
Your task is to summarize a founder's background in 2-4 sentences.

Rules:
- Focus on PRIOR experience (not their current role - that's already displayed elsewhere)
- Highlight: previous companies, notable roles, education, achievements
- Skip: current role details, generic skills lists, redundant info
- Be factual and concise
- If they were at notable companies (Google, Meta, OpenAI, etc.), mention it
- If they have a technical background (PhD, engineering), mention it
- If they previously founded or exited a company, mention it"""

    user_prompt = f"""Summarize this founder's background for a VC meeting brief.

Founder: {name}
Current Role: {role_title} at {company_name}

Raw Background Data:
{raw_background}

Write a 2-4 sentence summary focusing on their PRIOR experience and credentials (not their current role at {company_name})."""

    try:
        llm = ChatOpenAI(model="gpt-4o-mini", temperature=0)
        messages = [
            SystemMessage(content=system_prompt),
            HumanMessage(content=user_prompt),
        ]
        response = llm.invoke(messages)
        return response.content.strip()
    except Exception as e:
        logger.warning(f"LLM summarization failed for {name}: {e}")
        return raw_background


# =============================================================================
# TOOL 2b: enrich_founder_backgrounds (Swarm)
# =============================================================================

def enrich_founder_backgrounds(company_id: str, summarize: bool = True) -> dict:
    """
    Enrich founder backgrounds using Swarm API.

    Fetches detailed profile information for each founder using their
    LinkedIn URL and updates the founders table with background text
    and sources.

    STATUS: IMPLEMENTED (Swarm + optional OpenAI summarization)

    Args:
        company_id: Company URL or domain
        summarize: If True, use OpenAI to create concise summaries (default: True)

    Returns:
        Dict with enrichment results:
        {
            "company_id": str,
            "enriched_count": int,
            "skipped_count": int,
            "failed_count": int,
            "founders": [
                {
                    "name": str,
                    "status": "enriched" | "skipped" | "failed",
                    "reason": str (optional),
                    "sources": list[dict] (if enriched),
                }
            ]
        }

    Raises:
        ValueError: If Swarm API key is not set
    """
    swarm = get_swarm_client()
    if swarm is None:
        raise ValueError("SWARM_API_KEY not set - founder background enrichment unavailable")

    db = get_db()
    normalized_id = normalize_company_id(company_id)

    # Get existing founders from database
    founders = db.get_founders(normalized_id)

    if not founders:
        logger.info(f"No founders found in database for {normalized_id}")
        return {
            "company_id": normalized_id,
            "enriched_count": 0,
            "skipped_count": 0,
            "failed_count": 0,
            "founders": [],
        }

    results = {
        "company_id": normalized_id,
        "enriched_count": 0,
        "skipped_count": 0,
        "failed_count": 0,
        "founders": [],
    }

    for founder in founders:
        founder_result = {
            "name": founder.name,
            "status": "pending",
        }

        # Skip if already enriched (has meaningful background)
        if founder.background and len(founder.background) > 50:
            founder_result["status"] = "skipped"
            founder_result["reason"] = "Already has background"
            results["skipped_count"] += 1
            results["founders"].append(founder_result)
            continue

        # Try to enrich via LinkedIn URL
        profile = None

        if founder.linkedin_url:
            try:
                profile = swarm.get_profile_by_linkedin(founder.linkedin_url)
            except SwarmAPIError as e:
                logger.warning(f"Swarm API error for {founder.name}: {e}")

        # Fallback: search by name and company
        if not profile:
            try:
                # Get company name from database
                company = db.get_company(normalized_id)
                company_name = company.company_name if company else None
                profile = swarm.search_by_name_and_company(founder.name, company_name)
            except SwarmAPIError as e:
                logger.warning(f"Swarm name search failed for {founder.name}: {e}")

        if not profile:
            founder_result["status"] = "failed"
            founder_result["reason"] = "Profile not found in Swarm"
            results["failed_count"] += 1
            results["founders"].append(founder_result)
            continue

        # Format background and extract sources
        raw_background = profile.format_background()
        sources = profile.get_sources()

        if not raw_background or len(raw_background) < 20:
            founder_result["status"] = "failed"
            founder_result["reason"] = "No meaningful background data"
            results["failed_count"] += 1
            results["founders"].append(founder_result)
            continue

        # Optionally summarize with LLM
        if summarize:
            company = db.get_company(normalized_id)
            company_name = company.company_name if company else "the company"
            background = _summarize_founder_background(
                name=founder.name,
                role_title=founder.role_title or "",
                raw_background=raw_background,
                company_name=company_name,
            )
        else:
            background = raw_background

        # Format sources as string for storage
        sources_str = ""
        if sources:
            source_urls = [s["url"] for s in sources if s.get("url")]
            if source_urls:
                sources_str = "\n\n---\nSources: " + ", ".join(source_urls[:3])

        # Combine background with sources
        full_background = background + sources_str if background else None

        if not full_background or len(full_background) < 20:
            founder_result["status"] = "failed"
            founder_result["reason"] = "No meaningful background data"
            results["failed_count"] += 1
            results["founders"].append(founder_result)
            continue

        # Update founder in database
        founder.background = full_background
        founder.source = "swarm"
        founder.observed_at = datetime.utcnow().isoformat()

        # Also update LinkedIn URL if we found one
        if profile.linkedin_url and not founder.linkedin_url:
            if not profile.linkedin_url.startswith("http"):
                founder.linkedin_url = "https://" + profile.linkedin_url
            else:
                founder.linkedin_url = profile.linkedin_url

        db.upsert_founders([founder])

        founder_result["status"] = "enriched"
        founder_result["sources"] = sources
        results["enriched_count"] += 1
        results["founders"].append(founder_result)

        logger.info(f"Enriched background for {founder.name} at {normalized_id}")

    logger.info(
        f"Founder enrichment complete for {normalized_id}: "
        f"enriched={results['enriched_count']}, "
        f"skipped={results['skipped_count']}, "
        f"failed={results['failed_count']}"
    )

    return results


# =============================================================================
# TOOL 3: get_recent_news
# =============================================================================

def get_recent_news(company_id: str, days: int = 30) -> list[NewsArticle]:
    """
    Fetch recent news articles for a company via EventRegistry (newsapi.ai).

    STATUS: IMPLEMENTED (NewsAPI)

    Args:
        company_id: Company URL or domain
        days: Number of days to look back

    Returns:
        List of NewsArticle objects
    """
    db = get_db()
    normalized_id = normalize_company_id(company_id)

    newsapi = get_newsapi_client()
    if newsapi is None:
        logger.info(f"get_recent_news: NEWSAPI_API_KEY not set, skipping for {normalized_id}")
        return []

    # Resolve company name for keyword search
    company_name = None
    existing = db.get_company(normalized_id)
    if existing:
        company_name = existing.company_name
    if not company_name:
        # Fall back to domain hint
        company_name = normalized_id.split(".")[0]

    try:
        api_articles = newsapi.search_articles(keyword=company_name, days_back=days)
    except NewsApiError as e:
        logger.error(f"NewsAPI search failed for {normalized_id}: {e}")
        return []

    # Transform to NewsArticle DB models, filtering for relevance
    articles: list[NewsArticle] = []
    for a in api_articles:
        articles.append(NewsArticle(
            company_id=normalized_id,
            article_headline=a.title,
            outlet=a.source_name,
            url=a.url,
            published_date=a.published_date,
            observed_at=datetime.utcnow().isoformat(),
            source="newsapi",
        ))

    if articles:
        db.insert_news(articles)
        logger.info(f"Stored {len(articles)} news articles for {normalized_id}")

    return articles


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

    # Signal: Website Intelligence (Tavily Crawl)
    tavily = get_tavily_client()
    if tavily is not None:
        try:
            # Ensure URL is properly formatted for crawl
            url = normalized_id if normalized_id.startswith(("http://", "https://")) else f"https://{normalized_id}"
            intel = tavily.crawl_company_website(url)

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

    # Signal: News Events (EventRegistry)
    newsapi = get_newsapi_client()
    if newsapi is not None:
        try:
            company_name = company.name
            events = newsapi.get_events(keyword=company_name, days_back=30)
            for event in events:
                signal_type = event.to_signal_type()
                signals.append(KeySignal(
                    company_id=normalized_id,
                    signal_type=signal_type,
                    description=event.title,
                    observed_at=event.event_date or now,
                    source="newsapi",
                ))
            if events:
                logger.info(f"NewsAPI: {len(events)} event signals for {normalized_id}")
        except NewsApiError as e:
            logger.warning(f"NewsAPI event search failed for {normalized_id}: {e}")

    if signals:
        db.upsert_signals(signals)
        logger.info(f"Fetched and stored {len(signals)} signals for {normalized_id}")

    return signals


# =============================================================================
# TOOL 5: ingest_company
# =============================================================================

def ingest_company(
    company_id: str,
    user: Optional[str] = None,
    enrich_backgrounds: bool = False,
) -> dict:
    """
    Single entrypoint for company data ingestion.

    Orchestrates all data fetching and database writes.
    NO LLM calls - pure data ingestion.

    Args:
        company_id: Company URL or domain
        user: Optional user identifier for tracking
        enrich_backgrounds: If True, enrich founder backgrounds using Swarm API

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
        "founders_enriched": 0,
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

    # 2b. Enrich founder backgrounds (optional)
    if enrich_backgrounds and results["founders_count"] > 0:
        try:
            enrichment = enrich_founder_backgrounds(company_id)
            results["founders_enriched"] = enrichment["enriched_count"]
        except Exception as e:
            results["errors"].append(f"Founder backgrounds: {str(e)}")
            logger.error(f"Failed to enrich founder backgrounds for {company_id}: {e}")

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
        f"founders={results['founders_count']} (enriched={results['founders_enriched']}), "
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
            "founders_enriched": results["founders_enriched"],
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

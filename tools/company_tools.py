"""
Shared Company Tools
====================

Tools for fetching, storing, and retrieving company data.
Used by multiple agents for company intelligence.

Implemented Sources:
- Harmonic: Company profiles, founders, signals
- Swarm: Founder background enrichment
- Tavily: Website intelligence/updates
- Parallel Search: News articles, event signals

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
    CompetitorSnapshot,
    sync_founders_to_supabase,
    sync_company_to_supabase,
    sync_news_to_supabase,
    sync_competitors_to_supabase,
    sync_signals_to_supabase,
    read_company_from_supabase,
    read_founders_from_supabase,
    get_company_bundle_from_supabase,
    patch_company_website_update,
)
from core.clients.harmonic import HarmonicClient, HarmonicCompany, HarmonicAPIError
from core.clients.tavily import TavilyClient, TavilyAPIError
from core.clients.swarm import SwarmClient, SwarmAPIError, FounderProfile
from core.clients.parallel_search import (
    ParallelSearchClient,
    ParallelSearchError,
    _classify_signal_type,
)
import re
from core.tracking import get_tracker

logger = logging.getLogger(__name__)


# =============================================================================
# EXCERPT CLEANING
# =============================================================================

# Patterns to skip when cleaning excerpts
BOILERPLATE_PATTERNS = [
    r"cookie", r"accept all", r"reject all", r"privacy policy", r"terms of service",
    r"subscribe", r"sign up", r"log in", r"menu", r"navigation", r"toggle",
    r"share this", r"follow us", r"copyright", r"all rights reserved",
    r"skip to content", r"skip to main", r"read more", r"learn more", r"click here",
    r"manage cookies", r"cookie settings", r"we use cookies",
    r"section title:", r"oops, something went wrong", r"go to hub",
    r"futures & commodities", r"prediction markets", r"yahoo finance",
    r"published \w+,", r"updated \w+,",  # Skip date lines like "Published Fri, Feb"
    r"^\[.*\]\(.*\)$",  # Skip markdown links that are the entire line
    r"^>\s*",  # Skip blockquotes
]

def _clean_excerpt(excerpt: str, max_chars: int = 200) -> str:
    """
    Clean an excerpt by removing boilerplate content.

    Args:
        excerpt: Raw excerpt text
        max_chars: Maximum characters to return

    Returns:
        Cleaned excerpt or empty string if all content is boilerplate
    """
    if not excerpt:
        return ""

    # Pre-clean: remove common junk patterns
    excerpt = re.sub(r'\[Skip to [^\]]+\]\([^)]*\)', '', excerpt)  # [Skip to X](url)
    excerpt = re.sub(r'\[[^\]]*\]\(\s*\)', '', excerpt)  # Empty links [text]()
    excerpt = re.sub(r'\[?\s*\]\([^)]+\)', '', excerpt)  # [](url) empty text links
    excerpt = re.sub(r'Section Title:\s*', '', excerpt, flags=re.IGNORECASE)
    excerpt = re.sub(r'>\s*Content:', '', excerpt)
    excerpt = re.sub(r'Published \w+, \w+ \d+.*?(?=\.|$)', '', excerpt)
    excerpt = re.sub(r'Updated \w+, \w+ \d+.*?(?=\.|$)', '', excerpt)

    # Split into sentences/lines
    lines = excerpt.replace("\n", ". ").split(". ")
    clean_lines = []

    for line in lines:
        line = line.strip()
        if not line or len(line) < 20:
            continue

        # Skip lines matching boilerplate patterns
        line_lower = line.lower()
        if any(re.search(pattern, line_lower) for pattern in BOILERPLATE_PATTERNS):
            continue

        # Skip lines that are mostly URLs or markdown links
        if line.count("http") > 1 or line.count("](") > 2:
            continue

        # Skip lines that start with navigation-like content
        if re.match(r'^[\[\(]', line) and '](/' in line:
            continue

        # Clean markdown artifacts
        clean = re.sub(r'\[([^\]]+)\]\([^)]+\)', r'\1', line)  # [text](url) -> text
        clean = re.sub(r'[#*_`>\[\]]', '', clean).strip()

        # Skip if mostly punctuation or very short after cleaning
        if len(clean) < 25:
            continue

        # Skip if it looks like a nav menu (multiple slashes, pipes)
        if clean.count('/') > 2 or clean.count('|') > 1:
            continue

        clean_lines.append(clean)

    if not clean_lines:
        return ""

    # Join and truncate
    result = ". ".join(clean_lines)
    if len(result) > max_chars:
        result = result[:max_chars].rsplit(" ", 1)[0] + "..."

    return result


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


# Singleton Parallel Search client
_parallel_client: Optional[ParallelSearchClient] = None


def get_parallel_client() -> Optional[ParallelSearchClient]:
    """Get or create Parallel Search client instance. Returns None if API key not set."""
    global _parallel_client
    if _parallel_client is None:
        try:
            _parallel_client = ParallelSearchClient()
        except ValueError:
            logger.info("PARALLEL_API_KEY not set - news research disabled")
            return None
    return _parallel_client


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

    # Preserve existing website_update from Supabase (populated by Tavily during signal ingestion)
    existing_website_update = None
    try:
        existing = read_company_from_supabase(normalized_id)
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
        investors=company.investors[:10] if company.investors else [],
        web_traffic_trend=web_traffic_trend,
        website_update=existing_website_update,
        hiring_firing=hiring_firing,
        observed_at=datetime.utcnow().isoformat(),
        source_map=source_map,
    )

    logger.info(f"Fetched company profile: {company.name} ({normalized_id})")
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
        logger.info(f"Fetched {len(founders_list)} founders for {normalized_id}")
    else:
        logger.warning(f"No founders found for {normalized_id}")

    return founders_list


# =============================================================================
# HELPER: Summarize founder background with LLM
# =============================================================================

def _summarize_website_updates(raw_content: str, company_name: str) -> str:
    """
    Use OpenAI to summarize website updates into 1-2 VC-relevant sentences.
    """
    import os
    from langchain_anthropic import ChatAnthropic
    from langchain_core.messages import SystemMessage, HumanMessage

    if not os.getenv("ANTHROPIC_API_KEY"):
        return raw_content[:200]

    system_prompt = """You are a VC research assistant. Summarize website updates into 1-2 sentences.
Focus on what matters to investors: product launches, partnerships, funding, growth signals, market expansion.
Skip technical details, API changes, and developer documentation.
If the content is mostly technical/irrelevant, say "No significant business updates detected."
Be concise and factual."""

    user_prompt = f"""Summarize these recent website updates for {company_name} in 1-2 sentences for a VC investor:

{raw_content}

Summary:"""

    try:
        llm = ChatAnthropic(model="claude-haiku-4-5-20251001", temperature=0)
        messages = [
            SystemMessage(content=system_prompt),
            HumanMessage(content=user_prompt),
        ]
        response = llm.invoke(messages)
        return response.content.strip()
    except Exception as e:
        logger.warning(f"LLM summarization failed for website updates: {e}")
        return raw_content[:200]


def _summarize_news_article(
    headline: str,
    excerpts: str,
    outlet: str,
    company_name: str,
) -> str:
    """
    Use OpenAI to summarize a news article into 1-2 VC-relevant sentences.

    Args:
        headline: Article headline
        excerpts: Article excerpts/content
        outlet: News outlet name
        company_name: Company the article is about

    Returns:
        1-2 sentence VC-relevant summary
    """
    import os
    from langchain_anthropic import ChatAnthropic
    from langchain_core.messages import SystemMessage, HumanMessage

    if not os.getenv("ANTHROPIC_API_KEY"):
        return headline[:200] if headline else excerpts[:200]

    system_prompt = """You are a VC research assistant. Summarize news articles into 1-2 sentences.
Focus on what matters to investors: funding, acquisitions, product launches, partnerships, executive changes, market expansion, competitive moves.
Skip generic company descriptions and boilerplate content.
Be concise and factual. Start with the key news, not the company name."""

    user_prompt = f"""Summarize this news article about {company_name} in 1-2 sentences for a VC investor:

Headline: {headline}
Source: {outlet}

Content:
{excerpts}

Summary:"""

    try:
        llm = ChatAnthropic(model="claude-haiku-4-5-20251001", temperature=0)
        messages = [
            SystemMessage(content=system_prompt),
            HumanMessage(content=user_prompt),
        ]
        response = llm.invoke(messages)
        return response.content.strip()
    except Exception as e:
        logger.warning(f"LLM summarization failed for news article: {e}")
        return headline[:200] if headline else excerpts[:200]


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
    from langchain_anthropic import ChatAnthropic
    from langchain_core.messages import SystemMessage, HumanMessage
    from core.llm_validation import validate_founder_summary, LLMResponseError

    # Skip if no Anthropic key
    if not os.getenv("ANTHROPIC_API_KEY"):
        logger.warning("ANTHROPIC_API_KEY not set - skipping LLM summarization")
        return raw_background

    system_prompt = """You are a VC research assistant creating concise founder backgrounds.
Your task is to summarize a founder's background as 2-3 short bullet points.

Rules:
- Focus on PRIOR experience (not their current role - that's already displayed elsewhere)
- Each bullet = one key fact (notable employer, education, prior exit, etc.)
- Skip: current role details, generic skills lists, redundant info
- Be terse — 5-10 words per bullet
- If they were at notable companies (Google, Meta, OpenAI, etc.), mention it
- If they have a technical background (PhD, engineering), mention it
- If they previously founded or exited a company, mention it
- Output ONLY the bullet points, no intro text"""

    user_prompt = f"""Summarize this founder's background for a VC meeting brief.

Founder: {name}
Current Role: {role_title} at {company_name}

Raw Background Data:
{raw_background}

Write 2-3 bullet points (•) focusing on their PRIOR experience and credentials (not their current role at {company_name}). Each bullet should be 5-10 words."""

    try:
        llm = ChatAnthropic(model="claude-haiku-4-5-20251001", temperature=0)
        messages = [
            SystemMessage(content=system_prompt),
            HumanMessage(content=user_prompt),
        ]
        response = llm.invoke(messages)

        # Validate the LLM output before returning
        # This catches empty, echoed, or error responses
        validated_summary = validate_founder_summary(
            response.content,
            founder_name=name,
            raw_background=raw_background,
        )
        return validated_summary

    except LLMResponseError as e:
        # Validation failed - fall back to raw background
        logger.warning(
            f"LLM summary validation failed for {name} ({e.error_type}): {e}. "
            "Using raw background."
        )
        return raw_background
    except Exception as e:
        logger.warning(f"LLM summarization failed for {name}: {e}")
        return raw_background


# =============================================================================
# TOOL 2b: enrich_founder_backgrounds (Swarm)
# =============================================================================

def enrich_founder_backgrounds(company_id: str, summarize: bool = True) -> dict:
    """
    Enrich founder backgrounds using Swarm API with batch async fetching.

    Fetches detailed profile information for all founders in a single batch
    API call, then updates the founders table with background text and sources.

    STATUS: IMPLEMENTED (Swarm batch async + optional OpenAI summarization)

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

    Returns early with zero counts if SWARM_API_KEY is not set (no error raised).
    """
    swarm = get_swarm_client()
    if swarm is None:
        logger.info("SWARM_API_KEY not set - skipping founder background enrichment")
        return {
            "company_id": normalize_company_id(company_id),
            "enriched_count": 0,
            "skipped_count": 0,
            "failed_count": 0,
            "founders": [],
            "skipped_reason": "SWARM_API_KEY not set",
        }

    normalized_id = normalize_company_id(company_id)

    # Get existing founders from Supabase
    founders = read_founders_from_supabase(normalized_id)

    if not founders:
        logger.info(f"No founders found in Supabase for {normalized_id}")
        return {
            "company_id": normalized_id,
            "enriched_count": 0,
            "skipped_count": 0,
            "failed_count": 0,
            "founders": [],
        }

    # Get company name for context
    company = read_company_from_supabase(normalized_id)
    company_name = company.company_name if company else None

    results = {
        "company_id": normalized_id,
        "enriched_count": 0,
        "skipped_count": 0,
        "failed_count": 0,
        "founders": [],
    }

    # Separate founders into those needing enrichment vs already enriched
    founders_to_enrich = []
    linkedin_urls_to_fetch = []

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

        # Collect for batch enrichment
        founders_to_enrich.append((founder, founder_result))
        if founder.linkedin_url:
            linkedin_urls_to_fetch.append(founder.linkedin_url)

    # If no founders need enrichment, return early
    if not founders_to_enrich:
        logger.info(f"All founders already enriched for {normalized_id}")
        return results

    # BATCH FETCH: Get all profiles in one API call
    profiles_by_slug: dict[str, FounderProfile] = {}

    if linkedin_urls_to_fetch:
        logger.info(f"Batch fetching {len(linkedin_urls_to_fetch)} LinkedIn profiles for {normalized_id}")
        try:
            fetched_profiles = swarm.fetch_company_founders(
                linkedin_urls_to_fetch,
                company_name=company_name
            )
            # Index by LinkedIn slug for matching
            for profile in fetched_profiles:
                if profile.linkedin_slug:
                    profiles_by_slug[profile.linkedin_slug.lower()] = profile
                if profile.linkedin_url:
                    # Also index by full URL for fallback matching
                    profiles_by_slug[profile.linkedin_url.lower()] = profile
            logger.info(f"Batch fetch returned {len(fetched_profiles)} profiles")
        except SwarmAPIError as e:
            logger.error(f"Batch Swarm fetch failed: {e}")

    # Process each founder with the fetched profiles
    for founder, founder_result in founders_to_enrich:
        profile: Optional[FounderProfile] = None

        # Try to find profile by LinkedIn URL
        if founder.linkedin_url:
            url_lower = founder.linkedin_url.lower()
            # Try full URL match
            if url_lower in profiles_by_slug:
                profile = profiles_by_slug[url_lower]
            else:
                # Try slug extraction
                slug = swarm._extract_linkedin_slug(founder.linkedin_url)
                if slug:
                    profile = profiles_by_slug.get(slug.lower())

        # Fallback: search by name (individual API call - only if batch didn't find)
        if not profile:
            try:
                swarm_profile = swarm.search_by_name_and_company(founder.name, company_name)
                if swarm_profile:
                    profile = swarm_profile.to_founder_profile()
                    profile.startup_company = company_name
            except SwarmAPIError as e:
                logger.warning(f"Swarm name search failed for {founder.name}: {e}")

        if not profile:
            founder_result["status"] = "failed"
            founder_result["reason"] = "Profile not found in Swarm"
            results["failed_count"] += 1
            results["founders"].append(founder_result)
            continue

        # Format background
        raw_background = profile.format_background()

        if not raw_background or len(raw_background) < 20:
            founder_result["status"] = "failed"
            founder_result["reason"] = "No meaningful background data"
            results["failed_count"] += 1
            results["founders"].append(founder_result)
            continue

        # Optionally summarize with LLM
        if summarize:
            background = _summarize_founder_background(
                name=founder.name,
                role_title=founder.role_title or "",
                raw_background=raw_background,
                company_name=company_name or "the company",
            )
        else:
            background = raw_background

        # Format sources as string for storage
        sources = []
        if profile.linkedin_url:
            sources.append({"network": "linkedin", "url": profile.linkedin_url})
        if profile.twitter_url:
            sources.append({"network": "twitter", "url": profile.twitter_url})

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

        sync_founders_to_supabase([founder], company_name=company_name)

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
    Fetch recent news articles for a company via Parallel Search.

    STATUS: IMPLEMENTED (Parallel Search)

    Args:
        company_id: Company URL or domain
        days: Number of days to look back (not currently used by Parallel Search)

    Returns:
        List of NewsArticle objects
    """
    normalized_id = normalize_company_id(company_id)

    parallel = get_parallel_client()
    if parallel is None:
        logger.info(f"get_recent_news: PARALLEL_API_KEY not set, skipping for {normalized_id}")
        return []

    # Resolve company name for search
    company_name = None
    existing = read_company_from_supabase(normalized_id)
    if existing:
        company_name = existing.company_name
    if not company_name:
        # Fall back to domain hint
        company_name = normalized_id.split(".")[0]

    try:
        results = parallel.search_company_news(company_name, max_results=10)
    except ParallelSearchError as e:
        logger.error(f"Parallel Search failed for {normalized_id}: {e}")
        return []

    # Transform to NewsArticle DB models
    articles: list[NewsArticle] = []
    for r in results:
        # Clean and join excerpts for LLM context
        if r.excerpts:
            cleaned_excerpts = []
            for excerpt in r.excerpts:
                cleaned = _clean_excerpt(excerpt, max_chars=500)
                if cleaned:
                    cleaned_excerpts.append(cleaned)
            excerpts_text = "\n".join(cleaned_excerpts) if cleaned_excerpts else None
        else:
            excerpts_text = None
        articles.append(NewsArticle(
            company_id=normalized_id,
            article_headline=r.title,
            outlet=r.source_domain,
            url=r.url,
            published_date=r.publish_date,
            excerpts=excerpts_text,
            observed_at=datetime.utcnow().isoformat(),
            source="parallel",
        ))

    # Generate synopsis and classify news type for each article
    if articles and company_name:
        logger.info(f"Generating synopsis for {len(articles)} news articles...")
        for article in articles:
            try:
                # Generate synopsis using LLM
                synopsis = _summarize_news_article(
                    headline=article.article_headline,
                    excerpts=article.excerpts or "",
                    outlet=article.outlet or "Unknown",
                    company_name=company_name,
                )
                article.synopsis = synopsis

                # Classify news type based on headline and excerpts
                excerpts_list = [article.excerpts] if article.excerpts else []
                article.news_type = _classify_signal_type(article.article_headline, excerpts_list)

                # Simple sentiment classification based on keywords
                headline_lower = article.article_headline.lower()
                if any(w in headline_lower for w in ["raises", "funding", "growth", "launches", "partnership", "expands"]):
                    article.sentiment = "positive"
                elif any(w in headline_lower for w in ["layoffs", "lawsuit", "decline", "fails", "shuts down"]):
                    article.sentiment = "negative"
                else:
                    article.sentiment = "neutral"

            except Exception as e:
                logger.warning(f"Failed to generate synopsis for '{article.article_headline[:50]}': {e}")

    if articles:
        logger.info(f"Fetched {len(articles)} news articles for {normalized_id}")

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
        # Format date from ISO timestamp (e.g. "2025-06-18T00:00:00Z") to "June 18, 2025"
        try:
            from datetime import datetime as _dt
            raw_date = company.funding_last_date
            for fmt in ("%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"):
                try:
                    parsed = _dt.strptime(raw_date, fmt)
                    formatted_date = parsed.strftime("%B %-d, %Y")
                    break
                except ValueError:
                    continue
            else:
                formatted_date = raw_date
        except Exception:
            formatted_date = company.funding_last_date
        description = f"Last funding: ${company.funding_last_amount:,.0f} on {formatted_date}"
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

            # VC-relevant signal types to include
            vc_relevant_types = {"product_update", "funding_news", "partnership", "team_change"}

            # Collect and filter signals
            relevant_updates = []
            for sig in intel.signals:
                desc = sig.get("description", "")

                # Skip non-English content (check for common non-ASCII patterns)
                if any(ord(c) > 127 for c in desc[:50]):
                    continue

                # Skip junk content
                junk_patterns = ["opens in a new tab", "opens in a new window", "Read more",
                                 "newsletter", "Subscribe", "inbox", "cookie"]
                if any(p.lower() in desc.lower() for p in junk_patterns):
                    continue

                # Clean and truncate
                clean_desc = _clean_excerpt(desc, max_chars=150)
                if clean_desc and len(clean_desc) > 30:
                    relevant_updates.append({
                        "type": sig["type"],
                        "desc": clean_desc
                    })

            # Create ONE consolidated website signal for VCs
            if relevant_updates:
                # Prioritize: funding > product > partnership > team > general
                priority_order = ["funding_news", "product_update", "partnership", "team_change", "general_update"]
                relevant_updates.sort(key=lambda x: priority_order.index(x["type"]) if x["type"] in priority_order else 99)

                # Take top 5 updates for LLM summarization
                top_updates = relevant_updates[:5]
                raw_content = "\n".join([f"- {u['desc']}" for u in top_updates])

                # Use LLM to create VC-friendly summary
                summary = _summarize_website_updates(raw_content, company.name if company else normalized_id)

                signals.append(KeySignal(
                    company_id=normalized_id,
                    signal_type="website_update",
                    description=summary,
                    observed_at=now,
                    source="tavily",
                ))

                logger.info(f"Tavily: {len(relevant_updates)} relevant signals for {normalized_id}")

            # Update website_update field on briefing_companies (Supabase)
            if relevant_updates:
                summary = f"{len(relevant_updates)} website updates detected"
                patch_company_website_update(normalized_id, summary)
        except TavilyAPIError as e:
            logger.error(f"Tavily API error for {normalized_id}: {e}")
        except Exception as e:
            logger.error(f"Tavily unexpected error for {normalized_id}: {type(e).__name__}: {e}")
    else:
        signals.append(KeySignal(
            company_id=normalized_id,
            signal_type="website_update",
            description="Website change detection not yet available (TAVILY_API_KEY not set)",
            observed_at=now,
            source="pending_tavily",
        ))

    # Note: News from Parallel Search is stored separately in the news table
    # via get_recent_news(). We don't duplicate it as signals here.

    if signals:
        logger.info(f"Fetched {len(signals)} signals for {normalized_id}")

    return signals


# =============================================================================
# TOOL 5a: get_competitors
# =============================================================================

# Heuristics for startup vs incumbent classification
_INCUMBENT_STAGES = {
    "public", "ipo", "post_ipo_equity", "post_ipo_debt", "post_ipo_secondary", "acquired"
}
_INCUMBENT_HEADCOUNT_THRESHOLD = 500
_INCUMBENT_FOUNDED_BEFORE = 2010


def _classify_competitor_type(company: HarmonicCompany) -> str:
    """Classify a competitor as 'startup' or 'incumbent' using simple heuristics."""
    stage = (company.funding_stage or "").lower().replace(" ", "_").replace("-", "_")
    if stage in _INCUMBENT_STAGES:
        return "incumbent"
    if company.headcount and company.headcount >= _INCUMBENT_HEADCOUNT_THRESHOLD:
        return "incumbent"
    if company.founded_year and company.founded_year < _INCUMBENT_FOUNDED_BEFORE:
        return "incumbent"
    return "startup"


def _first_sentence(text: str) -> str:
    """Return the first complete sentence of text."""
    import re
    match = re.search(r'.+?[.!?](?:\s|$)', text)
    return match.group(0).strip() if match else text.strip()


def get_competitors(company_id: str, max_per_type: int = 3) -> list[CompetitorSnapshot]:
    """
    Fetch top startup and incumbent competitors via Harmonic's similar_companies endpoint.

    Steps:
    1. Look up the company in Harmonic to get its internal ID
    2. Call find_similar_companies() to get similar companies
    3. Classify each as startup or incumbent
    4. Return top max_per_type of each type
    5. Sync to Supabase briefing_competitors table

    Args:
        company_id: Company URL or domain
        max_per_type: Max competitors to return per type (startup/incumbent)

    Returns:
        List of CompetitorSnapshot objects (up to max_per_type * 2 total)
    """
    normalized_id = normalize_company_id(company_id)
    client = get_harmonic_client()

    # Step 1: Resolve Harmonic internal ID (not stored in CompanyCore)
    try:
        url_type, normalized = parse_company_url(company_id)
        if url_type == "company_domain":
            hc_subject = client.lookup_company(domain=normalized)
        elif url_type == "company_linkedin":
            hc_subject = client.lookup_company(linkedin_url=normalized)
        else:
            hc_subject = client.lookup_company(domain=normalized_id)
    except HarmonicAPIError as e:
        logger.warning(f"Harmonic lookup failed for {normalized_id}: {e}")
        return []

    if not hc_subject or not hc_subject.id:
        logger.warning(f"No Harmonic record found for {normalized_id}")
        return []

    # Step 2: Fetch similar company URNs then resolve each to full HarmonicCompany
    # The endpoint returns URNs like 'urn:harmonic:company:1858', not full objects
    try:
        resp = client._request(
            "GET",
            f"/search/similar_companies/{hc_subject.id}",
            params={"page_size": max_per_type * 5},
        )
        similar_urns = resp.get("results", [])
    except Exception as e:
        logger.error(f"similar_companies request failed for {normalized_id}: {e}")
        return []

    if not similar_urns:
        logger.info(f"No similar companies returned by Harmonic for {normalized_id}")
        return []

    # Resolve URNs to full company objects
    similar: list[HarmonicCompany] = []
    for urn in similar_urns:
        if not (isinstance(urn, str) and ":" in urn):
            continue
        comp_harmonic_id = urn.split(":")[-1]
        try:
            hc = client.get_company(comp_harmonic_id)
            if hc:
                similar.append(hc)
        except Exception:
            continue

    # Step 3: Classify and bucket
    startups: list[CompetitorSnapshot] = []
    incumbents: list[CompetitorSnapshot] = []

    for hc in similar:
        ctype = _classify_competitor_type(hc)
        snapshot = CompetitorSnapshot(
            company_id=normalized_id,
            competitor_name=hc.name,
            competitor_domain=hc.domain,
            competitor_type=ctype,
            description=_first_sentence(hc.description) if hc.description else None,
            funding_total=hc.funding_total,
            funding_stage=hc.funding_stage,
            funding_last_amount=hc.funding_last_amount,
            funding_last_date=hc.funding_last_date,
            headcount=hc.headcount,
            tags=", ".join(hc.tags[:5]) if hc.tags else None,
            harmonic_id=hc.id,
        )
        if ctype == "startup":
            startups.append(snapshot)
        else:
            incumbents.append(snapshot)

    # Step 4: Sort by headcount as relevance proxy, take top N per type
    startups.sort(key=lambda c: c.headcount or 0, reverse=True)
    incumbents.sort(key=lambda c: c.headcount or 0, reverse=True)
    result = startups[:max_per_type] + incumbents[:max_per_type]

    # Step 5: Sync to Supabase
    if result:
        try:
            sync_competitors_to_supabase(result)
        except Exception as e:
            logger.error(f"Failed to sync competitors to Supabase for {normalized_id}: {e}")

    logger.info(
        f"Fetched {len(startups[:max_per_type])} startup and "
        f"{len(incumbents[:max_per_type])} incumbent competitors for {normalized_id}"
    )
    return result


# =============================================================================
# TOOL 5: ingest_company
# =============================================================================

def ingest_company(
    company_id: str,
    user: Optional[str] = None,
    enrich_backgrounds: bool = True,
) -> dict:
    """
    Single entrypoint for company data ingestion.

    Orchestrates all data fetching and database writes.
    NO LLM calls - pure data ingestion.

    Args:
        company_id: Company URL or domain
        user: Optional user identifier for tracking
        enrich_backgrounds: If True (default), enrich founder backgrounds using Swarm API

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
        "competitors_count": 0,
        "errors": [],
    }

    # 1. Fetch company profile
    try:
        company_core = get_company_profile(company_id)
        results["company_name"] = company_core.company_name
        results["company_core"] = True

        # Sync company to Supabase for Lovable UI
        try:
            sync_company_to_supabase(company_core)
        except Exception as e:
            results["errors"].append(f"Company Supabase sync: {str(e)}")
            logger.error(f"Failed to sync company to Supabase for {company_id}: {e}")
    except Exception as e:
        results["errors"].append(f"Company profile: {str(e)}")
        logger.error(f"Failed to ingest company profile for {company_id}: {e}")
        return results

    # 2. Fetch founders (sync to Supabase immediately so enrichment can read them)
    try:
        founders = get_founders(company_id)
        results["founders_count"] = len(founders)
        if founders:
            try:
                sync_founders_to_supabase(founders, company_name=results.get("company_name"))
            except Exception as e:
                results["errors"].append(f"Founder Supabase sync: {str(e)}")
                logger.error(f"Failed to sync founders to Supabase for {company_id}: {e}")
    except Exception as e:
        results["errors"].append(f"Founders: {str(e)}")
        logger.error(f"Failed to ingest founders for {company_id}: {e}")

    # 2b. Enrich founder backgrounds (reads from Supabase, writes enriched rows back)
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

        if signals:
            try:
                sync_signals_to_supabase(signals)
            except Exception as e:
                results["errors"].append(f"Signals Supabase sync: {str(e)}")
                logger.error(f"Failed to sync signals to Supabase for {company_id}: {e}")
    except Exception as e:
        results["errors"].append(f"Signals: {str(e)}")
        logger.error(f"Failed to ingest signals for {company_id}: {e}")

    # 4. Fetch recent news
    try:
        news = get_recent_news(company_id)
        results["news_count"] = len(news)

        # Sync news to Supabase for Lovable UI
        if news:
            try:
                sync_news_to_supabase(news, normalized_id)
            except Exception as e:
                results["errors"].append(f"News Supabase sync: {str(e)}")
                logger.error(f"Failed to sync news to Supabase for {company_id}: {e}")
    except Exception as e:
        results["errors"].append(f"News: {str(e)}")
        logger.error(f"Failed to ingest news for {company_id}: {e}")

    # 5. Fetch competitors
    try:
        competitors = get_competitors(company_id)
        results["competitors_count"] = len(competitors)
    except Exception as e:
        results["errors"].append(f"Competitors: {str(e)}")
        logger.error(f"Failed to fetch competitors for {company_id}: {e}")

    logger.info(
        f"Ingestion complete for {results['company_name']}: "
        f"founders={results['founders_count']} (enriched={results['founders_enriched']}), "
        f"signals={results['signals_count']}, "
        f"news={results['news_count']}, "
        f"competitors={results['competitors_count']}"
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
            "competitors_count": results["competitors_count"],
            "errors": results["errors"],
        }
    )

    return results


# =============================================================================
# TOOL 6: get_company_bundle
# =============================================================================

def get_company_bundle(company_id: str) -> CompanyBundle:
    """
    Read-only accessor for briefing generation. Pulls from Supabase only.

    Returns all stored data for a company. Does NOT fetch from APIs.

    Args:
        company_id: Company URL or domain

    Returns:
        CompanyBundle with all available data from Supabase
    """
    normalized_id = normalize_company_id(company_id)
    return get_company_bundle_from_supabase(normalized_id)

"""
Parallel Search API Client
===========================

External news and media research via Parallel Search API.
Returns compressed excerpts optimized for LLM context windows.

Usage:
    from core.clients.parallel_search import ParallelSearchClient

    client = ParallelSearchClient()
    results = client.search_company_news("Stripe")
"""

from __future__ import annotations

import os
import time
import logging
from dataclasses import dataclass, field
from typing import Optional
from urllib.parse import urlparse

from parallel import Parallel

from core.tracking import get_tracker

logger = logging.getLogger(__name__)

# =============================================================================
# CONFIGURATION
# =============================================================================

# Sentiment analysis keywords
SENTIMENT_KEYWORDS = {
    "positive": ["growth", "raised", "launch", "expansion", "milestone", "success", "partner"],
    "negative": ["layoff", "decline", "lawsuit", "investigation", "loss", "cut", "delay", "fail"],
}

# Tier-1 tech publications for targeted searches
TIER1_TECH_PUBLICATIONS = {
    "techcrunch": {
        "domain": "techcrunch.com",
        "name": "TechCrunch",
        "focus": ["startups", "funding", "product launches", "acquisitions"],
    },
    "venturebeat": {
        "domain": "venturebeat.com",
        "name": "VentureBeat",
        "focus": ["AI", "enterprise tech", "gaming"],
    },
    "theinformation": {
        "domain": "theinformation.com",
        "name": "The Information",
        "focus": ["exclusive scoops", "deep dives", "tech industry"],
    },
    "bloomberg": {
        "domain": "bloomberg.com",
        "name": "Bloomberg",
        "focus": ["finance", "markets", "business news"],
    },
    "reuters": {
        "domain": "reuters.com",
        "name": "Reuters",
        "focus": ["breaking news", "global business"],
    },
}

# Signal classification keywords (migrated from newsapi.py)
# Order matters: more specific types should come before general ones
SIGNAL_KEYWORDS = {
    "funding": ["funding", "raised", "series", "investment", "investor", "valuation", "ipo"],
    "acquisition": ["acquisition", "acquired", "merger", "merged", "buyout"],
    "executive_change": [
        "ceo", "cfo", "cto", "coo", "cpo", "chief", "president",
        "appoints", "appointed", "names", "named", "steps down", "departs", "resigns",
    ],
    "hiring_expansion": [
        "hiring", "hires", "headcount", "recruiting", "talent",
        "job openings", "growing team", "expanding team", "new hires",
    ],
    "team_change": ["hire", "hired", "appointment", "vp", "layoff", "restructur"],
    "product_launch": ["launch", "launched", "released", "new product", "announce", "introducing"],
    "partnership": ["partner", "partnership", "collaboration", "alliance", "integration"],
}


# =============================================================================
# DATA MODELS
# =============================================================================

@dataclass
class ParallelSearchResult:
    """Single search result from Parallel Search API."""
    url: str
    title: str
    publish_date: Optional[str] = None
    excerpts: list[str] = field(default_factory=list)
    source_domain: str = ""  # Parsed from URL


# =============================================================================
# EXCEPTIONS
# =============================================================================

class ParallelSearchError(Exception):
    """Custom exception for Parallel Search API errors."""
    def __init__(self, message: str, status_code: Optional[int] = None):
        super().__init__(message)
        self.status_code = status_code


# =============================================================================
# HELPER FUNCTIONS
# =============================================================================

def _extract_source_domain(url: str) -> str:
    """Extract clean domain name from URL for outlet field."""
    try:
        domain = urlparse(url).netloc
        return domain.replace("www.", "")
    except Exception:
        return ""


def _classify_signal_type(title: str, excerpts: list[str]) -> str:
    """Classify news into signal type based on content keywords."""
    combined = (title + " " + " ".join(excerpts)).lower()
    for signal_type, keywords in SIGNAL_KEYWORDS.items():
        if any(kw in combined for kw in keywords):
            return signal_type
    return "news_coverage"  # Default fallback


def _analyze_sentiment(title: str, excerpts: list[str]) -> str:
    """
    Analyze sentiment of news content using keyword matching.

    Args:
        title: Article title
        excerpts: List of article excerpts

    Returns:
        "positive", "negative", or "neutral"
    """
    combined = (title + " " + " ".join(excerpts)).lower()

    positive_count = sum(1 for kw in SENTIMENT_KEYWORDS["positive"] if kw in combined)
    negative_count = sum(1 for kw in SENTIMENT_KEYWORDS["negative"] if kw in combined)

    if positive_count > negative_count:
        return "positive"
    elif negative_count > positive_count:
        return "negative"
    return "neutral"


# =============================================================================
# CLIENT
# =============================================================================

class ParallelSearchClient:
    """
    External news research via Parallel Search API.

    Strategy:
      1. Generate targeted search queries for different news types
      2. Search with semantic objective describing desired content
      3. Classify results by content keywords
      4. Return excerpts optimized for LLM context
    """

    # Semantic objective for the search
    SEARCH_OBJECTIVE = (
        "Find recent news articles, press releases, and media coverage about this company. "
        "Focus on: funding announcements, product launches, executive changes, partnerships, "
        "acquisitions, and significant company developments. Prioritize reputable tech and "
        "business news sources like TechCrunch, VentureBeat, Bloomberg, Forbes, Reuters."
    )

    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or os.getenv("PARALLEL_API_KEY")
        if not self.api_key:
            raise ValueError(
                "Parallel API key required. Set PARALLEL_API_KEY environment variable "
                "or pass api_key parameter."
            )
        self._client = Parallel(api_key=self.api_key)
        self._tracker = get_tracker()

    def search_company_news(
        self,
        company_name: str,
        max_results: int = 10,
        max_chars_per_result: int = 5000,
    ) -> list[ParallelSearchResult]:
        """
        Search for external news coverage about a company.

        Args:
            company_name: Company name to search for
            max_results: Maximum results to return (default 10)
            max_chars_per_result: Excerpt length limit (default 5000)

        Returns:
            List of ParallelSearchResult with classified signals

        Raises:
            ParallelSearchError: If API request fails
        """
        # Generate diverse search queries
        search_queries = [
            f'"{company_name}" funding announcement',
            f'"{company_name}" product launch',
            f'"{company_name}" news',
            f'"{company_name}" TechCrunch OR VentureBeat OR Bloomberg',
        ]

        start = time.time()
        try:
            response = self._client.beta.search(
                objective=self.SEARCH_OBJECTIVE,
                search_queries=search_queries,
                max_results=max_results,
                excerpts={"max_chars_per_result": max_chars_per_result},
            )
            latency = int((time.time() - start) * 1000)

            self._tracker.log_api_call(
                service="parallel",
                endpoint="/search",
                method="POST",
                status_code=200,
                latency_ms=latency,
            )

        except Exception as e:
            latency = int((time.time() - start) * 1000)
            self._tracker.log_api_call(
                service="parallel",
                endpoint="/search",
                method="POST",
                status_code=500,
                latency_ms=latency,
            )
            logger.error(f"Parallel Search API error for '{company_name}': {e}")
            raise ParallelSearchError(f"API request failed: {e}")

        results = []
        for item in response.results or []:
            url = getattr(item, "url", "") or ""
            result = ParallelSearchResult(
                url=url,
                title=getattr(item, "title", "") or "",
                publish_date=getattr(item, "publish_date", None),
                excerpts=getattr(item, "excerpts", []) or [],
                source_domain=_extract_source_domain(url),
            )
            results.append(result)

        logger.info(f"Parallel Search: fetched {len(results)} results for '{company_name}'")
        return results

    def classify_result(self, result: ParallelSearchResult) -> str:
        """
        Classify a search result into a signal type.

        Args:
            result: ParallelSearchResult to classify

        Returns:
            Signal type string (funding, acquisition, team_change, etc.)
        """
        return _classify_signal_type(result.title, result.excerpts)

    def search_techcrunch_mentions(
        self,
        company_name: str,
        max_results: int = 10,
        max_chars_per_result: int = 5000,
    ) -> list[ParallelSearchResult]:
        """
        Search specifically for TechCrunch coverage of a company.

        TechCrunch is a key signal for VC-relevant news due to its focus on
        startups, funding rounds, and product launches.

        Args:
            company_name: Company name to search for
            max_results: Maximum results to return (default 10)
            max_chars_per_result: Excerpt length limit (default 5000)

        Returns:
            List of ParallelSearchResult from TechCrunch

        Raises:
            ParallelSearchError: If API request fails
        """
        # TechCrunch-specific search queries
        search_queries = [
            f'site:techcrunch.com "{company_name}"',
            f'"{company_name}" TechCrunch funding',
            f'"{company_name}" TechCrunch launch',
            f'"{company_name}" TechCrunch startup',
        ]

        techcrunch_objective = (
            "Find TechCrunch articles about this company. Focus on funding announcements, "
            "product launches, founder interviews, and startup news. TechCrunch is a leading "
            "tech publication that covers startups and venture capital extensively."
        )

        start = time.time()
        try:
            response = self._client.beta.search(
                objective=techcrunch_objective,
                search_queries=search_queries,
                max_results=max_results,
                excerpts={"max_chars_per_result": max_chars_per_result},
            )
            latency = int((time.time() - start) * 1000)

            self._tracker.log_api_call(
                service="parallel",
                endpoint="/search",
                method="POST",
                status_code=200,
                latency_ms=latency,
            )

        except Exception as e:
            latency = int((time.time() - start) * 1000)
            self._tracker.log_api_call(
                service="parallel",
                endpoint="/search",
                method="POST",
                status_code=500,
                latency_ms=latency,
            )
            logger.error(f"TechCrunch search error for '{company_name}': {e}")
            raise ParallelSearchError(f"API request failed: {e}")

        # Filter to only TechCrunch results and parse
        results = []
        for item in response.results or []:
            url = getattr(item, "url", "") or ""
            domain = _extract_source_domain(url)

            # Accept techcrunch.com results (may include subdomains)
            if "techcrunch" not in domain.lower():
                continue

            result = ParallelSearchResult(
                url=url,
                title=getattr(item, "title", "") or "",
                publish_date=getattr(item, "publish_date", None),
                excerpts=getattr(item, "excerpts", []) or [],
                source_domain=domain,
            )
            results.append(result)

        logger.info(f"TechCrunch search: found {len(results)} articles for '{company_name}'")
        return results

    def search_tier1_mentions(
        self,
        company_name: str,
        publications: list[str] | None = None,
        max_results: int = 15,
        max_chars_per_result: int = 5000,
    ) -> list[ParallelSearchResult]:
        """
        Search for company mentions in tier-1 tech publications.

        Args:
            company_name: Company name to search for
            publications: List of publication keys to search (default: all tier-1)
                         Valid keys: techcrunch, venturebeat, theinformation, bloomberg, reuters
            max_results: Maximum results to return (default 15)
            max_chars_per_result: Excerpt length limit (default 5000)

        Returns:
            List of ParallelSearchResult from tier-1 publications

        Raises:
            ParallelSearchError: If API request fails
        """
        # Default to all tier-1 publications
        if publications is None:
            publications = list(TIER1_TECH_PUBLICATIONS.keys())

        # Build site-specific queries
        search_queries = []
        domains = []
        for pub_key in publications:
            if pub_key in TIER1_TECH_PUBLICATIONS:
                pub = TIER1_TECH_PUBLICATIONS[pub_key]
                domains.append(pub["domain"])
                search_queries.append(f'site:{pub["domain"]} "{company_name}"')

        # Add a combined query for broader coverage
        if domains:
            domain_or = " OR ".join(f"site:{d}" for d in domains[:3])
            search_queries.append(f'"{company_name}" ({domain_or})')

        tier1_objective = (
            "Find articles from top-tier tech and business publications about this company. "
            "Focus on funding, acquisitions, product launches, executive changes, and major "
            "company developments. Prioritize recent and authoritative coverage."
        )

        start = time.time()
        try:
            response = self._client.beta.search(
                objective=tier1_objective,
                search_queries=search_queries,
                max_results=max_results,
                excerpts={"max_chars_per_result": max_chars_per_result},
            )
            latency = int((time.time() - start) * 1000)

            self._tracker.log_api_call(
                service="parallel",
                endpoint="/search",
                method="POST",
                status_code=200,
                latency_ms=latency,
            )

        except Exception as e:
            latency = int((time.time() - start) * 1000)
            self._tracker.log_api_call(
                service="parallel",
                endpoint="/search",
                method="POST",
                status_code=500,
                latency_ms=latency,
            )
            logger.error(f"Tier-1 search error for '{company_name}': {e}")
            raise ParallelSearchError(f"API request failed: {e}")

        # Filter to only tier-1 publication results
        target_domains = {pub["domain"] for pub in TIER1_TECH_PUBLICATIONS.values()}
        results = []
        for item in response.results or []:
            url = getattr(item, "url", "") or ""
            domain = _extract_source_domain(url)

            # Check if domain matches any tier-1 publication
            is_tier1 = any(td in domain.lower() for td in target_domains)
            if not is_tier1:
                continue

            result = ParallelSearchResult(
                url=url,
                title=getattr(item, "title", "") or "",
                publish_date=getattr(item, "publish_date", None),
                excerpts=getattr(item, "excerpts", []) or [],
                source_domain=domain,
            )
            results.append(result)

        logger.info(
            f"Tier-1 search: found {len(results)} articles for '{company_name}' "
            f"from {len(publications)} publications"
        )
        return results

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

# Signal classification keywords (migrated from newsapi.py)
SIGNAL_KEYWORDS = {
    "funding": ["funding", "raised", "series", "investment", "investor", "valuation", "ipo"],
    "acquisition": ["acquisition", "acquired", "merger", "merged", "buyout"],
    "team_change": ["hire", "hired", "appointment", "ceo", "cto", "vp", "layoff", "restructur"],
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

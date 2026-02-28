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

# Weighted sentiment keywords: keyword -> score (-5 to +5)
# Phrases should come before single words to match first
SENTIMENT_WEIGHTS = {
    # ==========================================================================
    # STRONG POSITIVE (+4 to +5) - High-impact value-creating events
    # ==========================================================================
    # Funding / liquidity
    'oversubscribed': 5,
    'unicorn': 5,
    'record revenue': 5,
    'record growth': 5,
    'raises': 4,
    'raised': 4,
    'ipo': 4,
    'public debut': 4,
    'spac merger': 3,
    'acquired for': 4,
    'exit': 4,
    # Financial performance
    'profitable': 4,
    'profitability': 4,
    'beats estimates': 4,
    'exceeds expectations': 4,
    'cash flow positive': 4,
    # Growth acceleration
    'hypergrowth': 5,
    'triples': 5,
    'surges': 4,
    'soars': 4,
    'doubles': 4,
    'rapid growth': 4,
    'accelerates': 3,
    # Market validation
    'major contract': 4,
    'enterprise deal': 4,
    'breakthrough': 4,
    'regulatory approval': 5,
    'fda approval': 5,
    'expands internationally': 4,
    'strategic partnership': 3,

    # ==========================================================================
    # MODERATE POSITIVE (+1 to +3) - Forward momentum
    # ==========================================================================
    # Hiring & expansion
    'extends runway': 3,
    'expands': 3,
    'hires': 2,
    'appoints': 2,
    'new office': 2,
    'launches': 2,
    'product launch': 2,
    'rollout': 2,
    'introduces': 1,
    # Customer traction
    'new customers': 2,
    'lands': 2,
    'signs': 2,
    'partnership': 2,
    'integrates with': 2,
    # Capital efficiency
    'cost reduction': 2,
    'efficiency gains': 2,
    # Recognition
    'award': 2,
    'ranked': 2,
    'featured': 1,
    # General positive
    'growth': 2,
    'milestone': 2,
    'success': 2,
    'expansion': 2,

    # ==========================================================================
    # STRONG NEGATIVE (-4 to -5) - Existential or major damage
    # ==========================================================================
    # Financial distress
    'bankrupt': -5,
    'bankruptcy': -5,
    'insolvent': -5,
    'liquidation': -5,
    'default': -5,
    'ceases operations': -5,
    # Security / compliance
    'data breach': -5,
    'breach': -5,
    'hack': -5,
    'cyberattack': -5,
    'fraud': -5,
    'embezzlement': -5,
    # Legal exposure
    'charged': -5,
    'indicted': -5,
    'lawsuit': -4,
    'sued': -4,
    'regulatory probe': -4,
    # Major contraction
    'layoffs': -4,
    'layoff': -4,
    'cuts workforce': -4,
    'shutdown': -4,
    'crash': -4,
    'plunges': -4,
    'misses estimates': -4,
    'revenue decline': -4,
    'guidance cut': -4,
    'down round': -4,
    'valuation cut': -4,
    # Restructuring
    'restructuring': -3,
    'investigation': -3,

    # ==========================================================================
    # MODERATE NEGATIVE (-1 to -3) - Concerning but not terminal
    # ==========================================================================
    'leadership departure': -3,
    'ceo steps down': -3,
    'customer churn': -3,
    'delays': -2,
    'warning': -2,
    'decline': -2,
    'slows': -2,
    'headwinds': -2,
    'competition intensifies': -2,
    'cash burn': -2,
    'concern': -1,
    'risk': -1,
    'cut': -2,
    'fail': -2,
    'loss': -2,
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


def _analyze_sentiment(title: str, excerpts: list[str]) -> int:
    """
    Analyze sentiment of news content using weighted keyword matching.

    Scoring methodology:
    - Strong positive (+4 to +5): High-impact value-creating events
      (funding, profitability, hypergrowth, regulatory approval)
    - Moderate positive (+1 to +3): Forward momentum
      (hiring, product launches, partnerships, customer wins)
    - Moderate negative (-1 to -3): Concerning but not terminal
      (delays, leadership changes, competition, cash burn)
    - Strong negative (-4 to -5): Existential or major damage
      (bankruptcy, breaches, lawsuits, layoffs, shutdown)

    Args:
        title: Article title
        excerpts: List of article excerpts

    Returns:
        Integer sentiment score from -5 to +5
    """
    combined = (title + " " + " ".join(excerpts)).lower()

    # Track matched keywords to avoid double-counting overlapping phrases
    matched_positions: set[int] = set()
    total_score = 0

    # Sort keywords by length (longest first) to match phrases before words
    sorted_keywords = sorted(SENTIMENT_WEIGHTS.keys(), key=len, reverse=True)

    for keyword in sorted_keywords:
        pos = combined.find(keyword)
        if pos != -1:
            # Check if this position range is already matched
            keyword_range = set(range(pos, pos + len(keyword)))
            if not keyword_range & matched_positions:
                total_score += SENTIMENT_WEIGHTS[keyword]
                matched_positions.update(keyword_range)

    # Clamp to -5 to +5 range
    return max(-5, min(5, total_score))


def sentiment_score_to_label(score: int) -> str:
    """
    Convert numeric sentiment score to display label.

    Args:
        score: Integer from -5 to +5

    Returns:
        Label with emoji indicator
    """
    if score >= 4:
        return f"📈 +{score}"
    elif score >= 1:
        return f"📈 +{score}"
    elif score <= -4:
        return f"📉 {score}"
    elif score <= -1:
        return f"📉 {score}"
    else:
        return "➖ +0"


def get_sentiment_label_simple(score: int) -> str:
    """
    Convert numeric sentiment score to simple label for database storage.

    Args:
        score: Integer from -5 to +5

    Returns:
        "positive", "negative", or "neutral"
    """
    if score >= 1:
        return "positive"
    elif score <= -1:
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

    def search_company_news_enhanced(
        self,
        company_name: str,
        domain: str,
        description: Optional[str] = None,
        investors: Optional[list[str]] = None,
        tags: Optional[list[str]] = None,
        max_results: int = 10,
        max_chars_per_result: int = 5000,
    ) -> list[ParallelSearchResult]:
        """
        Enhanced search using Harmonic company data for better results.

        Uses description keywords, domain, and investors to create
        targeted search queries that work better for smaller companies.

        Args:
            company_name: Company name (use exact casing from Harmonic)
            domain: Company domain (e.g., "namespace.so")
            description: Harmonic company description (for keyword extraction)
            investors: List of investor names (for funding news)
            tags: Industry tags (for context)
            max_results: Maximum results to return
            max_chars_per_result: Excerpt length limit

        Returns:
            List of ParallelSearchResult
        """
        # Extract key terms from description for disambiguation
        description_keywords = []
        if description:
            # Extract meaningful terms (products, technologies, etc.)
            import re
            # Look for capitalized terms, tech keywords
            tech_terms = re.findall(r'\b(?:Docker|GitHub|Kubernetes|CI/CD|API|SDK|SaaS|AI|ML|Cloud|AWS|GCP|Azure)\b', description, re.IGNORECASE)
            description_keywords = list(set(term.lower() for term in tech_terms))[:3]

        # Build enhanced search queries
        search_queries = []

        # 1. Company blog/announcements (direct from source)
        clean_domain = domain.replace("https://", "").replace("http://", "").rstrip("/")
        search_queries.append(f'site:{clean_domain} announcement OR launch OR funding OR news')

        # 2. Company name with description context (disambiguation)
        if description_keywords:
            context = " ".join(description_keywords[:2])
            search_queries.append(f'"{company_name}" {context} startup OR company')
        else:
            search_queries.append(f'"{company_name}" startup company news')

        # 3. Funding news with investor names (if available)
        if investors and len(investors) > 0:
            top_investors = investors[:2]
            investor_query = " OR ".join(f'"{inv}"' for inv in top_investors)
            search_queries.append(f'"{company_name}" ({investor_query}) funding OR raises')
        else:
            search_queries.append(f'"{company_name}" funding raises Series seed')

        # 4. Product/launch news in tech publications
        search_queries.append(f'"{company_name}" TechCrunch OR VentureBeat OR Hacker News')

        # 5. Domain-based search for any coverage mentioning the domain
        search_queries.append(f'"{clean_domain}" OR "{company_name}" launch OR announces')

        # Build a rich objective using company context
        objective = f"Find recent news articles about {company_name}"
        if description:
            # Add first sentence of description for context
            first_sentence = description.split('.')[0]
            objective = f"Find recent news about {company_name}, a company that {first_sentence.lower()}. Look for funding announcements, product launches, partnerships, and company updates."

        start = time.time()
        try:
            response = self._client.beta.search(
                objective=objective,
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

        logger.info(f"Parallel Search (enhanced): fetched {len(results)} results for '{company_name}' using domain={clean_domain}, {len(description_keywords)} keywords, {len(investors or [])} investors")
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

    def search_industry_news(
        self,
        industry: str,
        exclude_companies: list[str] | None = None,
        max_results: int = 10,
        max_chars_per_result: int = 500,  # Reduced for metadata-only
    ) -> list[ParallelSearchResult]:
        """
        Search for industry-wide news, excluding specific company names.

        Args:
            industry: Industry/category to search (e.g., "fintech", "cybersecurity")
            exclude_companies: Company names to exclude from results
            max_results: Maximum results to return (default 10)
            max_chars_per_result: Excerpt length limit (default 500 - metadata only)

        Returns:
            List of ParallelSearchResult for industry news

        Raises:
            ParallelSearchError: If API request fails
        """
        # Build exclusion string for queries
        exclusions = ""
        if exclude_companies:
            # Limit exclusions to avoid query length issues
            top_excludes = exclude_companies[:10]
            exclusions = " ".join(f'-"{name}"' for name in top_excludes)

        # Industry-focused search queries
        search_queries = [
            f'"{industry}" industry trends {exclusions}'.strip(),
            f'"{industry}" market news {exclusions}'.strip(),
            f'"{industry}" sector analysis {exclusions}'.strip(),
            f'"{industry}" regulation OR policy {exclusions}'.strip(),
        ]

        industry_objective = (
            f"Find recent news articles about the {industry} industry and market. "
            f"Focus on: industry trends, market analysis, regulatory changes, sector reports, "
            f"and macro developments. Exclude articles about specific company announcements. "
            f"Prioritize reputable business and tech news sources."
        )

        start = time.time()
        try:
            response = self._client.beta.search(
                objective=industry_objective,
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
            logger.error(f"Industry search error for '{industry}': {e}")
            raise ParallelSearchError(f"API request failed: {e}")

        # Filter results to exclude company mentions
        exclude_lower = {name.lower() for name in (exclude_companies or [])}
        results = []

        for item in response.results or []:
            url = getattr(item, "url", "") or ""
            title = getattr(item, "title", "") or ""
            excerpts = getattr(item, "excerpts", []) or []

            # Post-filter: skip if title/excerpts mention excluded companies
            combined_text = f"{title} {' '.join(excerpts)}".lower()
            if any(exc in combined_text for exc in exclude_lower):
                continue

            result = ParallelSearchResult(
                url=url,
                title=title,
                publish_date=getattr(item, "publish_date", None),
                excerpts=excerpts,
                source_domain=_extract_source_domain(url),
            )
            results.append(result)

        logger.info(
            f"Industry search: found {len(results)} articles for '{industry}' "
            f"(excluded {len(exclude_companies or [])} company names)"
        )
        return results

    def search_metadata_only(
        self,
        company_name: str,
        max_results: int = 10,
        max_chars_per_result: int = 500,  # Reduced for metadata
    ) -> list[ParallelSearchResult]:
        """
        Search for company news with minimal excerpt length (metadata-focused).

        This reduces token usage by returning shorter excerpts while still
        providing enough context for classification and synopsis generation.

        Args:
            company_name: Company name to search for
            max_results: Maximum results to return (default 10)
            max_chars_per_result: Excerpt length limit (default 500)

        Returns:
            List of ParallelSearchResult with shorter excerpts

        Raises:
            ParallelSearchError: If API request fails
        """
        # Same queries but shorter excerpts
        search_queries = [
            f'"{company_name}" funding announcement',
            f'"{company_name}" product launch',
            f'"{company_name}" news',
            f'"{company_name}" TechCrunch OR VentureBeat OR Bloomberg',
        ]

        metadata_objective = (
            "Find recent news about this company. Return key headlines and brief "
            "summaries focusing on: funding, products, executives, partnerships, "
            "acquisitions. Prioritize authoritative tech and business sources."
        )

        start = time.time()
        try:
            response = self._client.beta.search(
                objective=metadata_objective,
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
            logger.error(f"Metadata search error for '{company_name}': {e}")
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

        logger.info(f"Metadata search: fetched {len(results)} results for '{company_name}'")
        return results

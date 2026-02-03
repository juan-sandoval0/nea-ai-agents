"""
EventRegistry (newsapi.ai) API Client
======================================

News article search and event detection via EventRegistry API.
Uses conceptUri-based entity disambiguation for precise company matching.

Endpoints used:
- POST /api/v1/suggestConceptsFast - Resolve company name → conceptUri
- POST /api/v1/suggestCategoriesFast - Resolve category label → categoryUri
- POST /api/v1/article/getArticles - Search/fetch articles
- POST /api/v1/event/getEvents - Search events

Reference: https://newsapi.ai/documentation

Usage:
    from core.clients.newsapi import NewsApiClient

    client = NewsApiClient()
    articles = client.search_articles("Stripe", days_back=30)
"""

from __future__ import annotations

import os
import time
import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Optional

import requests

from core.tracking import get_tracker

logger = logging.getLogger(__name__)

# =============================================================================
# CONFIGURATION
# =============================================================================

BASE_URL = "https://eventregistry.org"
DEFAULT_TIMEOUT = 30
ARTICLES_PER_PAGE = 100

# Business/tech category URIs for filtering noise
BUSINESS_CATEGORY_URIS = [
    "news/Business",
    "news/Technology",
    "dmoz/Business",
    "dmoz/Business/Information_Technology",
]

# Event category → signal type mapping
EVENT_CATEGORY_MAP = {
    "funding": "funding",
    "investment": "funding",
    "acquisition": "acquisition",
    "merger": "acquisition",
    "ipo": "funding",
    "leadership": "team_change",
    "appointment": "team_change",
    "hire": "team_change",
    "layoff": "team_change",
    "product": "product_launch",
    "launch": "product_launch",
    "partnership": "partnership",
    "collaboration": "partnership",
}


# =============================================================================
# DATA MODELS
# =============================================================================

@dataclass
class NewsApiArticle:
    """Parsed article from EventRegistry API."""
    title: str
    url: str
    body: str
    source_name: str
    published_date: Optional[str] = None
    sentiment: Optional[float] = None
    image_url: Optional[str] = None
    raw_data: dict = field(default_factory=dict)

    @classmethod
    def from_api_response(cls, data: dict) -> "NewsApiArticle":
        source = data.get("source", {}) or {}
        return cls(
            title=data.get("title", ""),
            url=data.get("url", ""),
            body=data.get("body", "")[:500],  # snippet
            source_name=source.get("title", "") or data.get("source_name", ""),
            published_date=data.get("dateTime") or data.get("date"),
            sentiment=data.get("sentiment"),
            image_url=data.get("image"),
            raw_data=data,
        )


@dataclass
class NewsApiEvent:
    """Parsed event from EventRegistry API."""
    uri: str
    title: str
    event_date: Optional[str] = None
    categories: list[str] = field(default_factory=list)
    concepts: list[str] = field(default_factory=list)
    raw_data: dict = field(default_factory=dict)

    @classmethod
    def from_api_response(cls, data: dict) -> "NewsApiEvent":
        title_eng = data.get("title", {})
        if isinstance(title_eng, dict):
            title = title_eng.get("eng", "") or next(iter(title_eng.values()), "")
        else:
            title = str(title_eng)

        categories = []
        for cat in data.get("categories", []) or []:
            label = cat.get("label", "") if isinstance(cat, dict) else str(cat)
            if label:
                categories.append(label)

        concepts = []
        for concept in data.get("concepts", []) or []:
            label = concept.get("label", {})
            if isinstance(label, dict):
                name = label.get("eng", "") or next(iter(label.values()), "")
            else:
                name = str(label)
            if name:
                concepts.append(name)

        return cls(
            uri=data.get("uri", ""),
            title=title,
            event_date=data.get("eventDate"),
            categories=categories,
            concepts=concepts[:10],
            raw_data=data,
        )

    def to_signal_type(self) -> str:
        """Map event categories/title to a signal type."""
        text = (self.title + " " + " ".join(self.categories)).lower()
        for keyword, signal_type in EVENT_CATEGORY_MAP.items():
            if keyword in text:
                return signal_type
        return "news_event"


# =============================================================================
# EXCEPTIONS
# =============================================================================

class NewsApiError(Exception):
    """Custom exception for EventRegistry API errors."""
    def __init__(self, message: str, status_code: Optional[int] = None):
        super().__init__(message)
        self.status_code = status_code


# =============================================================================
# CLIENT
# =============================================================================

class NewsApiClient:
    """
    REST client for EventRegistry (newsapi.ai) API.

    Uses conceptUri-based entity disambiguation when possible, falling back
    to keyword search with business/tech category filters for smaller companies.

    Usage:
        client = NewsApiClient()
        articles = client.search_articles("Stripe", days_back=30)
        events = client.get_events("Stripe", days_back=30)
    """

    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or os.getenv("NEWSAPI_API_KEY")
        if not self.api_key:
            raise ValueError(
                "EventRegistry API key required. Set NEWSAPI_API_KEY environment variable "
                "or pass api_key parameter."
            )
        self.session = requests.Session()
        self._tracker = get_tracker()
        self._concept_cache: dict[str, Optional[str]] = {}

    # =========================================================================
    # CONCEPT / CATEGORY RESOLUTION
    # =========================================================================

    def _resolve_concept_uri(self, keyword: str) -> Optional[str]:
        """
        Resolve a company name to an EventRegistry conceptUri.

        Uses source=["org"] to restrict to organizations, avoiding
        disambiguation issues (e.g. "Stripe" → flag pattern).
        Falls back to broader search with manual org-type filtering.
        """
        if keyword in self._concept_cache:
            return self._concept_cache[keyword]

        # Try with org-only source first (most precise)
        try:
            data = self._request("POST", "/api/v1/suggestConceptsFast", json_data={
                "prefix": keyword,
                "source": ["org"],
                "lang": "eng",
                "conceptLang": ["eng"],
            })
            if isinstance(data, list) and data:
                uri = data[0].get("uri")
                self._concept_cache[keyword] = uri
                logger.info(f"NewsAPI concept resolved (org): '{keyword}' -> {uri}")
                return uri
        except NewsApiError:
            pass

        # Fallback: broader search, filter for org type
        try:
            data = self._request("POST", "/api/v1/suggestConceptsFast", json_data={
                "prefix": keyword,
                "source": ["concepts"],
                "lang": "eng",
                "conceptLang": ["eng"],
            })
            if isinstance(data, list):
                for item in data:
                    if item.get("type") == "org":
                        uri = item.get("uri")
                        self._concept_cache[keyword] = uri
                        logger.info(f"NewsAPI concept resolved (fallback): '{keyword}' -> {uri}")
                        return uri
        except NewsApiError:
            pass

        self._concept_cache[keyword] = None
        logger.info(f"NewsAPI concept not found for '{keyword}', will use keyword search")
        return None

    # =========================================================================
    # HTTP
    # =========================================================================

    def _request(self, method: str, endpoint: str, params: Optional[dict] = None, json_data: Optional[dict] = None) -> dict:
        """Make an API request with error handling and tracking."""
        url = BASE_URL + endpoint

        # Inject API key into the appropriate location
        if method == "POST":
            if json_data is None:
                json_data = {}
            json_data["apiKey"] = self.api_key
        else:
            if params is None:
                params = {}
            params["apiKey"] = self.api_key

        start = time.time()
        try:
            response = self.session.request(
                method=method,
                url=url,
                params=params if method == "GET" else None,
                json=json_data if method == "POST" else None,
                timeout=DEFAULT_TIMEOUT,
            )
            latency = int((time.time() - start) * 1000)

            self._tracker.log_api_call(
                service="newsapi",
                endpoint=endpoint,
                method=method,
                status_code=response.status_code,
                latency_ms=latency,
            )

            logger.debug(f"NewsAPI {method} {endpoint} -> {response.status_code}")

            if response.status_code == 401:
                raise NewsApiError("Invalid API key", status_code=401)
            elif response.status_code == 429:
                raise NewsApiError("Rate limit exceeded", status_code=429)
            elif response.status_code >= 400:
                raise NewsApiError(
                    f"API error: {response.text[:200]}",
                    status_code=response.status_code,
                )

            return response.json() if response.content else {}

        except requests.exceptions.Timeout:
            raise NewsApiError(f"Request timed out after {DEFAULT_TIMEOUT}s")
        except requests.exceptions.ConnectionError as e:
            raise NewsApiError(f"Connection error: {e}")

    # =========================================================================
    # ARTICLE SEARCH
    # =========================================================================

    def search_articles(
        self,
        keyword: str,
        days_back: int = 30,
        date_start: Optional[str] = None,
        date_end: Optional[str] = None,
        max_pages: int = 1,
    ) -> list[NewsApiArticle]:
        """
        Search for news articles about a company.

        Uses conceptUri when the company can be resolved to a known entity
        (precise, NLP-tagged matching). Falls back to keyword search with
        business/tech category filters and source quality ranking.

        Args:
            keyword: Company name
            days_back: Days to look back (used if date_start not provided)
            date_start: Start date (YYYY-MM-DD)
            date_end: End date (YYYY-MM-DD)
            max_pages: Max pages to fetch (100 articles per page)

        Returns:
            List of NewsApiArticle objects
        """
        now = datetime.utcnow()
        if not date_end:
            date_end = now.strftime("%Y-%m-%d")
        if not date_start:
            date_start = (now - timedelta(days=days_back)).strftime("%Y-%m-%d")

        concept_uri = self._resolve_concept_uri(keyword)

        all_articles: list[NewsApiArticle] = []
        seen_urls: set[str] = set()

        for page in range(1, max_pages + 1):
            body: dict = {
                "dateStart": date_start,
                "dateEnd": date_end,
                "articlesPage": page,
                "articlesCount": ARTICLES_PER_PAGE,
                "articlesSortBy": "rel",
                "lang": "eng",
                "resultType": "articles",
                "isDuplicateFilter": "skipDuplicates",
            }

            if concept_uri:
                # Precise entity-based search — no keyword noise
                body["conceptUri"] = concept_uri
            else:
                # Keyword fallback with quality filters to reduce noise
                body["keyword"] = keyword
                body["keywordSearchMode"] = "phrase"
                body["categoryUri"] = BUSINESS_CATEGORY_URIS
                # Restrict to higher-quality sources (top 50%)
                body["startSourceRankPercentile"] = 0
                body["endSourceRankPercentile"] = 50

            try:
                data = self._request("POST", "/api/v1/article/getArticles", json_data=body)
            except NewsApiError:
                logger.warning(f"NewsAPI article search failed for '{keyword}' page {page}")
                break

            articles_data = data.get("articles", {})
            results = articles_data.get("results", []) if isinstance(articles_data, dict) else []

            for item in results:
                url = item.get("url", "")
                if url and url not in seen_urls:
                    seen_urls.add(url)
                    all_articles.append(NewsApiArticle.from_api_response(item))

            if len(results) < ARTICLES_PER_PAGE:
                break

        logger.info(f"NewsAPI: fetched {len(all_articles)} articles for '{keyword}' (concept={'yes' if concept_uri else 'no'})")
        return all_articles

    # =========================================================================
    # EVENT SEARCH
    # =========================================================================

    def get_events(
        self,
        keyword: str,
        days_back: int = 30,
        date_start: Optional[str] = None,
        date_end: Optional[str] = None,
    ) -> list[NewsApiEvent]:
        """
        Get events related to a company.

        Uses conceptUri when available for precise entity matching,
        keyword fallback otherwise.

        Args:
            keyword: Company name
            days_back: Days to look back
            date_start: Start date (YYYY-MM-DD)
            date_end: End date (YYYY-MM-DD)

        Returns:
            List of NewsApiEvent objects
        """
        now = datetime.utcnow()
        if not date_end:
            date_end = now.strftime("%Y-%m-%d")
        if not date_start:
            date_start = (now - timedelta(days=days_back)).strftime("%Y-%m-%d")

        concept_uri = self._resolve_concept_uri(keyword)

        body: dict = {
            "dateStart": date_start,
            "dateEnd": date_end,
            "lang": "eng",
            "resultType": "events",
            "eventsSortBy": "rel",
            "eventsCount": 50,
        }

        if concept_uri:
            body["conceptUri"] = concept_uri
        else:
            body["keyword"] = keyword
            body["keywordSearchMode"] = "phrase"

        try:
            data = self._request("POST", "/api/v1/event/getEvents", json_data=body)
        except NewsApiError:
            logger.warning(f"NewsAPI event search failed for '{keyword}'")
            return []

        events_data = data.get("events", {})
        results = events_data.get("results", []) if isinstance(events_data, dict) else []

        events = [NewsApiEvent.from_api_response(item) for item in results]
        logger.info(f"NewsAPI: fetched {len(events)} events for '{keyword}' (concept={'yes' if concept_uri else 'no'})")
        return events

    # =========================================================================
    # ARTICLE DETAILS
    # =========================================================================

    def get_article_details(self, article_uris: list[str]) -> list[NewsApiArticle]:
        """
        Batch lookup articles by URI.

        Args:
            article_uris: List of article URIs (up to 100)

        Returns:
            List of NewsApiArticle objects
        """
        if not article_uris:
            return []

        uris = article_uris[:100]
        body = {
            "articleUri": uris,
            "resultType": "articles",
        }

        try:
            data = self._request("POST", "/api/v1/article/getArticles", json_data=body)
        except NewsApiError:
            logger.warning(f"NewsAPI article details fetch failed for {len(uris)} URIs")
            return []

        articles_data = data.get("articles", {})
        results = articles_data.get("results", []) if isinstance(articles_data, dict) else []

        return [NewsApiArticle.from_api_response(item) for item in results]

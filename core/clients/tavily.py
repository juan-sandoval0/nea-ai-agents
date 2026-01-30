"""
Tavily API Client
==================

Website intelligence via Tavily search API.
Uses 2 credits per company: 1 for news, 1 for website changes.

Usage:
    from core.clients import TavilyClient

    client = TavilyClient()
    intel = client.analyze_company_website("stripe.com")
"""

from __future__ import annotations

import os
import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

logger = logging.getLogger(__name__)

# Signal classification keywords
SIGNAL_KEYWORDS = {
    "product_update": [
        "launch", "released", "new feature", "update", "upgrade", "beta",
        "product", "platform", "api", "integration", "v2", "v3",
    ],
    "pricing_change": [
        "pricing", "price", "cost", "plan", "tier", "subscription",
        "free tier", "enterprise", "discount",
    ],
    "team_change": [
        "hire", "hired", "appointment", "join", "joined", "ceo", "cto",
        "vp", "head of", "director", "layoff", "restructur",
    ],
    "partnership": [
        "partner", "partnership", "collaboration", "alliance", "integration with",
        "teams up", "joins forces",
    ],
    "funding_news": [
        "funding", "raised", "series", "investment", "investor", "valuation",
        "ipo", "acquisition", "acquired",
    ],
}


# =============================================================================
# DATA MODELS
# =============================================================================

@dataclass
class TavilySearchResult:
    """Single search result from Tavily API."""
    title: str
    url: str
    content: str
    score: float
    published_date: Optional[str] = None
    raw_data: dict = field(default_factory=dict)

    @classmethod
    def from_api_response(cls, data: dict) -> "TavilySearchResult":
        return cls(
            title=data.get("title", ""),
            url=data.get("url", ""),
            content=data.get("content", ""),
            score=data.get("score", 0.0),
            published_date=data.get("published_date"),
            raw_data=data,
        )


@dataclass
class WebsiteIntelligence:
    """Aggregated output from analyzing a company's web presence."""
    domain: str
    signals: list[dict] = field(default_factory=list)
    answer_summary: Optional[str] = None
    credit_cost: int = 2
    fetched_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())


class TavilyAPIError(Exception):
    """Custom exception for Tavily API errors."""
    def __init__(self, message: str, status_code: Optional[int] = None):
        super().__init__(message)
        self.status_code = status_code


# =============================================================================
# TAVILY CLIENT
# =============================================================================

class TavilyClient:
    """
    Thin wrapper around tavily-python for website intelligence.

    Budget: 2 credits per company.
    """

    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or os.getenv("TAVILY_API_KEY")
        if not self.api_key:
            raise ValueError(
                "Tavily API key required. Set TAVILY_API_KEY environment variable "
                "or pass api_key parameter."
            )
        from tavily import TavilyClient as _TavilyClient
        self._client = _TavilyClient(api_key=self.api_key)

    def search_news(self, domain: str, days: int = 30, max_results: int = 5) -> dict:
        """Search for recent news/announcements on a domain. 1 credit."""
        try:
            return self._client.search(
                query=f"site:{domain} recent news announcements",
                topic="news",
                include_domains=[domain],
                days=days,
                max_results=max_results,
                include_answer=True,
            )
        except Exception as e:
            raise TavilyAPIError(f"News search failed for {domain}: {e}")

    def search_website_changes(self, domain: str, days: int = 90, max_results: int = 5) -> dict:
        """Search for product/pricing/team changes on a domain. 1 credit."""
        try:
            return self._client.search(
                query=f"site:{domain} product pricing team updates changes",
                topic="general",
                include_domains=[domain],
                days=days,
                max_results=max_results,
                include_answer=True,
            )
        except Exception as e:
            raise TavilyAPIError(f"Website changes search failed for {domain}: {e}")

    def analyze_company_website(self, domain: str) -> WebsiteIntelligence:
        """
        Run both searches and categorize results into signals.
        2 credits total.
        """
        signals: list[dict] = []
        answer_parts: list[str] = []

        # Search 1: Recent news (1 credit)
        try:
            news_response = self.search_news(domain)
            if news_response.get("answer"):
                answer_parts.append(news_response["answer"])
            for result_data in news_response.get("results", []):
                result = TavilySearchResult.from_api_response(result_data)
                signal = _classify_result(result)
                signals.append(signal)
        except TavilyAPIError as e:
            logger.warning(f"Tavily news search failed for {domain}: {e}")

        # Search 2: Website changes (1 credit)
        try:
            changes_response = self.search_website_changes(domain)
            if changes_response.get("answer"):
                answer_parts.append(changes_response["answer"])
            for result_data in changes_response.get("results", []):
                result = TavilySearchResult.from_api_response(result_data)
                signal = _classify_result(result)
                # Avoid duplicate URLs
                if not any(s["url"] == signal["url"] for s in signals):
                    signals.append(signal)
        except TavilyAPIError as e:
            logger.warning(f"Tavily website changes search failed for {domain}: {e}")

        answer_summary = " | ".join(answer_parts) if answer_parts else None

        return WebsiteIntelligence(
            domain=domain,
            signals=signals,
            answer_summary=answer_summary,
            credit_cost=2,
        )


# =============================================================================
# SIGNAL CLASSIFICATION
# =============================================================================

def _classify_result(result: TavilySearchResult) -> dict:
    """Classify a search result into a signal type based on keywords."""
    text = f"{result.title} {result.content}".lower()

    signal_type = "general_update"
    for stype, keywords in SIGNAL_KEYWORDS.items():
        if any(kw in text for kw in keywords):
            signal_type = stype
            break

    # Build one-line description
    description = result.title.strip()
    if result.url:
        description += f" (source: {result.url})"

    return {
        "type": signal_type,
        "description": result.title.strip(),
        "url": result.url,
        "date": result.published_date,
    }

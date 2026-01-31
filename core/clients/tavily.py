"""
Tavily API Client
==================

Website intelligence via Tavily search + extract APIs.
Budget: ~3 credits per company.
  - 1 credit: basic search for recent company mentions
  - 1 credit: basic extract on up to 5 URLs from search results

Usage:
    from core.clients import TavilyClient

    client = TavilyClient()
    intel = client.analyze_company_website("mercor.com")
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
        "product", "platform", "api", "integration", "v2", "v3", "announce",
        "now available", "introducing", "rollout", "ship",
    ],
    "pricing_change": [
        "pricing", "price", "cost", "plan", "tier", "subscription",
        "free tier", "enterprise", "discount", "rate",
    ],
    "team_change": [
        "hire", "hired", "appointment", "join", "joined", "ceo", "cto",
        "vp", "head of", "director", "layoff", "restructur", "new role",
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
    credit_cost: int = 0
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
    Website intelligence via Tavily search + extract.

    Strategy:
      1. search (basic, 1 credit) - find recent pages about the company
      2. extract (basic, ~1 credit per 5 URLs) - get full content from top results
      3. Classify and summarize from extracted content
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

    def search(self, query: str, max_results: int = 5, **kwargs) -> dict:
        """Run a basic search. 1 credit."""
        try:
            return self._client.search(
                query=query,
                max_results=max_results,
                include_answer=True,
                **kwargs,
            )
        except Exception as e:
            raise TavilyAPIError(f"Search failed: {e}")

    def extract(self, urls: list[str]) -> dict:
        """Extract full content from URLs. 1 credit per 5 successful extractions."""
        try:
            return self._client.extract(urls=urls)
        except Exception as e:
            raise TavilyAPIError(f"Extract failed: {e}")

    def analyze_company_website(self, domain: str) -> WebsiteIntelligence:
        """
        Search for recent company activity, then extract full content
        from top results to build meaningful signals.

        ~2-3 credits total.
        """
        credits_used = 0
        signals: list[dict] = []
        answer_summary = None

        # Step 1: Search for recent company activity (1 credit)
        # Use domain without TLD as a company name hint for better results
        company_hint = domain.split(".")[0]
        search_results = []
        try:
            response = self.search(
                query=f'"{company_hint}" company news updates announcements',
                topic="news",
                days=30,
                max_results=5,
            )
            credits_used += 1
            answer_summary = response.get("answer")
            search_results = response.get("results", [])
        except TavilyAPIError as e:
            logger.warning(f"Tavily search failed for {domain}: {e}")

        if not search_results:
            return WebsiteIntelligence(
                domain=domain,
                answer_summary=answer_summary,
                credit_cost=credits_used,
            )

        # Step 2: Extract full content from top URLs (1 credit for up to 5 URLs)
        urls = [r["url"] for r in search_results if r.get("url")][:5]
        extracted_content = {}  # url -> full text

        if urls:
            try:
                extract_response = self.extract(urls)
                credits_used += 1
                for item in extract_response.get("results", []):
                    url = item.get("url", "")
                    text = item.get("raw_content", "") or item.get("text", "")
                    if url and text:
                        extracted_content[url] = text
            except TavilyAPIError as e:
                logger.warning(f"Tavily extract failed for {domain}: {e}")

        # Step 3: Build signals from search results enriched with extracted content
        # Only keep results that actually mention the company
        company_hint_lower = company_hint.lower()
        for result_data in search_results:
            result = TavilySearchResult.from_api_response(result_data)
            # Relevance check: company name must appear in title, URL, or content
            combined_text = f"{result.title} {result.url} {result.content}".lower()
            if company_hint_lower not in combined_text:
                continue
            full_text = extracted_content.get(result.url, "")
            signal = _classify_and_summarize(result, full_text)
            if signal:
                signals.append(signal)

        return WebsiteIntelligence(
            domain=domain,
            signals=signals,
            answer_summary=answer_summary,
            credit_cost=credits_used,
        )


# =============================================================================
# SIGNAL CLASSIFICATION & SUMMARIZATION
# =============================================================================

def _classify_and_summarize(result: TavilySearchResult, full_text: str) -> Optional[dict]:
    """Classify a result and build a meaningful description from extracted content."""
    # Use full extracted text if available, otherwise fall back to search snippet
    content = full_text or result.content
    combined = f"{result.title} {content}".lower()

    # Classify signal type
    signal_type = "general_update"
    for stype, keywords in SIGNAL_KEYWORDS.items():
        if any(kw in combined for kw in keywords):
            signal_type = stype
            break

    # Build description from the best available content
    title = result.title.strip()

    if full_text:
        # Extract the most informative sentences from full content
        summary = _extract_key_sentences(full_text, max_chars=200)
        if summary:
            description = summary
        else:
            description = title
    elif result.content.strip():
        description = result.content.strip()[:200]
    else:
        description = title

    # Don't return signals with no real information
    if len(description) < 10:
        return None

    return {
        "type": signal_type,
        "description": description,
        "url": result.url,
        "date": result.published_date,
    }


def _extract_key_sentences(text: str, max_chars: int = 200) -> str:
    """Extract the most informative sentences from extracted page content."""
    import re

    # Skip lines that look like boilerplate or markup
    skip_patterns = [
        "skip to content", "cookie", "accept all", "privacy", "subscribe",
        "sign up", "log in", "menu", "navigation", "search", "toggle",
        "share this", "follow us", "copyright", "all rights reserved",
    ]

    sentences = []
    for line in text.split("\n"):
        line = line.strip()
        # Skip short lines, markdown images, links-only lines, headers with just nav
        if not line or len(line) < 30:
            continue
        if line.startswith(("![", "* [", "- [", "#", "|", ">")):
            continue
        # Skip lines that are mostly URLs or markdown
        if line.count("http") > 1 or line.count("](") > 1:
            continue
        if any(p in line.lower() for p in skip_patterns):
            continue

        # Clean markdown artifacts
        clean = re.sub(r'\[([^\]]+)\]\([^)]+\)', r'\1', line)  # [text](url) -> text
        clean = re.sub(r'[#*_`]', '', clean).strip()

        # Split into sentences
        for sent in clean.split(". "):
            sent = sent.strip()
            if len(sent) > 30:
                sentences.append(sent)

    if not sentences:
        return ""

    # Take the first few meaningful sentences up to max_chars
    result = []
    total = 0
    for sent in sentences[:5]:
        if total + len(sent) > max_chars:
            break
        result.append(sent)
        total += len(sent) + 2

    return ". ".join(result)

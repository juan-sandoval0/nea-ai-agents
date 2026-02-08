"""
Tavily API Client
==================

Website intelligence via Tavily Crawl API.
Crawls a company's own website to discover product updates, blog posts,
press releases, and other strategic content.

Usage:
    from core.clients import TavilyClient

    client = TavilyClient()
    intel = client.crawl_company_website("stripe.com")
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
    Website intelligence via Tavily Crawl API.

    Strategy:
      1. crawl - discover pages on the company's website (blog, news, pricing, etc.)
      2. Classify each page by URL path and content keywords
      3. Extract key sentences to build meaningful signals
    """

    # Path patterns to prioritize during crawl
    CRAWL_SELECT_PATHS = [
        "/blog.*",
        "/news.*",
        "/press.*",
        "/newsroom.*",
        "/changelog.*",
        "/releases.*",
        "/updates.*",
        "/announcements.*",
        "/about.*",
        "/team.*",
        "/careers.*",
        "/pricing.*",
        "/plans.*",
        "/product.*",
        "/features.*",
        "/launch.*",
    ]

    # Natural language instructions for the crawler
    CRAWL_INSTRUCTIONS = (
        "Find pages about: product announcements, feature launches, company news, "
        "press releases, blog posts, pricing information, team updates, and recent "
        "company developments. Prioritize recent content and official announcements."
    )

    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or os.getenv("TAVILY_API_KEY")
        if not self.api_key:
            raise ValueError(
                "Tavily API key required. Set TAVILY_API_KEY environment variable "
                "or pass api_key parameter."
            )
        # Debug: log key info (masked)
        key_preview = f"{self.api_key[:8]}...{self.api_key[-4:]}" if len(self.api_key) > 12 else "too_short"
        logger.info(f"Tavily client initializing with key: {key_preview} (len={len(self.api_key)})")
        from tavily import TavilyClient as _TavilyClient
        self._client = _TavilyClient(api_key=self.api_key)

    def crawl_company_website(self, url: str) -> WebsiteIntelligence:
        """
        Crawl a company's website to discover product updates, blog posts,
        press releases, and other strategic content.

        Args:
            url: Company website URL (e.g., "https://stripe.com" or "stripe.com")

        Returns:
            WebsiteIntelligence with classified signals from crawled pages
        """
        # Normalize URL
        if not url.startswith(("http://", "https://")):
            url = f"https://{url}"

        # Extract domain for the response
        from urllib.parse import urlparse
        parsed = urlparse(url)
        domain = parsed.netloc or parsed.path.split("/")[0]

        signals: list[dict] = []

        try:
            response = self._client.crawl(
                url=url,
                max_depth=2,
                limit=30,
                allow_external=False,
                instructions=self.CRAWL_INSTRUCTIONS,
                select_paths=self.CRAWL_SELECT_PATHS,
                timeout=120,
            )
        except Exception as e:
            logger.warning(f"Tavily crawl failed for {url}: {e}")
            raise TavilyAPIError(f"Crawl failed: {e}")

        # Process crawled pages
        results = response.get("results", [])
        logger.info(f"Tavily crawl returned {len(results)} pages for {domain}")

        for page in results:
            page_url = page.get("url", "")
            raw_content = page.get("raw_content", "")

            if not page_url or not raw_content:
                continue

            signal = _classify_crawled_page(page_url, raw_content)
            if signal:
                signals.append(signal)

        return WebsiteIntelligence(
            domain=domain,
            signals=signals,
            credit_cost=1,  # Crawl uses credits based on pages crawled
        )


# =============================================================================
# SIGNAL CLASSIFICATION & SUMMARIZATION
# =============================================================================

# URL path hints for classification boost
PATH_TYPE_HINTS = {
    "product_update": ["/blog", "/changelog", "/releases", "/updates", "/launch", "/announcements", "/product", "/features"],
    "pricing_change": ["/pricing", "/plans"],
    "team_change": ["/team", "/about", "/careers"],
    "partnership": ["/partners", "/integrations"],
    "funding_news": ["/press", "/news", "/newsroom"],
}


def _classify_crawled_page(url: str, raw_content: str) -> Optional[dict]:
    """
    Classify a crawled page and build a meaningful signal.

    Uses URL path hints for classification boost, then falls back to
    content keyword matching.
    """
    from urllib.parse import urlparse

    if not raw_content or len(raw_content) < 50:
        return None

    parsed = urlparse(url)
    path = parsed.path.lower()
    content_lower = raw_content.lower()

    # Try to classify by URL path first
    signal_type = None
    for stype, path_patterns in PATH_TYPE_HINTS.items():
        if any(pattern in path for pattern in path_patterns):
            signal_type = stype
            break

    # Fall back to content keyword matching
    if signal_type is None:
        signal_type = "general_update"
        for stype, keywords in SIGNAL_KEYWORDS.items():
            if any(kw in content_lower for kw in keywords):
                signal_type = stype
                break

    # Extract key sentences for description
    description = _extract_key_sentences(raw_content, max_chars=200)

    if not description or len(description) < 10:
        return None

    return {
        "type": signal_type,
        "description": description,
        "url": url,
        "date": None,  # Crawl doesn't provide dates
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

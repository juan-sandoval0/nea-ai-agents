"""
Weekly Digest Generator
=======================

Aggregates the past 7 days of signals, scores and ranks articles,
and generates a digest with featured and summarized articles.

Usage:
    from agents.news_aggregator.digest import generate_weekly_digest

    digest = generate_weekly_digest()
    print(digest.to_markdown())
"""

from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, List, Dict, Any

# Load environment variables from .env file
try:
    from dotenv import load_dotenv
    env_path = Path(__file__).parent.parent.parent / ".env"
    load_dotenv(env_path)
except ImportError:
    pass  # dotenv not installed, rely on environment variables

from .database import (
    get_signals,
    get_companies,
    CompanySignal,
    WatchedCompany,
    get_industry_signal_summary,
    INDUSTRY_CATEGORIES,
)

logger = logging.getLogger(__name__)

# =============================================================================
# CONFIGURATION
# =============================================================================

# Quality news sources (higher trust, boost ranking)
QUALITY_SOURCES = [
    'techcrunch', 'bloomberg', 'forbes', 'reuters', 'wsj', 'venturebeat',
    'theverge', 'wired', 'cnbc', 'businessinsider', 'ft.com', 'nytimes',
    'axios', 'theinformation', 'semafor', 'crunchbase', 'pitchbook'
]

# Signal types that are most digest-worthy
DIGEST_SIGNAL_TYPES = ['funding', 'acquisition', 'executive_change', 'product_launch', 'partnership']

# Noise patterns to filter out
NOISE_PATTERNS = [
    r'wikipedia\.org',
    r'list of.*companies',
    r'press release',
    r'blog\s*\|',
    r'product updates',
    r'\d+ fintech trends',
    r'unicorn.*list',
    r'best practices',
    r'how to',
]

# Digest configuration
DEFAULT_FEATURED_COUNT = 3
DEFAULT_SUMMARY_COUNT = 8
DEFAULT_DAYS = 7


# =============================================================================
# DATA MODELS
# =============================================================================

@dataclass
class DigestArticle:
    """An article prepared for the digest."""
    signal: CompanySignal
    company: Optional[WatchedCompany]
    rank_score: float = 0.0
    is_quality_source: bool = False
    event_key: str = ""
    formatted_headline: str = ""
    formatted_summary: str = ""

    @property
    def company_name(self) -> str:
        return self.company.company_name if self.company else "Unknown"

    @property
    def company_category(self) -> str:
        return self.company.category if self.company else "unknown"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "headline": self.signal.headline,
            "company": self.company_name,
            "category": self.company_category,
            "signal_type": self.signal.signal_type,
            "source": self.signal.source_name,
            "url": self.signal.source_url,
            "published_date": self.signal.published_date,
            "relevance_score": self.signal.relevance_score,
            "rank_score": self.rank_score,
            "sentiment": self.signal.sentiment,
            "synopsis": self.signal.synopsis,
        }


@dataclass
class WeeklyDigest:
    """The complete weekly digest."""
    start_date: str
    end_date: str
    featured_articles: List[DigestArticle] = field(default_factory=list)
    summary_articles: List[DigestArticle] = field(default_factory=list)
    industry_highlights: Dict[str, Any] = field(default_factory=dict)
    stats: Dict[str, Any] = field(default_factory=dict)
    generated_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())

    def to_dict(self) -> Dict[str, Any]:
        return {
            "start_date": self.start_date,
            "end_date": self.end_date,
            "featured_articles": [a.to_dict() for a in self.featured_articles],
            "summary_articles": [a.to_dict() for a in self.summary_articles],
            "industry_highlights": self.industry_highlights,
            "stats": self.stats,
            "generated_at": self.generated_at,
        }

    def to_markdown(self) -> str:
        """Generate markdown version of the digest."""
        lines = []

        # Header
        lines.append(f"# Weekly Signal Digest")
        lines.append(f"**{self.start_date} to {self.end_date}**\n")

        # Stats summary
        if self.stats:
            lines.append("## Overview")
            lines.append(f"- **Total Signals:** {self.stats.get('total_signals', 0)}")
            lines.append(f"- **Companies Covered:** {self.stats.get('companies_covered', 0)}")
            lines.append(f"- **Portfolio Signals:** {self.stats.get('portfolio_signals', 0)}")
            lines.append(f"- **Competitor Signals:** {self.stats.get('competitor_signals', 0)}")
            lines.append("")

        # Featured articles
        if self.featured_articles:
            lines.append("## Featured Stories\n")
            for i, article in enumerate(self.featured_articles, 1):
                lines.append(f"### {i}. {article.signal.headline}")
                lines.append(f"**{article.company_name}** ({article.company_category}) | {article.signal.signal_type}")

                if article.formatted_summary:
                    lines.append(f"\n{article.formatted_summary}")
                elif article.signal.synopsis:
                    lines.append(f"\n{article.signal.synopsis}")
                elif article.signal.description:
                    lines.append(f"\n{article.signal.description[:200]}...")

                if article.signal.source_url:
                    source_name = article.signal.source_name or "Source"
                    lines.append(f"\n[{source_name}]({article.signal.source_url})")

                if article.signal.sentiment:
                    sentiment_icon = {"positive": "📈", "negative": "📉", "neutral": "➖"}.get(article.signal.sentiment, "")
                    lines.append(f"\nSentiment: {sentiment_icon} {article.signal.sentiment}")

                lines.append("")

        # Summary articles
        if self.summary_articles:
            lines.append("## More Headlines\n")
            for article in self.summary_articles:
                icon = self._get_signal_icon(article.signal.signal_type)
                headline = article.signal.headline[:60]
                if len(article.signal.headline) > 60:
                    headline += "..."
                lines.append(f"- {icon} **{article.company_name}**: {headline}")

                if article.signal.source_url:
                    lines.append(f"  [{article.signal.source_name or 'Link'}]({article.signal.source_url})")

            lines.append("")

        # Industry highlights
        if self.industry_highlights:
            lines.append("## Industry Trends\n")
            for industry, data in self.industry_highlights.items():
                if data.get("total_signals", 0) > 0:
                    lines.append(f"- **{industry.replace('_', ' ').title()}**: {data['total_signals']} signals from {data['company_count']} companies")
            lines.append("")

        # Footer
        lines.append("---")
        lines.append(f"*Generated: {self.generated_at[:10]}*")

        return "\n".join(lines)

    def _get_signal_icon(self, signal_type: str) -> str:
        icons = {
            'funding': '💰',
            'acquisition': '🤝',
            'executive_change': '👤',
            'team_change': '👥',
            'product_launch': '🚀',
            'partnership': '🔗',
            'hiring_expansion': '📈',
        }
        return icons.get(signal_type, '📌')


# =============================================================================
# HELPER FUNCTIONS
# =============================================================================

def _is_noise(headline: str, url: str) -> bool:
    """Check if a signal is noise based on patterns."""
    text = f"{headline} {url}".lower()
    for pattern in NOISE_PATTERNS:
        if re.search(pattern, text, re.IGNORECASE):
            return True
    return False


def _is_quality_source(source: str, url: str) -> bool:
    """Check if source is from a quality outlet."""
    text = f"{source} {url}".lower()
    return any(qs in text for qs in QUALITY_SOURCES)


def _extract_event_key(headline: str, company_name: str) -> str:
    """Extract a normalized key for deduplication."""
    h = headline.lower()
    h = h.replace(company_name.lower(), "").strip()

    # Extract funding amounts
    amount_match = re.search(r'\$[\d.]+\s*[bmk](?:illion)?', h)
    if amount_match:
        amt = amount_match.group().replace(' ', '').lower()
        return f"funding_{amt}"

    # Extract acquisition targets
    acq_match = re.search(r'acqui\w*\s+(\w+)', h)
    if acq_match:
        return f"acquisition_{acq_match.group(1)}"

    # Series round
    series_match = re.search(r'series\s+[a-k]', h)
    if series_match:
        return f"series_{series_match.group()}"

    # Fallback
    words = [w for w in h.split() if len(w) > 3][:3]
    return "_".join(words) if words else h[:20]


def _calculate_rank_score(signal: CompanySignal, company: WatchedCompany, is_quality: bool) -> float:
    """
    Calculate ranking score for digest ordering.

    Factors:
    - Base relevance score (0-100)
    - Quality source bonus (+20)
    - Portfolio company bonus (+15)
    - Recency bonus (up to +10)
    - Sentiment alignment (+5 for positive)
    """
    score = float(signal.relevance_score or 0)

    # Quality source bonus
    if is_quality:
        score += 20

    # Portfolio company bonus
    if company and company.category == "portfolio":
        score += 15

    # Recency bonus (newer = better)
    if signal.published_date:
        try:
            pub_date = datetime.fromisoformat(signal.published_date.replace('Z', '+00:00'))
            days_ago = (datetime.utcnow() - pub_date.replace(tzinfo=None)).days
            recency_bonus = max(0, 10 - days_ago)
            score += recency_bonus
        except (ValueError, TypeError):
            pass

    # Positive sentiment bonus
    if signal.sentiment == "positive":
        score += 5

    return score


def _summarize_article_with_llm(article: DigestArticle) -> str:
    """Use LLM to generate a concise summary for digest."""
    try:
        from langchain_anthropic import ChatAnthropic
        from langchain_core.messages import SystemMessage, HumanMessage

        system_prompt = """You are a VC research assistant creating a weekly news digest.
Write a 1-2 sentence summary of this news article for busy investors.
Focus on: what happened, why it matters, and any key numbers.
Be concise and factual."""

        content = article.signal.synopsis or article.signal.description or article.signal.headline
        user_prompt = f"""Summarize this news about {article.company_name}:

Headline: {article.signal.headline}
Type: {article.signal.signal_type}
Content: {content}

Write a 1-2 sentence summary:"""

        llm = ChatAnthropic(model="claude-haiku-4-5-20251001", temperature=0, max_tokens=300)
        messages = [
            SystemMessage(content=system_prompt),
            HumanMessage(content=user_prompt),
        ]
        response = llm.invoke(messages)
        return response.content.strip()

    except Exception as e:
        logger.warning(f"LLM summarization failed: {e}")
        return article.signal.synopsis or article.signal.description or article.signal.headline


# =============================================================================
# MAIN DIGEST GENERATOR
# =============================================================================

def generate_weekly_digest(
    days: int = DEFAULT_DAYS,
    featured_count: int = DEFAULT_FEATURED_COUNT,
    summary_count: int = DEFAULT_SUMMARY_COUNT,
    investor_id: str = None,
    include_industry_highlights: bool = True,
    use_llm_summaries: bool = False,
) -> WeeklyDigest:
    """
    Generate a weekly digest of company signals.

    Args:
        days: Number of days to look back (default 7)
        featured_count: Number of featured articles (default 3)
        summary_count: Number of summary articles (default 8)
        investor_id: Filter to specific investor's companies
        include_industry_highlights: Include industry trend summaries
        use_llm_summaries: Use LLM to enhance article summaries

    Returns:
        WeeklyDigest with featured and summary articles
    """
    end_date = datetime.utcnow()
    start_date = end_date - timedelta(days=days)
    cutoff_date = start_date.strftime("%Y-%m-%d")

    # Fetch signals
    all_signals = get_signals(investor_id=investor_id, limit=500)
    companies = {c.id: c for c in get_companies(active_only=False)}

    # Filter and process signals
    articles: List[DigestArticle] = []
    seen_events: Dict[str, DigestArticle] = {}  # For deduplication

    for signal in all_signals:
        # Skip old signals
        if signal.published_date and signal.published_date < cutoff_date:
            continue
        if signal.detected_at and signal.detected_at < cutoff_date:
            continue

        # Skip non-digest signal types
        if signal.signal_type not in DIGEST_SIGNAL_TYPES:
            continue

        # Skip noise
        if _is_noise(signal.headline, signal.source_url or ""):
            continue

        company = companies.get(signal.company_id)
        is_quality = _is_quality_source(signal.source_name or "", signal.source_url or "")
        event_key = _extract_event_key(signal.headline, company.company_name if company else "")

        # Create article
        article = DigestArticle(
            signal=signal,
            company=company,
            is_quality_source=is_quality,
            event_key=event_key,
            rank_score=_calculate_rank_score(signal, company, is_quality),
        )

        # Deduplicate - keep higher-ranked version
        if event_key in seen_events:
            if article.rank_score > seen_events[event_key].rank_score:
                seen_events[event_key] = article
        else:
            seen_events[event_key] = article

    articles = list(seen_events.values())

    # Sort by rank score
    articles.sort(key=lambda a: a.rank_score, reverse=True)

    # Split into featured and summary
    featured = articles[:featured_count]
    summary = articles[featured_count:featured_count + summary_count]

    # Optionally enhance with LLM summaries
    if use_llm_summaries:
        for article in featured:
            article.formatted_summary = _summarize_article_with_llm(article)

    # Calculate stats
    portfolio_signals = sum(1 for a in articles if a.company_category == "portfolio")
    competitor_signals = sum(1 for a in articles if a.company_category == "competitor")
    companies_covered = len(set(a.signal.company_id for a in articles))

    stats = {
        "total_signals": len(articles),
        "companies_covered": companies_covered,
        "portfolio_signals": portfolio_signals,
        "competitor_signals": competitor_signals,
        "featured_count": len(featured),
        "summary_count": len(summary),
    }

    # Industry highlights
    industry_highlights = {}
    if include_industry_highlights:
        for industry in list(INDUSTRY_CATEGORIES.keys())[:5]:  # Top 5 industries
            try:
                summary_data = get_industry_signal_summary(industry, days=days)
                if summary_data.get("total_signals", 0) > 0:
                    industry_highlights[industry] = {
                        "total_signals": summary_data["total_signals"],
                        "company_count": summary_data["company_count"],
                        "top_types": dict(list(summary_data["signal_counts"].items())[:3]),
                    }
            except Exception as e:
                logger.warning(f"Failed to get industry summary for {industry}: {e}")

    digest = WeeklyDigest(
        start_date=start_date.strftime("%Y-%m-%d"),
        end_date=end_date.strftime("%Y-%m-%d"),
        featured_articles=featured,
        summary_articles=summary,
        industry_highlights=industry_highlights,
        stats=stats,
    )

    logger.info(
        f"Generated digest: {len(featured)} featured, {len(summary)} summary "
        f"from {len(articles)} total articles"
    )

    return digest


def generate_digest_for_investor(investor_id: str, **kwargs) -> WeeklyDigest:
    """Generate a digest for a specific investor's portfolio."""
    return generate_weekly_digest(investor_id=investor_id, **kwargs)


def get_digest_as_json(digest: WeeklyDigest) -> str:
    """Export digest as JSON string."""
    return json.dumps(digest.to_dict(), indent=2)


def get_digest_as_markdown(digest: WeeklyDigest) -> str:
    """Export digest as markdown string."""
    return digest.to_markdown()

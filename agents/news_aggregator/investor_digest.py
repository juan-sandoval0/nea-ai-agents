"""
Unified Investor Digest Pipeline
=================================

Single source of truth for news aggregation with:
- Story-level deduplication (merge multiple URLs about same event)
- Engagement-based primary URL selection (HN > PH > TechCrunch > other)
- Hybrid classification (fast rules + embedding similarity) with confidence
- Deterministic sentiment scoring with evidence keywords
- Template-based synopsis generation (no full article text required)
- Dynamic selection (no hard-coded top N)
- 7-day investor-grade markdown digest

Re-engineered for reduced LLM runtime:
- Uses only title + snippet (no full article body)
- Embeddings cached by URL hash to prevent duplicate computation
- LLM calls limited to 1 per unique story (or fewer if confidence is high)
- Industry Trends section with de-duplicated industries

Usage:
    from agents.news_aggregator.investor_digest import generate_investor_digest

    digest = generate_investor_digest()
    print(digest.to_markdown())
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional, List, Dict, Any, Tuple, Set
from urllib.parse import urlparse, parse_qs, urlencode, urlunparse

# Load environment variables
try:
    from dotenv import load_dotenv
    env_path = Path(__file__).parent.parent.parent / ".env"
    load_dotenv(env_path)
except ImportError:
    pass

from .database import (
    get_signals, get_companies, get_portfolio_companies,
    get_competitors_for_company, CompanySignal, WatchedCompany,
    get_company_by_id, INDUSTRY_CATEGORIES,
    get_companies_by_industry, CachedStory, save_stories_batch,
)
from services.history import get_digest_history, get_audit_log

logger = logging.getLogger(__name__)

# =============================================================================
# CONFIGURATION
# =============================================================================

# Source priority (higher = more trusted/preferred)
SOURCE_PRIORITY = {
    'producthunt.com': 100,
    'news.ycombinator.com': 95,
    'techcrunch.com': 90,
    'bloomberg.com': 88,
    'reuters.com': 85,
    'wsj.com': 85,
    'ft.com': 85,
    'theinformation.com': 82,
    'forbes.com': 75,
    'venturebeat.com': 75,
    'axios.com': 75,
    'cnbc.com': 70,
    'businessinsider.com': 65,
    'wired.com': 60,
    'theverge.com': 60,
    'crunchbase.com': 55,
    'pitchbook.com': 55,
}

# Industry search configuration (to limit API calls)
INDUSTRY_SEARCH_CONFIG = {
    'max_industries': 5,          # Max industries to search (increased for better coverage)
    'max_results_per_industry': 8,  # Max results per industry search
    'min_priority_score': 45.0,   # Min score to include industry stories
    'industry_priority_boost': -10,  # Score adjustment for non-tracked companies
    'max_stories_per_industry': 5,  # Max stories shown per industry in digest
}

# Synopsis generation configuration
SYNOPSIS_CONFIG = {
    'max_synopsis_length': 400,
    'use_llm': True,  # LLM generates both synopsis AND type classification
}

# Classification rules (order matters - first match wins)
CLASSIFICATION_RULES = [
    # FUNDING - most specific first
    ('FUNDING', [
        r'series\s+[a-k]', r'seed\s+round', r'raises?\s+\$', r'funding\s+round',
        r'raised\s+\$', r'\$\d+[mb]\s+(?:round|funding|raise)', r'valuation',
        r'unicorn', r'decacorn', r'pre-?seed', r'venture\s+capital',
        r'investment\s+round', r'led\s+by.*capital', r'growth\s+equity',
    ]),
    # M&A
    ('M&A', [
        r'acqui(?:res?|red|sition)', r'merger', r'buyout', r'takeover',
        r'purchased\s+by', r'bought\s+by', r'deal\s+to\s+buy', r'sold\s+to',
    ]),
    # IPO / PUBLIC
    ('IPO', [
        r'\bipo\b', r'going\s+public', r'files?\s+(?:for\s+)?s-?1', r'public\s+offering',
        r'nasdaq', r'nyse\s+listing', r'direct\s+listing', r'spac',
    ]),
    # SECURITY / OUTAGE
    ('SECURITY', [
        r'breach', r'hack(?:ed|ing)?', r'vulnerability', r'exploit', r'ransomware',
        r'outage', r'down(?:time)?', r'incident', r'data\s+leak', r'compromised',
        r'security\s+flaw', r'cyber\s*attack',
    ]),
    # LEGAL / REGULATORY
    ('LEGAL', [
        r'lawsuit', r'sued', r'litigation', r'antitrust', r'ftc\s+investigation',
        r'sec\s+(?:probe|investigation|charges)', r'doj', r'regulatory', r'compliance',
        r'settlement', r'fine(?:d|s)?', r'penalty', r'class\s+action',
    ]),
    # LAYOFFS
    ('LAYOFFS', [
        r'layoff', r'laid\s+off', r'workforce\s+reduction', r'cut(?:ting)?\s+\d+%?\s+(?:staff|jobs|employees)',
        r'downsiz', r'restructur', r'headcount\s+reduction',
    ]),
    # HIRING / EXPANSION
    ('HIRING', [
        r'hiring\s+spree', r'(?:plans?\s+to\s+)?hir(?:e|ing)\s+\d+', r'headcount\s+growth',
        r'expanding\s+team', r'new\s+(?:ceo|cto|cfo|coo)', r'appoints?\s+(?:new\s+)?(?:ceo|cto|cfo)',
        r'names?\s+(?:new\s+)?(?:ceo|cto|cfo)', r'executive\s+hire',
    ]),
    # PARTNERSHIP
    ('PARTNERSHIP', [
        r'partner(?:ship|s|ed|ing)', r'collaborat', r'alliance', r'integrat(?:es?|ion|ing)',
        r'teams?\s+up', r'joint\s+venture', r'strategic\s+(?:deal|agreement)',
    ]),
    # PRODUCT UPDATE
    ('PRODUCT', [
        r'launch(?:es|ed|ing)?', r'announces?\s+(?:new|its)', r'introduces?', r'unveils?',
        r'releases?', r'rolls?\s+out', r'debuts?', r'ships?', r'beta', r'ga\s+release',
        r'new\s+feature', r'product\s+update', r'version\s+\d',
    ]),
    # EARNINGS / METRICS
    ('EARNINGS', [
        r'revenue', r'earnings', r'profit(?:able|ability)?', r'arr\b', r'mrr\b',
        r'quarterly\s+results', r'fiscal\s+(?:q\d|year)', r'guidance', r'ebitda',
        r'gross\s+margin', r'growth\s+rate', r'yoy', r'year-over-year',
    ]),
    # CUSTOMER / GTM
    ('CUSTOMER', [
        r'customer\s+(?:win|loss)', r'signed?\s+(?:deal|contract)', r'enterprise\s+deal',
        r'lands?\s+(?:deal|contract)', r'expands?\s+(?:to|into)', r'enters?\s+(?:market|sector)',
        r'go-to-market', r'gtm', r'sales\s+milestone',
    ]),
    # MARKET / MACRO (catch-all for industry news)
    ('MARKET', [
        r'industry\s+(?:trend|report|analysis)', r'market\s+(?:report|analysis|outlook)',
        r'sector\s+(?:report|analysis)', r'macro', r'economic', r'regulation',
    ]),
]

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
    'expansion': 3,
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
    'funding': 3,
    'backed': 2,
    'valuation': 2,
    'wins': 3,
    'launch': 2,

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
    'outage': -3,
    'downtime': -3,
    'vulnerable': -3,
    # Legal exposure
    'charged': -5,
    'indicted': -5,
    'lawsuit': -4,
    'sued': -4,
    'regulatory probe': -4,
    'scandal': -4,
    # Major contraction
    'layoffs': -4,
    'layoff': -4,
    'laid off': -4,
    'cuts workforce': -4,
    'shutdown': -4,
    'crash': -4,
    'plunges': -4,
    'plunge': -4,
    'misses estimates': -4,
    'revenue decline': -4,
    'guidance cut': -4,
    'down round': -4,
    'valuation cut': -4,
    # Restructuring
    'restructuring': -3,
    'investigation': -3,
    'closes': -3,
    'struggles': -3,
    'decline': -3,
    'fired': -3,
    'exodus': -3,
    'downturn': -3,
    'losses': -3,

    # ==========================================================================
    # MODERATE NEGATIVE (-1 to -3) - Concerning but not terminal
    # ==========================================================================
    'leadership departure': -3,
    'ceo steps down': -3,
    'customer churn': -3,
    'delays': -2,
    'delayed': -2,
    'warning': -2,
    'decline': -2,
    'slows': -2,
    'headwinds': -2,
    'competition intensifies': -2,
    'cash burn': -2,
    'debt': -2,
    'cuts': -2,
    'concern': -1,
    'risk': -1,
}

# Noise patterns to filter
NOISE_PATTERNS = [
    r'wikipedia\.org', r'list\s+of.*companies', r'press\s+release\s+only',
    r'blog\s*\|', r'unicorn.*list', r'best\s+practices', r'how\s+to\s+',
    r'techcrunch\.com/tag/', r'linkedin\.com/pulse', r'webinar', r'podcast\s+episode',
]

# Homepage/non-article URL patterns to filter
HOMEPAGE_PATTERNS = [
    r'^https?://[^/]+/?$',  # Just domain with optional trailing slash
    r'^https?://[^/]+/(?:category|tag|topic|author|page)/[^/]*/?$',  # Category/tag pages
    r'^https?://[^/]+/(?:ai|tech|business|news|blog)/?$',  # Generic section pages
    r'^https?://[^/]+/[^/]{1,15}/?$',  # Very short paths (likely not articles)
]

# Non-article URL patterns (company pages, profiles, newsrooms, etc.)
NON_ARTICLE_PATTERNS = [
    r'/news/?$',  # Company newsroom landing pages
    r'/newsroom/?$',
    r'/press/?$',
    r'/press-releases/?$',
    r'/media/?$',
    r'/about/?$',
    r'/company/?$',
    r'/profile/?$',
    r'/insights/?$',  # Law firm/consulting insights landing
    r'/blog/?$',
    r'crunchbase\.com/organization/',  # Crunchbase company profiles
    r'linkedin\.com/company/',  # LinkedIn company pages
    r'pitchbook\.com/profiles/',  # PitchBook profiles
    r'wikipedia\.org/',
    r'/careers/?$',
    r'/jobs/?$',
    r'/contact/?$',
    r'/team/?$',
    r'/investors/?$',
    r'/ir/?$',  # Investor relations
    r'finance\.yahoo\.com/quote/',  # Stock quote pages (not articles)
    r'bloomberg\.com/quote/',
    r'/funding-rounds/?$',
    r'/company-profile',
]

# Title similarity threshold for clustering
TITLE_SIMILARITY_THRESHOLD = 0.6

# =============================================================================
# DATA MODELS
# =============================================================================

@dataclass
class ArticleRef:
    """A single article/URL reference (raw, before clustering)."""
    url: str
    title: str
    source_domain: str
    published_date: Optional[str] = None
    snippet: str = ""
    engagement_score: int = 0  # From HN/PH if available
    company_id: str = ""
    company_name: str = ""
    company_category: str = ""  # portfolio, competitor
    parent_company_name: Optional[str] = None  # For competitors
    industry_tags: List[str] = field(default_factory=list)  # Industry tags from Harmonic
    signal_id: str = ""  # Original signal ID for caching

    @property
    def source_priority(self) -> int:
        """Get source priority score."""
        domain = self.source_domain.lower()
        for key, priority in SOURCE_PRIORITY.items():
            if key in domain:
                return priority
        return 30  # Default for unknown sources

    @property
    def normalized_url(self) -> str:
        """Normalize URL by removing tracking params."""
        return normalize_url(self.url)


@dataclass
class SentimentResult:
    """Deterministic sentiment analysis result."""
    label: str  # Positive, Negative, Neutral, Mixed
    score: int  # -5 to +5
    keywords_hit: List[str] = field(default_factory=list)

    def __str__(self) -> str:
        icon = {'Positive': '📈', 'Negative': '📉', 'Neutral': '➖', 'Mixed': '⚖️'}.get(self.label, '➖')
        kw_str = ', '.join(self.keywords_hit[:3]) if self.keywords_hit else 'none'
        return f"{icon} {self.label} ({self.score:+d}) [{kw_str}]"


@dataclass
class Story:
    """A unique story (merged from multiple ArticleRefs)."""
    story_id: str  # Hash-based ID for caching
    primary_url: str
    primary_title: str
    other_urls: List[Dict[str, str]] = field(default_factory=list)  # [{url, source}, ...]
    articles: List[ArticleRef] = field(default_factory=list)

    # Derived fields (computed once)
    classification: str = "GENERAL"
    sentiment: SentimentResult = field(default_factory=lambda: SentimentResult('Neutral', 0))
    synopsis: str = ""

    # Company context
    company_id: str = ""
    company_name: str = ""
    company_category: str = ""
    parent_company_name: Optional[str] = None
    industry_tags: List[str] = field(default_factory=list)

    # Scoring
    priority_score: float = 0.0
    priority_reasons: List[str] = field(default_factory=list)

    # Metadata
    published_date: Optional[str] = None
    max_engagement: int = 0
    source_count: int = 0

    def compute_story_id(self) -> str:
        """Generate deterministic story ID for caching.

        Uses event-based key (company + classification + funding amount + week)
        rather than URL-based key. This ensures multiple articles about the
        same event (e.g., "ElevenLabs $500M Series D") get the same story_id.
        """
        # Extract funding amount if present (for funding stories)
        funding_amount = extract_funding_amount(self.primary_title) or ""

        # Get week bucket (YYYY-WW) for time grouping
        week_bucket = ""
        if self.published_date:
            try:
                pub_date = datetime.fromisoformat(
                    self.published_date.replace('Z', '+00:00')
                )
                week_bucket = pub_date.strftime("%Y-W%W")
            except (ValueError, TypeError):
                week_bucket = self.published_date[:7] if self.published_date else ""

        # Event-based key: company + classification + funding_amount + week
        # This groups all articles about the same event into one story
        key_parts = [
            self.company_id or self.company_name.lower(),
            self.classification,
            funding_amount,
            week_bucket,
        ]
        key = '|'.join(key_parts)
        return hashlib.md5(key.encode()).hexdigest()[:12]


@dataclass
class StoryStore:
    """Canonical store for unique stories with indices."""
    stories: List[Story] = field(default_factory=list)

    # Indices for fast lookup
    by_company: Dict[str, List[Story]] = field(default_factory=dict)
    by_classification: Dict[str, List[Story]] = field(default_factory=dict)
    by_industry: Dict[str, List[Story]] = field(default_factory=dict)

    def add_story(self, story: Story):
        """Add story and update indices."""
        self.stories.append(story)

        # Update company index
        if story.company_id:
            if story.company_id not in self.by_company:
                self.by_company[story.company_id] = []
            self.by_company[story.company_id].append(story)

        # Update classification index
        if story.classification not in self.by_classification:
            self.by_classification[story.classification] = []
        self.by_classification[story.classification].append(story)

        # Update industry index
        for tag in story.industry_tags:
            if tag not in self.by_industry:
                self.by_industry[tag] = []
            self.by_industry[tag].append(story)

    def get_portfolio_stories(self) -> List[Story]:
        """Get stories for portfolio companies."""
        return [s for s in self.stories if s.company_category == 'portfolio']

    def get_competitor_stories(self) -> List[Story]:
        """Get stories for competitor companies."""
        return [s for s in self.stories if s.company_category == 'competitor']

    def get_industry_stories(self) -> List[Story]:
        """Get stories from industry-wide search (not tracked companies)."""
        return [s for s in self.stories if s.company_category == 'industry']

    def get_stories_by_industry(self, industry: str) -> List[Story]:
        """Get stories for a specific industry."""
        return self.by_industry.get(industry, [])

    def get_industry_summary(self) -> Dict[str, Dict[str, Any]]:
        """Get summary stats by industry."""
        summary = {}
        for industry, stories in self.by_industry.items():
            summary[industry] = {
                'story_count': len(stories),
                'company_count': len(set(s.company_id for s in stories)),
                'classifications': {},
            }
            for story in stories:
                cls = story.classification
                summary[industry]['classifications'][cls] = \
                    summary[industry]['classifications'].get(cls, 0) + 1
        return summary


@dataclass
class PipelineTimingStats:
    """Timing statistics for the digest pipeline."""
    fetch_time_ms: int = 0
    embedding_time_ms: int = 0
    classification_time_ms: int = 0
    synopsis_time_ms: int = 0
    llm_calls: int = 0
    total_time_ms: int = 0

    def to_dict(self) -> Dict:
        return {
            'fetch_time_ms': self.fetch_time_ms,
            'embedding_time_ms': self.embedding_time_ms,
            'classification_time_ms': self.classification_time_ms,
            'synopsis_time_ms': self.synopsis_time_ms,
            'llm_calls': self.llm_calls,
            'total_time_ms': self.total_time_ms,
        }


@dataclass
class InvestorDigest:
    """The final digest output."""
    start_date: str
    end_date: str
    store: StoryStore
    generated_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    # Stats
    total_stories: int = 0
    total_articles: int = 0
    companies_covered: int = 0

    # Industry filter (if applied)
    industry_filter: Optional[str] = None

    # Timing stats
    timing: PipelineTimingStats = field(default_factory=PipelineTimingStats)

    def to_markdown(self) -> str:
        """Render digest as investor-grade markdown."""
        return render_digest_markdown(self)

    def get_industry_summary(self) -> Dict[str, Dict[str, Any]]:
        """Get industry summary from store."""
        return self.store.get_industry_summary()


# =============================================================================
# URL NORMALIZATION
# =============================================================================

def normalize_url(url: str) -> str:
    """Normalize URL by removing tracking params and canonicalizing."""
    if not url:
        return ""

    try:
        parsed = urlparse(url)

        # Remove common tracking params
        tracking_params = {
            'utm_source', 'utm_medium', 'utm_campaign', 'utm_content', 'utm_term',
            'ref', 'source', 'fbclid', 'gclid', 'mc_cid', 'mc_eid',
        }

        if parsed.query:
            params = parse_qs(parsed.query, keep_blank_values=True)
            filtered = {k: v for k, v in params.items() if k.lower() not in tracking_params}
            new_query = urlencode(filtered, doseq=True) if filtered else ''
        else:
            new_query = ''

        # Rebuild URL without tracking
        normalized = urlunparse((
            parsed.scheme.lower(),
            parsed.netloc.lower().replace('www.', ''),
            parsed.path.rstrip('/'),
            parsed.params,
            new_query,
            '',  # Remove fragment
        ))

        return normalized
    except Exception:
        return url.lower()


def extract_domain(url: str) -> str:
    """Extract clean domain from URL."""
    try:
        parsed = urlparse(url)
        domain = parsed.netloc.lower().replace('www.', '')
        return domain
    except Exception:
        return ""


# =============================================================================
# STORY CLUSTERING
# =============================================================================

def title_similarity(title1: str, title2: str) -> float:
    """Calculate Jaccard similarity between titles."""
    if not title1 or not title2:
        return 0.0

    # Tokenize and normalize
    def tokenize(text: str) -> set:
        # Remove punctuation and lowercase
        text = re.sub(r'[^\w\s]', ' ', text.lower())
        # Keep words with 3+ chars
        return {w for w in text.split() if len(w) >= 3}

    tokens1 = tokenize(title1)
    tokens2 = tokenize(title2)

    if not tokens1 or not tokens2:
        return 0.0

    intersection = len(tokens1 & tokens2)
    union = len(tokens1 | tokens2)

    return intersection / union if union > 0 else 0.0


def extract_funding_amount(text: str) -> Optional[str]:
    """Extract normalized funding amount from text (e.g., '$500M', '$11B')."""
    # Match patterns like $500M, $11B, $500 million, $11 billion
    pattern = r'\$(\d+(?:\.\d+)?)\s*([BMK]|billion|million|thousand)?'
    match = re.search(pattern, text, re.IGNORECASE)
    if match:
        amount = match.group(1)
        unit = (match.group(2) or 'M').upper()[0]
        return f"${amount}{unit}"
    return None


def should_cluster(article1: ArticleRef, article2: ArticleRef) -> bool:
    """Determine if two articles should be clustered as same story."""
    # Same normalized URL
    if article1.normalized_url == article2.normalized_url:
        return True

    # Different companies = different stories
    if article1.company_id != article2.company_id:
        return False

    # Funding amount match: if same company mentions same dollar amount, likely same event
    amount1 = extract_funding_amount(article1.title)
    amount2 = extract_funding_amount(article2.title)
    if amount1 and amount2 and amount1 == amount2:
        return True

    # High title similarity + time proximity
    title_sim = title_similarity(article1.title, article2.title)
    if title_sim >= TITLE_SIMILARITY_THRESHOLD:
        # Check date proximity (within 3 days)
        if article1.published_date and article2.published_date:
            try:
                d1 = datetime.fromisoformat(article1.published_date.replace('Z', '+00:00'))
                d2 = datetime.fromisoformat(article2.published_date.replace('Z', '+00:00'))
                if abs((d1 - d2).days) <= 3:
                    return True
            except (ValueError, TypeError):
                # If dates can't be parsed, still cluster on title similarity
                return True
        else:
            return True

    return False


def cluster_articles(articles: List[ArticleRef]) -> List[List[ArticleRef]]:
    """Cluster articles into story groups."""
    if not articles:
        return []

    clusters: List[List[ArticleRef]] = []
    used = set()

    for i, article in enumerate(articles):
        if i in used:
            continue

        # Start new cluster
        cluster = [article]
        used.add(i)

        # Find all matching articles
        for j, other in enumerate(articles):
            if j in used:
                continue
            if should_cluster(article, other):
                cluster.append(other)
                used.add(j)

        clusters.append(cluster)

    return clusters


def select_primary_article(articles: List[ArticleRef]) -> Tuple[ArticleRef, List[Dict[str, str]]]:
    """Select primary article from cluster based on engagement + source priority.

    Returns:
        Tuple of (primary_article, other_sources) where other_sources is a list of
        {"url": "...", "source": "TechCrunch"} dicts for display in the UI.
    """
    if not articles:
        raise ValueError("Cannot select from empty list")

    if len(articles) == 1:
        return articles[0], []

    # Score each article: engagement + source priority + recency
    def score_article(a: ArticleRef) -> float:
        score = 0.0

        # Engagement (0-200 range, capped)
        score += min(a.engagement_score, 200)

        # Source priority (0-100)
        score += a.source_priority

        # Recency bonus (0-30)
        if a.published_date:
            try:
                pub = datetime.fromisoformat(a.published_date.replace('Z', '+00:00'))
                days_old = (datetime.now(timezone.utc) - pub).days
                score += max(0, 30 - days_old)
            except (ValueError, TypeError):
                pass

        return score

    scored = [(score_article(a), a) for a in articles]
    scored.sort(key=lambda x: x[0], reverse=True)

    primary = scored[0][1]
    # Include source name with each URL for UI display
    other_sources = [
        {"url": a.url, "source": _format_source_name(a.source_domain)}
        for _, a in scored[1:]
        if a.url and a.url != primary.url
    ]

    return primary, other_sources


def _format_source_name(domain: str) -> str:
    """Format domain into readable source name (e.g., 'techcrunch.com' -> 'TechCrunch')."""
    if not domain:
        return "News"

    # Known source name mappings
    source_names = {
        'techcrunch.com': 'TechCrunch',
        'bloomberg.com': 'Bloomberg',
        'reuters.com': 'Reuters',
        'wsj.com': 'Wall Street Journal',
        'ft.com': 'Financial Times',
        'forbes.com': 'Forbes',
        'cnbc.com': 'CNBC',
        'theverge.com': 'The Verge',
        'wired.com': 'Wired',
        'venturebeat.com': 'VentureBeat',
        'axios.com': 'Axios',
        'theinformation.com': 'The Information',
        'businessinsider.com': 'Business Insider',
        'nytimes.com': 'NY Times',
        'news.ycombinator.com': 'Hacker News',
        'producthunt.com': 'Product Hunt',
        'crunchbase.com': 'Crunchbase',
        'pitchbook.com': 'PitchBook',
        'semafor.com': 'Semafor',
        'news.google.com': 'Google News',
    }

    domain_lower = domain.lower().replace('www.', '')

    # Check for known sources
    for key, name in source_names.items():
        if key in domain_lower:
            return name

    # Fallback: capitalize the domain name
    # e.g., "example.com" -> "Example"
    name = domain_lower.split('.')[0]
    return name.title() if name else "News"


# =============================================================================
# CLASSIFICATION (LLM-based)
# =============================================================================

# Valid classification types for LLM
VALID_TYPES = [
    'FUNDING', 'M&A', 'IPO', 'SECURITY', 'LEGAL', 'LAYOFFS', 'HIRING',
    'PARTNERSHIP', 'PRODUCT', 'EARNINGS', 'CUSTOMER', 'MARKET', 'GENERAL'
]


def classify_and_summarize_story(
    articles: List[ArticleRef],
    company_name: str,
    llm_call_count: Dict[str, int] = None
) -> Tuple[str, str, str]:
    """
    Use LLM to classify story type, generate headline, AND generate synopsis in a single call.

    Returns (classification, synopsis, headline)
    """
    if not articles:
        return 'GENERAL', '', ''

    if llm_call_count is None:
        llm_call_count = {'count': 0}

    # Gather article data
    titles = [a.title for a in articles[:5]]
    snippets = [a.snippet for a in articles[:5] if a.snippet]
    sources = [a.source_domain for a in articles[:5]]

    # Try LLM classification + synopsis + headline
    if SYNOPSIS_CONFIG['use_llm'] and os.getenv("OPENAI_API_KEY"):
        try:
            result = _llm_classify_and_summarize(company_name, titles, snippets, sources)
            llm_call_count['count'] += 1
            return result
        except Exception as e:
            logger.warning(f"LLM classify/summarize failed: {e}")

    # Fallback: simple classification with company-focused headline
    fallback_headline = f"{company_name}: News Coverage"
    return 'GENERAL', titles[0] if titles else '', fallback_headline


def _llm_classify_and_summarize(
    company_name: str,
    titles: List[str],
    snippets: List[str],
    sources: List[str]
) -> Tuple[str, str, str]:
    """
    Single LLM call to classify type, generate headline, AND generate synopsis.

    Returns (classification, synopsis, headline)
    """
    from langchain_openai import ChatOpenAI
    from langchain_core.messages import SystemMessage, HumanMessage

    types_str = ', '.join(VALID_TYPES)

    system_prompt = f"""You are a VC research assistant analyzing news articles.

Your task:
1. Classify the story into ONE of these types: {types_str}
2. Write a clear, complete headline (max 100 chars) that captures the key news
3. Write a 2-3 sentence synopsis for investors

Classification guidelines:
- FUNDING: fundraising, Series A/B/C, seed rounds, valuations
- M&A: acquisitions, mergers, buyouts
- IPO: going public, S-1 filings, direct listings
- SECURITY: data breaches, hacks, vulnerabilities
- LEGAL: lawsuits, regulatory actions, settlements
- LAYOFFS: job cuts, workforce reductions
- HIRING: executive hires, team expansion
- PARTNERSHIP: strategic alliances, integrations
- PRODUCT: launches, features, releases
- EARNINGS: revenue, profits, financial results
- CUSTOMER: deals, contracts, market expansion
- MARKET: industry trends, macro analysis
- GENERAL: other news

Headline guidelines:
- Start with {company_name}
- Focus ONLY on what {company_name} did (raised, launched, partnered, etc.)
- DO NOT include source names like "| TechCrunch", "| Forbes", "| Reuters"
- DO NOT include generic phrases like "Press and News", "Latest News", "Company Profile"
- Include specific facts (funding amounts, valuations, partner names)
- Be concise (max 80 chars)
- No trailing ellipsis, periods, or pipe characters

Respond in this exact format:
TYPE: [classification]
HEADLINE: [clear, complete headline]
SYNOPSIS: [2-3 sentence synopsis]"""

    # Build context from articles
    context_lines = []
    for i, title in enumerate(titles):
        source = sources[i] if i < len(sources) else 'Unknown'
        snippet = snippets[i][:250] if i < len(snippets) else ''
        context_lines.append(f"[{source}] {title}")
        if snippet:
            context_lines.append(f"  {snippet}")

    user_prompt = f"""Company: {company_name}

Articles:
{chr(10).join(context_lines)}

Classify, write headline, and summarize:"""

    llm = ChatOpenAI(model="gpt-4o-mini", temperature=0, max_tokens=300)
    response = llm.invoke([
        SystemMessage(content=system_prompt),
        HumanMessage(content=user_prompt),
    ])

    # Parse response
    content = response.content.strip()
    classification = 'GENERAL'
    headline = ''
    synopsis = ''

    for line in content.split('\n'):
        line = line.strip()
        if line.upper().startswith('TYPE:'):
            type_val = line[5:].strip().upper()
            if type_val in VALID_TYPES:
                classification = type_val
        elif line.upper().startswith('HEADLINE:'):
            headline = line[9:].strip()
        elif line.upper().startswith('SYNOPSIS:'):
            synopsis = line[9:].strip()

    # If synopsis wasn't found on its own line, use everything after SYNOPSIS:
    if not synopsis:
        parts = content.split('SYNOPSIS:', 1)
        if len(parts) > 1:
            synopsis = parts[1].strip()

    # If headline wasn't found, construct a simple one with company name
    if not headline:
        headline = f"{company_name}: {classification.title()} News"

    # Clean up headline
    headline = headline.rstrip('.')
    if headline.endswith('...'):
        headline = headline[:-3].rstrip()
    if headline.endswith('…'):
        headline = headline[:-1].rstrip()

    # Remove source suffixes (e.g., "| TechCrunch", "| Forbes")
    source_suffixes = [
        '| TechCrunch', '| Forbes', '| Reuters', '| Bloomberg', '| WSJ',
        '| VentureBeat', '| The Verge', '| Wired', '| CNBC', '| Yahoo',
    ]
    for suffix in source_suffixes:
        if suffix in headline:
            headline = headline.split(suffix)[0].strip()
    # Also handle company name suffixes (e.g., "| Slash", "| Harness")
    if ' | ' in headline:
        headline = headline.split(' | ')[0].strip()

    return classification, synopsis[:SYNOPSIS_CONFIG['max_synopsis_length']], headline[:100]


# =============================================================================
# SENTIMENT SCORING
# =============================================================================

def analyze_sentiment(articles: List[ArticleRef]) -> SentimentResult:
    """
    Deterministic sentiment scoring with evidence keywords.

    Scoring methodology:
    - Strong positive (+4 to +5): High-impact value-creating events
      (funding, profitability, hypergrowth, regulatory approval)
    - Moderate positive (+1 to +3): Forward momentum
      (hiring, product launches, partnerships, customer wins)
    - Moderate negative (-1 to -3): Concerning but not terminal
      (delays, leadership changes, competition, cash burn)
    - Strong negative (-4 to -5): Existential or major damage
      (bankruptcy, breaches, lawsuits, layoffs, shutdown)

    Returns SentimentResult with label, score [-5,+5], and matched keywords.
    """
    # Combine all text
    combined_text = ' '.join([
        a.title + ' ' + a.snippet for a in articles
    ]).lower()

    # Track matched positions to avoid double-counting overlapping phrases
    matched_positions: set[int] = set()
    total_score = 0
    keywords_hit = []
    positive_hits = 0
    negative_hits = 0

    # Sort keywords by length (longest first) to match phrases before words
    sorted_keywords = sorted(SENTIMENT_WEIGHTS.keys(), key=len, reverse=True)

    for keyword in sorted_keywords:
        weight = SENTIMENT_WEIGHTS[keyword]
        pos = combined_text.find(keyword)
        if pos != -1:
            # Check if this position range is already matched
            keyword_range = set(range(pos, pos + len(keyword)))
            if not keyword_range & matched_positions:
                total_score += weight
                matched_positions.update(keyword_range)
                keywords_hit.append(keyword)

                if weight > 0:
                    positive_hits += 1
                else:
                    negative_hits += 1

    # Cap score to [-5, +5]
    capped_score = max(-5, min(5, total_score))

    # Determine label
    if positive_hits >= 2 and negative_hits >= 2:
        label = 'Mixed'
    elif capped_score >= 2:
        label = 'Positive'
    elif capped_score <= -2:
        label = 'Negative'
    else:
        label = 'Neutral'

    return SentimentResult(
        label=label,
        score=capped_score,
        keywords_hit=keywords_hit[:5],  # Keep top 5
    )




# =============================================================================
# PRIORITY SCORING
# =============================================================================

def calculate_priority_score(story: Story) -> Tuple[float, List[str]]:
    """
    Calculate investor priority score for a story.

    Returns (score, reasons) where score is 0-100.
    """
    score = 0.0
    reasons = []

    # Classification weight (0-30)
    class_weights = {
        'FUNDING': 30, 'M&A': 30, 'IPO': 28,
        'SECURITY': 25, 'LEGAL': 25, 'LAYOFFS': 22,
        'HIRING': 18, 'EARNINGS': 20, 'PRODUCT': 15,
        'PARTNERSHIP': 12, 'CUSTOMER': 15, 'MARKET': 10,
        'GENERAL': 5,
    }
    class_score = class_weights.get(story.classification, 5)
    score += class_score
    if class_score >= 25:
        reasons.append(f"High-impact: {story.classification}")

    # Entity relevance (0-20, or penalty for industry-wide)
    if story.company_category == 'portfolio':
        score += 20
        reasons.append("Portfolio company")
    elif story.company_category == 'competitor':
        score += 10
        reasons.append("Competitor")
    elif story.company_category == 'industry':
        # Industry stories get a penalty since they're not from tracked companies
        # But high-impact classifications can still make them relevant
        score += INDUSTRY_SEARCH_CONFIG.get('industry_priority_boost', -10)
        reasons.append("Industry news")

    # Source credibility (0-15)
    # Bonus: Company's own domain is a primary source for their announcements
    is_company_domain = False
    if story.articles and story.company_id:
        primary_url = story.primary_url.lower()
        # Extract company domain from company_id (stored as URL or domain)
        from agents.news_aggregator.database import get_company_by_id
        company = get_company_by_id(story.company_id)
        if company:
            company_domain = company.company_id.replace("https://", "").replace("http://", "").rstrip("/")
            if company_domain in primary_url:
                is_company_domain = True

    if story.articles:
        if is_company_domain:
            # Company's own blog/announcements are authoritative primary sources
            source_score = 15
            reasons.append("Company announcement")
        else:
            max_source_priority = max(a.source_priority for a in story.articles)
            source_score = min(15, max_source_priority * 0.15)
            if max_source_priority >= 85:
                reasons.append("Tier-1 source")
        score += source_score

    # Engagement (0-15)
    if story.max_engagement > 0:
        eng_score = min(15, story.max_engagement * 0.05)
        score += eng_score
        if story.max_engagement >= 100:
            reasons.append(f"High engagement ({story.max_engagement})")

    # Multi-source validation (0-10)
    if story.source_count >= 3:
        score += 10
        reasons.append(f"Multi-source ({story.source_count})")
    elif story.source_count >= 2:
        score += 5

    # Recency (0-10)
    if story.published_date:
        try:
            pub = datetime.fromisoformat(story.published_date.replace('Z', '+00:00'))
            days_old = (datetime.now(timezone.utc) - pub).days
            recency_score = max(0, 10 - days_old)
            score += recency_score
        except (ValueError, TypeError):
            pass

    return min(100, score), reasons


# =============================================================================
# NOISE FILTERING
# =============================================================================

def is_noise(article: ArticleRef) -> bool:
    """Check if article is noise."""
    text = f"{article.title} {article.url}".lower()
    for pattern in NOISE_PATTERNS:
        if re.search(pattern, text, re.IGNORECASE):
            return True
    return False


def is_homepage_url(url: str) -> bool:
    """
    Check if URL is a homepage or non-article page.

    Filters out:
    - Domain homepages (https://example.com/)
    - Category/tag pages (https://example.com/category/ai/)
    - Generic section pages (https://example.com/news/)
    - Company profiles, newsrooms, landing pages
    """
    if not url:
        return True

    url_lower = url.lower()

    # Check against homepage patterns
    for pattern in HOMEPAGE_PATTERNS:
        if re.match(pattern, url, re.IGNORECASE):
            return True

    # Check against non-article patterns
    for pattern in NON_ARTICLE_PATTERNS:
        if re.search(pattern, url_lower):
            return True

    # Additional checks
    try:
        parsed = urlparse(url)
        path = parsed.path.strip('/')

        # No path = homepage
        if not path:
            return True

        # Very short path without numbers/dates (likely not an article)
        # Articles usually have slugs, IDs, or dates in the path
        if len(path) < 20 and not re.search(r'\d', path) and path.count('/') == 0:
            return True

        # Common non-article paths
        non_article_paths = [
            'about', 'contact', 'privacy', 'terms', 'careers', 'team',
            'subscribe', 'newsletter', 'advertise', 'press', 'media',
            'news', 'newsroom', 'blog', 'insights', 'resources',
        ]
        if path.lower() in non_article_paths:
            return True

        # Check if path ends with common non-article suffixes
        path_lower = path.lower()
        if path_lower.endswith(('/news', '/newsroom', '/press', '/blog', '/insights')):
            return True

    except Exception:
        pass

    return False


def is_within_date_range(publish_date: Optional[str], days: int = 7, strict: bool = True) -> bool:
    """
    Check if publish date is within the specified range.

    Args:
        publish_date: ISO date string or None
        days: Number of days to look back (default 7)
        strict: If True, reject articles without valid dates (default True)

    Returns:
        True if date is within range
        False if date is outside range, missing (when strict), or unparseable
    """
    if not publish_date:
        # No date - reject if strict mode
        return not strict

    try:
        # Handle various date formats
        date_str = publish_date.replace('Z', '+00:00')
        if 'T' not in date_str:
            date_str = f"{date_str}T00:00:00+00:00"

        pub_date = datetime.fromisoformat(date_str)
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)

        return pub_date >= cutoff
    except (ValueError, TypeError):
        # Can't parse date - reject if strict mode
        return not strict


# =============================================================================
# MARKDOWN RENDERING
# =============================================================================

def _get_deduplicated_industries(store: StoryStore) -> List[str]:
    """
    Get unique industries from all stories, de-duplicated.

    If multiple portfolio companies share the same industry, that industry
    appears only ONCE in the returned list.

    Returns:
        List of unique industry strings, sorted alphabetically
    """
    unique_industries: Set[str] = set()

    for story in store.stories:
        for tag in story.industry_tags:
            # Normalize industry name
            normalized = tag.lower().strip()
            if normalized:
                unique_industries.add(normalized)

    return sorted(list(unique_industries))


def render_digest_markdown(digest: InvestorDigest) -> str:
    """Render digest as investor-grade markdown with tables."""
    lines = []

    # Header
    lines.append("# 📊 Investor Signal Digest")
    lines.append(f"**{digest.start_date} to {digest.end_date}**\n")

    # Stats
    lines.append("## Overview")
    lines.append(f"- **Stories:** {digest.total_stories} (from {digest.total_articles} articles)")
    lines.append(f"- **Companies:** {digest.companies_covered}")
    if digest.industry_filter:
        lines.append(f"- **Industry Filter:** {digest.industry_filter}")
    lines.append(f"- **Generated:** {digest.generated_at[:16]} UTC")
    lines.append("")

    # Get stories by section
    portfolio_stories = sorted(
        digest.store.get_portfolio_stories(),
        key=lambda s: s.priority_score,
        reverse=True
    )
    competitor_stories = sorted(
        digest.store.get_competitor_stories(),
        key=lambda s: s.priority_score,
        reverse=True
    )

    # Section 1: Portfolio Companies
    lines.append("## 📈 Portfolio Companies\n")
    if portfolio_stories:
        lines.extend(_render_story_table(portfolio_stories))
    else:
        lines.append("*No portfolio company stories met the minimum priority threshold.*")
    lines.append("")

    # Section 2: Competitors
    lines.append("## 🎯 Competitors\n")
    if competitor_stories:
        # Group by parent company
        by_parent: Dict[str, List[Story]] = {}
        for story in competitor_stories:
            parent = story.parent_company_name or "Other"
            if parent not in by_parent:
                by_parent[parent] = []
            by_parent[parent].append(story)

        for parent_name, stories in by_parent.items():
            lines.append(f"### Competitors of {parent_name}\n")
            lines.extend(_render_story_table(stories))
            lines.append("")
    else:
        lines.append("*No competitor stories met the minimum priority threshold.*")
        lines.append("")

    # Industry Trends section (only if not already filtered by industry)
    # Shows stories grouped by UNIQUE industry (de-duplicated across portfolio companies)
    lines.append("## 🏭 Industry Trends\n")

    if digest.industry_filter:
        lines.append(f"*Industry filter applied: showing only `{digest.industry_filter}` stories above.*")
        lines.append("")
    else:
        # Track story IDs already shown to avoid duplication
        shown_story_ids: Set[str] = set()
        for s in portfolio_stories:
            shown_story_ids.add(s.story_id)
        for s in competitor_stories:
            shown_story_ids.add(s.story_id)

        industry_section_has_stories = False
        max_stories_per_industry = INDUSTRY_SEARCH_CONFIG.get('max_stories_per_industry', 5)

        # Collect all unique industries across portfolio companies (de-duplicated)
        # Each industry appears ONCE regardless of how many portfolio companies share it
        unique_industries = _get_deduplicated_industries(digest.store)

        # Sort industries by max story priority (most "active" industries first)
        industries_with_priority: List[Tuple[str, float, List[Story]]] = []

        for industry in unique_industries:
            # Get industry-wide stories (category='industry') for this industry
            industry_stories = [
                s for s in digest.store.get_industry_stories()
                if industry.lower() in [t.lower() for t in s.industry_tags]
                and s.story_id not in shown_story_ids
            ]

            # Also include tracked company stories tagged with this industry
            tracked_stories = [
                s for s in digest.store.get_stories_by_industry(industry)
                if s.story_id not in shown_story_ids
                and s.company_category != 'industry'  # Avoid double-counting
            ]

            all_industry_stories = industry_stories + tracked_stories

            # Sort by priority and dedupe
            seen_ids = set()
            deduped_stories = []
            for s in sorted(all_industry_stories, key=lambda x: x.priority_score, reverse=True):
                if s.story_id not in seen_ids:
                    deduped_stories.append(s)
                    seen_ids.add(s.story_id)

            if deduped_stories:
                max_priority = max(s.priority_score for s in deduped_stories)
                industries_with_priority.append((industry, max_priority, deduped_stories))

        # Sort by max priority descending
        industries_with_priority.sort(key=lambda x: x[1], reverse=True)

        # Render each unique industry once
        for industry, max_priority, industry_stories in industries_with_priority:
            # Cap stories per industry
            top_stories = industry_stories[:max_stories_per_industry]

            if top_stories:
                industry_section_has_stories = True

                # Format industry name nicely
                industry_name = industry.replace('_', ' ').title()
                lines.append(f"### {industry_name}\n")
                lines.extend(_render_story_table(top_stories, include_company=True))
                lines.append("")

                # Mark as shown
                for s in top_stories:
                    shown_story_ids.add(s.story_id)

        if not industry_section_has_stories:
            total_shown = len(shown_story_ids)
            if total_shown > 0:
                lines.append(f"*All {total_shown} stories were already shown in Portfolio Companies and Competitors sections above.*")
            else:
                lines.append("*No industry tags assigned to companies. Run `--refresh-industries` to fetch tags from Harmonic.*")
            lines.append("")

    # Footer with timing stats
    lines.append("---")
    lines.append(f"*Generated by Investor Digest Pipeline*")
    if digest.timing and digest.timing.total_time_ms > 0:
        lines.append(f"*Runtime: {digest.timing.total_time_ms}ms (fetch: {digest.timing.fetch_time_ms}ms, classify: {digest.timing.classification_time_ms}ms, LLM calls: {digest.timing.llm_calls})*")

    return '\n'.join(lines)


def _render_story_table(stories: List[Story], include_company: bool = True) -> List[str]:
    """Render stories as a formatted table using pandas."""
    if not stories:
        return ["*No stories*"]

    try:
        import pandas as pd

        # Build data for DataFrame
        data = []
        for story in stories:
            # Truncate title
            title = story.primary_title[:50]
            if len(story.primary_title) > 50:
                title += "..."

            # Sentiment with icon
            sent = story.sentiment
            sent_icon = {'Positive': '📈', 'Negative': '📉', 'Neutral': '➖', 'Mixed': '⚖️'}.get(sent.label, '➖')
            sent_str = f"{sent_icon} {sent.score:+d}"

            # Synopsis (truncate)
            synopsis = story.synopsis[:120]
            if len(story.synopsis) > 120:
                synopsis += "..."

            # Sources indicator
            sources = f"+{len(story.other_urls)}" if story.other_urls else ""

            row = {
                'Company': story.company_name[:15],
                'Title': title,
                'Type': story.classification,
                'Sent': sent_str,
                'Src': sources,
                'Synopsis': synopsis,
                'URL': story.primary_url,
            }
            data.append(row)

        df = pd.DataFrame(data)

        # Select columns based on include_company flag
        if include_company:
            cols = ['Company', 'Title', 'Type', 'Sent', 'Src', 'Synopsis']
        else:
            cols = ['Title', 'Type', 'Sent', 'Src', 'Synopsis']

        # Use tabulate for nicer output if available, otherwise pandas
        try:
            from tabulate import tabulate
            table = tabulate(
                df[cols],
                headers='keys',
                tablefmt='simple',
                showindex=False,
                maxcolwidths=[15, 40, 10, 6, 4, 60] if include_company else [45, 10, 6, 4, 60]
            )
        except ImportError:
            # Fall back to pandas to_string
            table = df[cols].to_string(index=False)

        lines = ["```"]
        lines.append(table)
        lines.append("```")

        # Add URLs as footnotes
        lines.append("")
        lines.append("**Links:**")
        for i, story in enumerate(stories, 1):
            short_title = story.primary_title[:50]
            if len(story.primary_title) > 50:
                short_title += "..."
            lines.append(f"{i}. [{short_title}]({story.primary_url})")

        return lines

    except ImportError:
        # Fallback to simple markdown table if pandas not available
        return _render_story_table_markdown(stories, include_company)


def _render_story_table_markdown(stories: List[Story], include_company: bool = True) -> List[str]:
    """Fallback markdown table renderer."""
    if not stories:
        return ["*No stories*"]

    lines = []

    # Table header
    if include_company:
        lines.append("| Company | Title | Type | Sent | Synopsis |")
        lines.append("|---------|-------|------|------|----------|")
    else:
        lines.append("| Title | Type | Sent | Synopsis |")
        lines.append("|-------|------|------|----------|")

    for story in stories:
        # Truncate title
        title = story.primary_title[:50]
        if len(story.primary_title) > 50:
            title += "..."

        # Format title as link
        title_cell = f"[{title}]({story.primary_url})"

        # Sentiment with icon
        sent = story.sentiment
        sent_icon = {'Positive': '📈', 'Negative': '📉', 'Neutral': '➖', 'Mixed': '⚖️'}.get(sent.label, '➖')
        sent_cell = f"{sent_icon}{sent.score:+d}"

        # Synopsis (truncate)
        synopsis = story.synopsis[:100]
        if len(story.synopsis) > 100:
            synopsis += "..."
        if story.other_urls:
            synopsis += f" *+{len(story.other_urls)}*"

        if include_company:
            lines.append(f"| {story.company_name[:15]} | {title_cell} | {story.classification} | {sent_cell} | {synopsis} |")
        else:
            lines.append(f"| {title_cell} | {story.classification} | {sent_cell} | {synopsis} |")

    return lines


# =============================================================================
# INDUSTRY NEWS SEARCH
# =============================================================================

def get_portfolio_industries(investor_id: str = None) -> List[str]:
    """Get unique industries from portfolio companies, sorted by frequency."""
    portfolio = get_portfolio_companies(investor_id)
    industry_counts: Dict[str, int] = {}

    for company in portfolio:
        for tag in company.industries:
            # Normalize tag
            tag_lower = tag.lower().strip()
            industry_counts[tag_lower] = industry_counts.get(tag_lower, 0) + 1

    # Sort by count (most common first) and return
    sorted_industries = sorted(industry_counts.items(), key=lambda x: x[1], reverse=True)
    return [industry for industry, _ in sorted_industries]


def search_industry_news(
    industries: List[str],
    days: int = 7,
) -> List[ArticleRef]:
    """
    Search for news across industries using ParallelSearchClient.

    Filters applied:
    1. Only articles from the last N days (default 7)
    2. Excludes homepage/non-article URLs

    Note: Does NOT exclude articles mentioning portfolio/competitor names -
    industry news can mention tracked companies.

    Args:
        industries: List of industry tags to search
        days: Days to look back (articles older than this are filtered)

    Returns:
        List of ArticleRef objects from industry searches
    """
    try:
        from core.clients.parallel_search import ParallelSearchClient
    except ImportError:
        logger.warning("ParallelSearchClient not available for industry search")
        return []

    config = INDUSTRY_SEARCH_CONFIG
    max_industries = config['max_industries']
    max_results = config['max_results_per_industry']

    articles: List[ArticleRef] = []
    searched_urls: Set[str] = set()  # Deduplicate across industries

    # Track filtering stats
    filtered_stats = {'homepage': 0, 'old_date': 0, 'noise': 0}

    try:
        client = ParallelSearchClient()
    except Exception as e:
        logger.warning(f"Failed to initialize ParallelSearchClient: {e}")
        return []

    # Search top N industries
    for industry in industries[:max_industries]:
        logger.info(f"Searching industry news for: {industry}")

        try:
            # Use industry-specific search (no company exclusions)
            results = client.search_industry_news(
                industry=industry,
                exclude_companies=[],  # Don't exclude any companies
                max_results=max_results,
                max_chars_per_result=500,  # Metadata only
            )

            for result in results:
                url = result.url or ""
                if not url or url in searched_urls:
                    continue

                # Filter 1: Homepage/non-article URLs
                if is_homepage_url(url):
                    filtered_stats['homepage'] += 1
                    continue

                # Filter 2: Date range (only last N days)
                if not is_within_date_range(result.publish_date, days=days):
                    filtered_stats['old_date'] += 1
                    continue

                title = result.title or ""
                snippet = " ".join(result.excerpts or [])[:500] if result.excerpts else ""

                searched_urls.add(url)

                # Create ArticleRef for industry story
                article = ArticleRef(
                    url=url,
                    title=title,
                    source_domain=result.source_domain or extract_domain(url),
                    published_date=result.publish_date,
                    snippet=snippet,
                    engagement_score=0,
                    company_id="",  # No specific company
                    company_name=f"[{industry.title()}]",  # Show industry as "company"
                    company_category="industry",  # Special category
                    parent_company_name=None,
                    industry_tags=[industry],
                    signal_id="",
                )

                # Filter 3: Noise patterns
                if is_noise(article):
                    filtered_stats['noise'] += 1
                    continue

                articles.append(article)

        except Exception as e:
            logger.warning(f"Industry search failed for {industry}: {e}")
            continue

    logger.info(
        f"Found {len(articles)} industry news articles "
        f"(filtered: {filtered_stats['homepage']} homepage, {filtered_stats['old_date']} old, "
        f"{filtered_stats['noise']} noise)"
    )
    return articles


def _get_industry_search_terms(industry: str) -> str:
    """Convert industry tag to search terms."""
    # Map common industry tags to search-friendly terms
    industry_search_map = {
        'financial services': 'fintech funding startup',
        'fintech': 'fintech funding startup',
        'artificial intelligence': 'AI startup funding',
        'ai_ml': 'AI machine learning startup',
        'healthcare': 'healthtech startup funding',
        'cybersecurity': 'cybersecurity startup funding',
        'enterprise': 'enterprise software startup',
        'saas': 'SaaS startup funding',
        'developer': 'developer tools startup',
        'data': 'data analytics startup',
        'analytics': 'analytics startup funding',
        'cloud': 'cloud infrastructure startup',
        'payments': 'payments fintech startup',
        'ai': 'AI startup funding news',
        'b2b': 'B2B startup funding',
        'software': 'software startup funding',
        'media': 'media tech startup',
        'edtech': 'edtech startup funding',
        'communications': 'communications tech startup',
    }

    industry_lower = industry.lower()

    # Check for exact match
    if industry_lower in industry_search_map:
        return industry_search_map[industry_lower]

    # Check for partial match
    for key, terms in industry_search_map.items():
        if key in industry_lower or industry_lower in key:
            return terms

    # Fallback: use the industry name directly
    return f"{industry} startup funding news"


# =============================================================================
# MAIN PIPELINE
# =============================================================================

def generate_investor_digest(
    days: int = 7,
    min_priority_score: float = 40.0,
    max_stories_per_section: int = 15,
    investor_id: str = None,
    industry_filter: str = None,
    fast_mode: bool = False,
    include_industry_search: bool = True,
) -> InvestorDigest:
    """
    Generate unified investor digest.

    Single pipeline: fetch -> normalize -> cluster -> classify -> sentiment -> synopsis -> rank -> render

    Re-engineered for reduced LLM runtime:
    - Uses only title + snippet (no full article body)
    - Embeddings cached by URL hash
    - LLM calls limited to 1 per unique story (or fewer)
    - Portfolio vs Competitor exclusion enforced
    - Industry Trends with de-duplicated industries

    Args:
        days: Days to look back (default 7)
        min_priority_score: Minimum score to include (default 40)
        max_stories_per_section: Max stories per section (default 15)
        investor_id: Optional investor filter
        industry_filter: Optional industry tag to filter by (e.g., "fintech", "ai_ml")
        fast_mode: Skip LLM synopsis and HN enrichment for faster generation
        include_industry_search: Search for industry-wide news (adds API calls)

    Returns:
        InvestorDigest with all stories and markdown output
    """
    pipeline_start = time.time()
    timing = PipelineTimingStats()

    # Calculate date range
    end_date = datetime.now(timezone.utc)
    start_date = end_date - timedelta(days=days)
    cutoff_iso = start_date.isoformat()

    # ==========================================================================
    # FETCH PHASE
    # ==========================================================================
    fetch_start = time.time()

    # Fetch all signals and companies
    all_signals = get_signals(investor_id=investor_id, limit=1000)
    all_companies = get_companies(active_only=True)

    # Build company lookup with industry tags
    companies: Dict[str, WatchedCompany] = {}
    company_industries: Dict[str, List[str]] = {}
    portfolio_ids: Set[str] = set()  # Track portfolio company IDs for exclusion

    for c in all_companies:
        companies[c.id] = c
        company_industries[c.id] = c.industries
        if c.category == "portfolio":
            portfolio_ids.add(c.id)

    # Filter by industry if specified
    if industry_filter:
        industry_filter_lower = industry_filter.lower()
        filtered_company_ids = set()
        for cid, tags in company_industries.items():
            if any(industry_filter_lower in tag.lower() for tag in tags):
                filtered_company_ids.add(cid)
        companies = {k: v for k, v in companies.items() if k in filtered_company_ids}

    # Build parent company lookup
    parent_names: Dict[str, str] = {}
    for c in companies.values():
        if c.category == "competitor" and c.parent_company_id:
            parent = companies.get(c.parent_company_id)
            if parent:
                parent_names[c.id] = parent.company_name

    # Step 1: Convert signals to ArticleRefs (filter by date + noise)
    articles: List[ArticleRef] = []

    for signal in all_signals:
        # Skip if no URL
        url = signal.source_url or ""
        if not url:
            continue

        # Get company early to check if URL is from company's own domain
        company = companies.get(signal.company_id)
        if not company:
            continue

        # Check if URL is from company's own domain (blog posts, changelog, etc.)
        company_domain = company.company_id.replace("https://", "").replace("http://", "").rstrip("/")
        is_company_domain = company_domain in url.lower()

        # Filter: Homepage/non-article URLs
        # Exception: Allow company's own domain content (their blog, docs, changelog)
        if not is_company_domain and is_homepage_url(url):
            continue

        # For company's own domain, only skip the actual homepage
        if is_company_domain:
            path = urlparse(url).path.strip('/')
            if not path:  # Actual homepage with no path
                continue

        # Date filter - strict: require valid date within range
        # Exception: Company's own content is always relevant (may not have dates)
        if not is_company_domain:
            if not is_within_date_range(signal.published_date, days=days, strict=True):
                # Fallback: check detected_at if no published_date
                if signal.detected_at:
                    if not is_within_date_range(signal.detected_at, days=days, strict=True):
                        continue
                else:
                    continue

        # Company already fetched above
        if not company:
            continue

        article = ArticleRef(
            url=url,
            title=signal.headline,
            source_domain=signal.source_name or extract_domain(url),
            published_date=signal.published_date,
            snippet=signal.description or "",
            engagement_score=0,  # Will be enriched from HN/PH
            company_id=company.id,
            company_name=company.company_name,
            company_category=company.category,
            parent_company_name=parent_names.get(company.id),
            industry_tags=company_industries.get(company.id, []),
            signal_id=signal.id,
        )

        # Filter noise
        if is_noise(article):
            continue

        articles.append(article)

    # Step 1b: Fetch industry-wide news (beyond tracked companies)
    if include_industry_search and not industry_filter:
        portfolio_industries = get_portfolio_industries(investor_id)
        if portfolio_industries:
            logger.info(f"Searching industry news for top industries: {portfolio_industries[:INDUSTRY_SEARCH_CONFIG['max_industries']]}")
            # Search industry news (allows company mentions)
            industry_articles = search_industry_news(
                portfolio_industries,
                days=days,
            )

            # Add industry articles (they'll be processed through same pipeline)
            articles.extend(industry_articles)
            logger.info(f"Added {len(industry_articles)} industry articles to pipeline")

    timing.fetch_time_ms = int((time.time() - fetch_start) * 1000)

    # Step 2: Enrich with engagement data from HN (skip in fast mode)
    if not fast_mode:
        articles = _enrich_with_hn_engagement(articles)

    # ==========================================================================
    # CLASSIFICATION & EMBEDDING PHASE
    # ==========================================================================
    classify_start = time.time()

    # Step 3: Cluster articles into stories
    clusters = cluster_articles(articles)

    # Step 4: Build stories from clusters
    store = StoryStore()
    synopsis_cache: Dict[str, str] = {}
    llm_call_count = {'count': 0}

    for cluster in clusters:
        primary, other_urls = select_primary_article(cluster)

        story = Story(
            story_id="",
            primary_url=primary.url,
            primary_title=primary.title,  # Temporary, will be replaced by LLM headline
            other_urls=other_urls,
            articles=cluster,
            company_id=primary.company_id,
            company_name=primary.company_name,
            company_category=primary.company_category,
            parent_company_name=primary.parent_company_name,
            industry_tags=primary.industry_tags,
            published_date=primary.published_date,
            max_engagement=max(a.engagement_score for a in cluster),
            source_count=len(cluster),
        )

        # Sentiment (deterministic - do first for priority scoring)
        story.sentiment = analyze_sentiment(cluster)

        # LLM classifies, generates synopsis, AND generates headline
        story.classification, story.synopsis, story.primary_title = classify_and_summarize_story(
            cluster,
            story.company_name,
            llm_call_count
        )

        # Compute story ID AFTER classification (uses company + classification + amount + week)
        story.story_id = story.compute_story_id()

        # Priority scoring
        story.priority_score, story.priority_reasons = calculate_priority_score(story)

        # Filter by minimum score
        if story.priority_score < min_priority_score:
            continue

        store.add_story(story)

    timing.classification_time_ms = int((time.time() - classify_start) * 1000)
    timing.llm_calls = llm_call_count['count']

    # ==========================================================================
    # PORTFOLIO vs COMPETITOR EXCLUSION
    # ==========================================================================
    # Remove competitors that are also portfolio companies from competitor section
    _resolve_portfolio_competitor_overlap(store, portfolio_ids)

    # ==========================================================================
    # BUILD DIGEST
    # ==========================================================================
    digest_generated_at = datetime.now(timezone.utc).isoformat()

    timing.total_time_ms = int((time.time() - pipeline_start) * 1000)

    digest = InvestorDigest(
        start_date=start_date.strftime("%Y-%m-%d"),
        end_date=end_date.strftime("%Y-%m-%d"),
        store=store,
        total_stories=len(store.stories),
        total_articles=len(articles),
        companies_covered=len(set(s.company_id for s in store.stories if s.company_id)),
        industry_filter=industry_filter,
        generated_at=digest_generated_at,
        timing=timing,
    )

    # Persist stories to database
    cached_stories = []
    for story in store.stories:
        cached = CachedStory(
            id=str(uuid.uuid4()),
            story_id=story.story_id,
            primary_url=story.primary_url,
            primary_title=story.primary_title,
            other_urls=story.other_urls,
            classification=story.classification,
            sentiment_label=story.sentiment.label,
            sentiment_score=story.sentiment.score,
            sentiment_keywords=story.sentiment.keywords_hit,
            synopsis=story.synopsis,
            company_id=story.company_id,
            company_name=story.company_name,
            company_category=story.company_category,
            parent_company_name=story.parent_company_name,
            industry_tags=story.industry_tags,
            priority_score=story.priority_score,
            priority_reasons=story.priority_reasons,
            published_date=story.published_date or datetime.now(timezone.utc).strftime("%Y-%m-%d"),
            max_engagement=story.max_engagement,
            source_count=story.source_count,
            article_signal_ids=[a.signal_id for a in story.articles],
            digest_generated_at=digest_generated_at,
        )
        cached_stories.append(cached)

    if cached_stories:
        saved_count = save_stories_batch(cached_stories, digest_generated_at)
        logger.info(f"Cached {saved_count} stories to database")

        # Deduplicate any stories that represent the same event
        from .database import deduplicate_stories
        dedup_result = deduplicate_stories()
        if dedup_result['deleted'] > 0:
            logger.info(f"Deduplicated {dedup_result['merged']} story groups, removed {dedup_result['deleted']} duplicates")

    # Save digest run to history
    try:
        portfolio_story_count = len([s for s in store.stories if s.company_category == "portfolio"])
        competitor_story_count = len([s for s in store.stories if s.company_category == "competitor"])

        # Get top 3 stories summary
        top_stories = sorted(store.stories, key=lambda s: s.priority_score, reverse=True)[:3]
        top_stories_summary = "; ".join([
            f"{s.company_name}: {s.primary_title[:80]}" for s in top_stories
        ]) if top_stories else None

        digest_history = get_digest_history()
        digest_history.save_digest(
            story_count=digest.total_stories,
            portfolio_count=portfolio_story_count,
            competitor_count=competitor_story_count,
            top_stories_summary=top_stories_summary,
            investor_filter=industry_filter,
            success=True,
        )

        # Also save to persistent audit log
        audit_log = get_audit_log()
        audit_log.log(
            agent="news_aggregator",
            event_type="digest",
            action="generate",
            resource_type="digest",
            details={
                "story_count": digest.total_stories,
                "portfolio_count": portfolio_story_count,
                "competitor_count": competitor_story_count,
                "companies_covered": digest.companies_covered,
                "industry_filter": industry_filter,
                "total_time_ms": timing.total_time_ms,
            },
        )
    except Exception as hist_err:
        logger.warning(f"Failed to save digest history: {hist_err}")

    logger.info(
        f"Generated digest: {digest.total_stories} stories from {digest.total_articles} articles "
        f"covering {digest.companies_covered} companies "
        f"(timing: fetch={timing.fetch_time_ms}ms, classify={timing.classification_time_ms}ms, "
        f"embed={timing.embedding_time_ms}ms, llm_calls={timing.llm_calls}, total={timing.total_time_ms}ms)"
    )

    return digest


def _resolve_portfolio_competitor_overlap(store: StoryStore, portfolio_ids: Set[str]):
    """
    Remove competitor stories where the company is also in portfolio_ids.

    Requirement: If one portfolio company is a competitor of another portfolio company,
    do not include that company in Competitors section - only in Portfolio section.
    """
    # Find company IDs that are both portfolio and marked as competitor of another
    overlap_ids = set()
    for story in store.stories:
        if story.company_category == "competitor" and story.company_id in portfolio_ids:
            overlap_ids.add(story.company_id)

    if overlap_ids:
        logger.info(f"Portfolio/Competitor overlap: removing {len(overlap_ids)} companies from Competitors")

        # Update stories to be portfolio instead of competitor
        for story in store.stories:
            if story.company_id in overlap_ids and story.company_category == "competitor":
                story.company_category = "portfolio"
                story.parent_company_name = None  # Clear competitor linkage


def _enrich_with_hn_engagement(articles: List[ArticleRef]) -> List[ArticleRef]:
    """Enrich articles with HN engagement scores where available."""
    try:
        from core.clients.hackernews import HackerNewsClient
        hn = HackerNewsClient()

        # Get unique company names
        company_names = list(set(a.company_name for a in articles))

        # Fetch HN data per company (batch)
        hn_data: Dict[str, Dict[str, int]] = {}  # url -> engagement

        for company_name in company_names[:10]:  # Limit API calls
            try:
                result = hn.search_company_mentions(company_name, days_back=30, max_results=20)
                for story in result.stories:
                    if story.url:
                        hn_data[normalize_url(story.url)] = story.engagement_score
                    # Also store HN discussion URL
                    hn_data[normalize_url(story.hn_url)] = story.engagement_score
            except Exception as e:
                logger.warning(f"HN fetch failed for {company_name}: {e}")

        # Enrich articles
        for article in articles:
            norm_url = article.normalized_url
            if norm_url in hn_data:
                article.engagement_score = max(article.engagement_score, hn_data[norm_url])

    except ImportError:
        logger.warning("HackerNewsClient not available")
    except Exception as e:
        logger.warning(f"HN enrichment failed: {e}")

    return articles


# =============================================================================
# CLI ENTRYPOINT
# =============================================================================

def main():
    """CLI entrypoint for digest generation."""
    import argparse

    parser = argparse.ArgumentParser(description="Generate Investor Digest")
    parser.add_argument("--days", type=int, default=7, help="Days to look back")
    parser.add_argument("--min-score", type=float, default=40.0, help="Minimum priority score")
    parser.add_argument("--json", action="store_true", help="Output as JSON instead of markdown")

    args = parser.parse_args()

    digest = generate_investor_digest(
        days=args.days,
        min_priority_score=args.min_score,
    )

    if args.json:
        output = {
            "start_date": digest.start_date,
            "end_date": digest.end_date,
            "total_stories": digest.total_stories,
            "total_articles": digest.total_articles,
            "companies_covered": digest.companies_covered,
            "stories": [
                {
                    "story_id": s.story_id,
                    "primary_url": s.primary_url,
                    "primary_title": s.primary_title,
                    "other_urls": s.other_urls,
                    "classification": s.classification,
                    "sentiment": {"label": s.sentiment.label, "score": s.sentiment.score},
                    "synopsis": s.synopsis,
                    "company_name": s.company_name,
                    "priority_score": s.priority_score,
                }
                for s in digest.store.stories
            ],
        }
        print(json.dumps(output, indent=2))
    else:
        print(digest.to_markdown())


if __name__ == "__main__":
    main()

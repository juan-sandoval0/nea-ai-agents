"""
Hacker News API Client
======================

Search for company mentions on Hacker News via the Algolia HN API.
Free API, no authentication required.

Usage:
    from core.clients.hackernews import HackerNewsClient

    client = HackerNewsClient()
    results = client.search_company_mentions("Stripe")
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Optional

import requests

from core.tracking import get_tracker

logger = logging.getLogger(__name__)

# =============================================================================
# CONFIGURATION
# =============================================================================

ALGOLIA_HN_BASE_URL = "https://hn.algolia.com/api/v1"

# Engagement thresholds for filtering
MIN_POINTS_THRESHOLD = 5  # Minimum points to be considered relevant
MIN_COMMENTS_THRESHOLD = 2  # Minimum comments for discussion signal


# =============================================================================
# DATA MODELS
# =============================================================================

@dataclass
class HNStory:
    """A Hacker News story mentioning a company."""
    story_id: str
    title: str
    url: Optional[str] = None
    points: int = 0
    comment_count: int = 0
    author: Optional[str] = None
    created_at: Optional[str] = None
    hn_url: str = ""  # Link to HN discussion

    @property
    def engagement_score(self) -> int:
        """Calculate engagement score from points and comments."""
        # Points are direct votes, comments indicate discussion
        # Weight comments slightly higher as they indicate deeper engagement
        return self.points + (self.comment_count * 2)

    @property
    def engagement_level(self) -> str:
        """Categorize engagement level."""
        score = self.engagement_score
        if score >= 500:
            return "viral"
        elif score >= 100:
            return "high"
        elif score >= 30:
            return "medium"
        return "low"


@dataclass
class HNSearchResult:
    """Result of searching HN for company mentions."""
    company_name: str
    stories: list[HNStory] = field(default_factory=list)
    total_hits: int = 0
    searched_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())


# =============================================================================
# EXCEPTIONS
# =============================================================================

class HackerNewsAPIError(Exception):
    """Custom exception for Hacker News API errors."""
    def __init__(self, message: str, status_code: Optional[int] = None):
        super().__init__(message)
        self.status_code = status_code


# =============================================================================
# CLIENT
# =============================================================================

class HackerNewsClient:
    """
    Search Hacker News for company mentions via Algolia API.

    The Algolia HN API is free and requires no authentication.
    Rate limits are generous but we still track calls.
    """

    def __init__(self, timeout: int = 10):
        """
        Initialize HN client.

        Args:
            timeout: Request timeout in seconds
        """
        self._timeout = timeout
        self._tracker = get_tracker()
        self._session = requests.Session()
        self._session.headers.update({
            "Accept": "application/json",
            "User-Agent": "NEA-AI-Agents/1.0",
        })

    def search_company_mentions(
        self,
        company_name: str,
        days_back: int = 90,
        max_results: int = 20,
        min_points: int = MIN_POINTS_THRESHOLD,
    ) -> HNSearchResult:
        """
        Search for company mentions in HN stories.

        Args:
            company_name: Company name to search for
            days_back: How many days back to search (default 90)
            max_results: Maximum stories to return (default 20)
            min_points: Minimum points filter (default 5)

        Returns:
            HNSearchResult with matching stories

        Raises:
            HackerNewsAPIError: If API request fails
        """
        # Calculate timestamp for date filter
        cutoff_date = datetime.utcnow() - timedelta(days=days_back)
        cutoff_timestamp = int(cutoff_date.timestamp())

        # Build query - search in story titles and URLs
        params = {
            "query": company_name,
            "tags": "story",  # Only stories, not comments
            "numericFilters": f"created_at_i>{cutoff_timestamp},points>={min_points}",
            "hitsPerPage": min(max_results, 50),  # API max is 50
        }

        start = time.time()
        try:
            response = self._session.get(
                f"{ALGOLIA_HN_BASE_URL}/search",
                params=params,
                timeout=self._timeout,
            )
            latency = int((time.time() - start) * 1000)

            self._tracker.log_api_call(
                service="hackernews",
                endpoint="/search",
                method="GET",
                status_code=response.status_code,
                latency_ms=latency,
            )

            response.raise_for_status()
            data = response.json()

        except requests.exceptions.Timeout:
            latency = int((time.time() - start) * 1000)
            self._tracker.log_api_call(
                service="hackernews",
                endpoint="/search",
                method="GET",
                status_code=408,
                latency_ms=latency,
            )
            logger.error(f"HN API timeout searching for '{company_name}'")
            raise HackerNewsAPIError("Request timeout", status_code=408)

        except requests.exceptions.RequestException as e:
            latency = int((time.time() - start) * 1000)
            status = getattr(e.response, "status_code", 500) if e.response else 500
            self._tracker.log_api_call(
                service="hackernews",
                endpoint="/search",
                method="GET",
                status_code=status,
                latency_ms=latency,
            )
            logger.error(f"HN API error searching for '{company_name}': {e}")
            raise HackerNewsAPIError(f"API request failed: {e}", status_code=status)

        # Parse results
        stories = []
        for hit in data.get("hits", []):
            story = HNStory(
                story_id=str(hit.get("objectID", "")),
                title=hit.get("title", ""),
                url=hit.get("url"),
                points=hit.get("points", 0) or 0,
                comment_count=hit.get("num_comments", 0) or 0,
                author=hit.get("author"),
                created_at=hit.get("created_at"),
                hn_url=f"https://news.ycombinator.com/item?id={hit.get('objectID', '')}",
            )
            stories.append(story)

        # Sort by engagement score (highest first)
        stories.sort(key=lambda s: s.engagement_score, reverse=True)

        result = HNSearchResult(
            company_name=company_name,
            stories=stories[:max_results],
            total_hits=data.get("nbHits", len(stories)),
        )

        logger.info(
            f"HN Search: found {len(stories)} stories for '{company_name}' "
            f"(total hits: {result.total_hits})"
        )

        return result

    def get_recent_discussions(
        self,
        company_name: str,
        days_back: int = 30,
        min_comments: int = MIN_COMMENTS_THRESHOLD,
    ) -> list[HNStory]:
        """
        Get recent HN discussions about a company (stories with active comments).

        Args:
            company_name: Company name to search for
            days_back: How many days back to search
            min_comments: Minimum comment count filter

        Returns:
            List of HNStory with active discussions
        """
        result = self.search_company_mentions(
            company_name=company_name,
            days_back=days_back,
            max_results=50,
            min_points=1,  # Lower threshold, filter by comments instead
        )

        # Filter to stories with meaningful discussion
        discussions = [
            story for story in result.stories
            if story.comment_count >= min_comments
        ]

        # Sort by comment count for discussion relevance
        discussions.sort(key=lambda s: s.comment_count, reverse=True)

        return discussions[:10]

    def get_viral_mentions(
        self,
        company_name: str,
        days_back: int = 180,
        min_points: int = 100,
    ) -> list[HNStory]:
        """
        Get viral/high-engagement HN stories about a company.

        Args:
            company_name: Company name to search for
            days_back: How many days back to search
            min_points: Minimum points for viral threshold

        Returns:
            List of high-engagement HNStory
        """
        result = self.search_company_mentions(
            company_name=company_name,
            days_back=days_back,
            max_results=20,
            min_points=min_points,
        )

        return [s for s in result.stories if s.engagement_level in ("high", "viral")]

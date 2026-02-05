"""
Unit Tests for Tavily API Client
================================
Tests for website intelligence, signal classification, and edge cases.

Run with:
    pytest tests/test_tavily_client.py -v
"""

import pytest
from unittest.mock import Mock, patch, MagicMock

from core.clients.tavily import (
    TavilyClient,
    TavilyAPIError,
    WebsiteIntelligence,
    _classify_crawled_page,
    _extract_key_sentences,
    SIGNAL_KEYWORDS,
)


# =============================================================================
# FIXTURES
# =============================================================================

@pytest.fixture
def mock_api_key():
    """Provide a mock API key."""
    return "test_tavily_api_key_12345"


@pytest.fixture
def mock_tavily_sdk():
    """Mock the Tavily SDK client."""
    with patch("core.clients.tavily.TavilyClient.__init__", lambda self, api_key=None: None):
        with patch.dict("os.environ", {"TAVILY_API_KEY": "test_key"}):
            client = TavilyClient.__new__(TavilyClient)
            client.api_key = "test_key"
            client._client = MagicMock()
            return client


# =============================================================================
# SENTENCE EXTRACTION TESTS
# =============================================================================

class TestSentenceExtraction:
    """Tests for _extract_key_sentences function."""

    def test_extracts_meaningful_sentences(self):
        """Should extract meaningful sentences from content."""
        text = """
        Skip to content
        Navigation Menu

        Stripe launches new payment processing feature with 50% faster transactions.
        The update includes support for international payments and multi-currency.

        Subscribe to newsletter
        Follow us on Twitter
        """
        result = _extract_key_sentences(text, max_chars=200)

        assert "Stripe" in result
        assert "payment" in result.lower()
        # Should not include boilerplate
        assert "skip to content" not in result.lower()
        assert "subscribe" not in result.lower()

    def test_filters_boilerplate(self):
        """Should filter out common boilerplate patterns."""
        text = """
        Skip to content
        Accept all cookies
        Privacy Policy
        Subscribe to our newsletter
        Log in
        This is the actual meaningful content about the product launch.
        """
        result = _extract_key_sentences(text)

        # Should only contain meaningful content
        assert "meaningful content" in result
        assert "cookie" not in result.lower()
        assert "privacy" not in result.lower()

    def test_handles_markdown_artifacts(self):
        """Should clean up markdown link syntax."""
        text = """
        Check out our [new product](https://example.com/product) announcement.
        Read more about the [feature update](https://example.com/features).
        """
        result = _extract_key_sentences(text)

        # Should extract text without markdown syntax
        assert "](http" not in result
        # Content should be preserved
        assert "product" in result.lower() or "feature" in result.lower()

    def test_returns_empty_for_boilerplate_only(self):
        """Should return empty string if only boilerplate content."""
        text = """
        Skip to content
        Menu
        Navigation
        Log in
        Sign up
        """
        result = _extract_key_sentences(text)
        # May return empty or minimal content
        assert len(result) < 30 or result == ""

    def test_respects_max_chars(self):
        """Should respect max_chars limit."""
        text = """
        This is a very long sentence about important company developments that exceeds the limit.
        Another long sentence with additional details about the product launch and features.
        Yet another sentence describing the partnership announcement with major tech companies.
        """
        result = _extract_key_sentences(text, max_chars=50)

        # Result should be reasonably close to max_chars
        assert len(result) <= 100  # Allow some buffer for sentence completion

    def test_handles_empty_input(self):
        """Should handle empty input gracefully."""
        assert _extract_key_sentences("") == ""
        assert _extract_key_sentences("   ") == ""
        assert _extract_key_sentences("\n\n\n") == ""

    def test_filters_url_heavy_lines(self):
        """Should filter lines with multiple URLs."""
        text = """
        Check https://example.com and https://other.com and https://third.com for more info.
        This is actual meaningful content about the company's new feature.
        """
        result = _extract_key_sentences(text)

        # Should prefer meaningful content over URL-heavy lines
        assert "meaningful content" in result or len(result) > 0


# =============================================================================
# PAGE CLASSIFICATION TESTS
# =============================================================================

class TestPageClassification:
    """Tests for _classify_crawled_page function."""

    def test_classifies_product_update_by_path(self):
        """Should classify pages with product/blog paths as product_update."""
        result = _classify_crawled_page(
            "https://example.com/blog/new-feature-announcement",
            "We're excited to announce our new feature that improves performance by 50%."
        )

        assert result is not None
        assert result["type"] == "product_update"

    def test_classifies_pricing_by_path(self):
        """Should classify pages with pricing path as pricing_change."""
        result = _classify_crawled_page(
            "https://example.com/pricing",
            "Our pricing plans start at $99 per month with enterprise options available."
        )

        assert result is not None
        assert result["type"] == "pricing_change"

    def test_classifies_team_change_by_path(self):
        """Should classify pages with team/careers path as team_change."""
        result = _classify_crawled_page(
            "https://example.com/team",
            "Meet our leadership team including our CEO and CTO."
        )

        assert result is not None
        assert result["type"] == "team_change"

    def test_classifies_by_content_keywords(self):
        """Should classify by content keywords when path doesn't match."""
        result = _classify_crawled_page(
            "https://example.com/news/123",
            "The company has raised $50M in Series B funding led by top investors."
        )

        assert result is not None
        assert result["type"] == "funding_news"

    def test_returns_none_for_short_content(self):
        """Should return None for content too short to be meaningful."""
        result = _classify_crawled_page(
            "https://example.com/page",
            "Short"
        )
        assert result is None

    def test_returns_none_for_empty_content(self):
        """Should return None for empty content."""
        result = _classify_crawled_page(
            "https://example.com/page",
            ""
        )
        assert result is None

    def test_includes_url_in_result(self):
        """Should include the URL in the result."""
        result = _classify_crawled_page(
            "https://example.com/blog/post",
            "This is a meaningful blog post about new product features and improvements."
        )

        assert result is not None
        assert result["url"] == "https://example.com/blog/post"

    def test_extracts_description(self):
        """Should extract description from content."""
        result = _classify_crawled_page(
            "https://example.com/blog/post",
            "This is a meaningful blog post about new product features and improvements."
        )

        assert result is not None
        assert result["description"]
        assert len(result["description"]) > 0


# =============================================================================
# TAVILY CLIENT TESTS
# =============================================================================

class TestTavilyClient:
    """Tests for TavilyClient."""

    def test_missing_api_key_raises_error(self):
        """Creating client without API key should raise ValueError."""
        # Clear the API key from environment
        import os
        original_key = os.environ.pop("TAVILY_API_KEY", None)

        try:
            with pytest.raises(ValueError, match="Tavily API key required"):
                # Import fresh to avoid cached client
                from core.clients.tavily import TavilyClient as FreshTavilyClient
                FreshTavilyClient(api_key=None)
        finally:
            # Restore original key if it existed
            if original_key is not None:
                os.environ["TAVILY_API_KEY"] = original_key

    def test_crawl_normalizes_url(self, mock_tavily_sdk):
        """Should normalize URL without protocol."""
        mock_tavily_sdk._client.crawl.return_value = {"results": []}

        mock_tavily_sdk.crawl_company_website("stripe.com")

        # Check crawl was called with https:// prefix
        call_args = mock_tavily_sdk._client.crawl.call_args
        assert call_args[1]["url"].startswith("https://")

    def test_crawl_returns_website_intelligence(self, mock_tavily_sdk):
        """Should return WebsiteIntelligence object."""
        mock_tavily_sdk._client.crawl.return_value = {
            "results": [
                {
                    "url": "https://stripe.com/blog/new-feature",
                    "raw_content": "Stripe launches new payment feature with improved performance.",
                }
            ]
        }

        result = mock_tavily_sdk.crawl_company_website("stripe.com")

        assert isinstance(result, WebsiteIntelligence)
        assert result.domain

    def test_crawl_handles_empty_results(self, mock_tavily_sdk):
        """Should handle crawl with no results."""
        mock_tavily_sdk._client.crawl.return_value = {"results": []}

        result = mock_tavily_sdk.crawl_company_website("stripe.com")

        assert isinstance(result, WebsiteIntelligence)
        assert result.signals == []

    def test_crawl_filters_irrelevant_pages(self, mock_tavily_sdk):
        """Should filter pages without meaningful content."""
        mock_tavily_sdk._client.crawl.return_value = {
            "results": [
                {
                    "url": "https://stripe.com/blog/post",
                    "raw_content": "Short",  # Too short
                },
                {
                    "url": "https://stripe.com/blog/real-post",
                    "raw_content": "This is a meaningful blog post about new product features and improvements that Stripe is rolling out.",
                }
            ]
        }

        result = mock_tavily_sdk.crawl_company_website("stripe.com")

        # Should have filtered the short content
        assert len(result.signals) <= 1

    def test_crawl_raises_on_api_error(self, mock_tavily_sdk):
        """Should raise TavilyAPIError on API failure."""
        mock_tavily_sdk._client.crawl.side_effect = Exception("API Error")

        with pytest.raises(TavilyAPIError, match="Crawl failed"):
            mock_tavily_sdk.crawl_company_website("stripe.com")

    def test_crawl_classifies_multiple_pages(self, mock_tavily_sdk):
        """Should classify multiple crawled pages."""
        mock_tavily_sdk._client.crawl.return_value = {
            "results": [
                {
                    "url": "https://stripe.com/blog/new-feature",
                    "raw_content": "We're launching a new payment processing feature with 50% faster checkout.",
                },
                {
                    "url": "https://stripe.com/pricing",
                    "raw_content": "Our pricing plans include starter at $0 and pro at $25 per month.",
                },
            ]
        }

        result = mock_tavily_sdk.crawl_company_website("stripe.com")

        # Should have signals from both pages
        assert len(result.signals) >= 1
        signal_types = [s["type"] for s in result.signals]
        # At least one should be classified
        assert any(t in ["product_update", "pricing_change"] for t in signal_types)


# =============================================================================
# SIGNAL KEYWORDS TESTS
# =============================================================================

class TestSignalKeywords:
    """Tests for signal keyword configuration."""

    def test_product_update_keywords_exist(self):
        """Should have product_update keywords defined."""
        assert "product_update" in SIGNAL_KEYWORDS
        assert len(SIGNAL_KEYWORDS["product_update"]) > 0
        assert "launch" in SIGNAL_KEYWORDS["product_update"]

    def test_pricing_change_keywords_exist(self):
        """Should have pricing_change keywords defined."""
        assert "pricing_change" in SIGNAL_KEYWORDS
        assert "pricing" in SIGNAL_KEYWORDS["pricing_change"]

    def test_team_change_keywords_exist(self):
        """Should have team_change keywords defined."""
        assert "team_change" in SIGNAL_KEYWORDS
        assert "hire" in SIGNAL_KEYWORDS["team_change"]

    def test_funding_news_keywords_exist(self):
        """Should have funding_news keywords defined."""
        assert "funding_news" in SIGNAL_KEYWORDS
        assert "funding" in SIGNAL_KEYWORDS["funding_news"]


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

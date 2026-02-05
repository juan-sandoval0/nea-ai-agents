"""
Unit Tests for Pydantic Output Validation Schemas
=================================================
Tests for schema validation and edge case handling.

Run with:
    pytest tests/test_schemas.py -v
"""

import pytest
from datetime import datetime
from pydantic import ValidationError

from core.schemas import (
    KeySignalOutput,
    FounderOutput,
    CompanyCoreOutput,
    NewsArticleOutput,
    DataSourcesOutput,
    BriefingResultOutput,
    IngestResultOutput,
    validate_briefing_result,
    validate_ingest_result,
    validate_key_signal,
    validate_founder,
)


# =============================================================================
# KEY SIGNAL VALIDATION TESTS
# =============================================================================

class TestKeySignalOutput:
    """Tests for KeySignalOutput schema."""

    def test_valid_signal(self):
        """Should validate a correct signal."""
        signal = KeySignalOutput(
            company_id="stripe.com",
            signal_type="web_traffic",
            description="Strong traffic growth: +12.5% in 30 days",
            observed_at=datetime.utcnow().isoformat(),
            source="harmonic",
        )
        assert signal.company_id == "stripe.com"
        assert signal.signal_type == "web_traffic"

    def test_missing_required_fields(self):
        """Should reject signals missing required fields."""
        with pytest.raises(ValidationError):
            KeySignalOutput(
                company_id="stripe.com",
                # missing signal_type
                description="Some description",
                observed_at=datetime.utcnow().isoformat(),
                source="harmonic",
            )

    def test_empty_company_id(self):
        """Should reject empty company_id."""
        with pytest.raises(ValidationError):
            KeySignalOutput(
                company_id="",
                signal_type="web_traffic",
                description="Some description",
                observed_at=datetime.utcnow().isoformat(),
                source="harmonic",
            )

    def test_empty_description(self):
        """Should reject empty description."""
        with pytest.raises(ValidationError):
            KeySignalOutput(
                company_id="stripe.com",
                signal_type="web_traffic",
                description="",
                observed_at=datetime.utcnow().isoformat(),
                source="harmonic",
            )

    def test_unknown_signal_type_warns(self, caplog):
        """Unknown signal types should log a warning but still validate."""
        import logging
        caplog.set_level(logging.WARNING)

        signal = KeySignalOutput(
            company_id="stripe.com",
            signal_type="unknown_type",
            description="Some description",
            observed_at=datetime.utcnow().isoformat(),
            source="harmonic",
        )
        assert signal.signal_type == "unknown_type"
        assert "Unknown signal_type" in caplog.text

    def test_all_valid_signal_types(self):
        """All known signal types should validate without warning."""
        valid_types = [
            "web_traffic", "hiring", "funding",
            "website_update", "website_product", "website_pricing",
            "website_team", "website_news",
            "acquisition", "team_change", "product_launch",
            "partnership", "news_coverage",
        ]
        for signal_type in valid_types:
            signal = KeySignalOutput(
                company_id="test.com",
                signal_type=signal_type,
                description="Test description",
                observed_at=datetime.utcnow().isoformat(),
                source="harmonic",
            )
            assert signal.signal_type == signal_type


# =============================================================================
# FOUNDER VALIDATION TESTS
# =============================================================================

class TestFounderOutput:
    """Tests for FounderOutput schema."""

    def test_valid_founder(self):
        """Should validate a correct founder."""
        founder = FounderOutput(
            company_id="stripe.com",
            name="John Collison",
            role_title="President",
            linkedin_url="https://linkedin.com/in/johncollison",
            background="Co-founded Stripe with brother Patrick.",
            observed_at=datetime.utcnow().isoformat(),
            source="swarm",
        )
        assert founder.name == "John Collison"

    def test_founder_without_optional_fields(self):
        """Should validate founder without optional fields."""
        founder = FounderOutput(
            company_id="stripe.com",
            name="John Doe",
            observed_at=datetime.utcnow().isoformat(),
        )
        assert founder.name == "John Doe"
        assert founder.role_title is None
        assert founder.linkedin_url is None
        assert founder.background is None

    def test_empty_name_rejected(self):
        """Should reject empty name."""
        with pytest.raises(ValidationError):
            FounderOutput(
                company_id="stripe.com",
                name="",
                observed_at=datetime.utcnow().isoformat(),
            )

    def test_invalid_linkedin_url_warns(self, caplog):
        """Invalid LinkedIn URL should log warning but validate."""
        import logging
        caplog.set_level(logging.WARNING)

        founder = FounderOutput(
            company_id="stripe.com",
            name="John Doe",
            linkedin_url="https://twitter.com/johndoe",
            observed_at=datetime.utcnow().isoformat(),
        )
        assert founder.linkedin_url == "https://twitter.com/johndoe"
        assert "linkedin.com" in caplog.text


# =============================================================================
# COMPANY CORE VALIDATION TESTS
# =============================================================================

class TestCompanyCoreOutput:
    """Tests for CompanyCoreOutput schema."""

    def test_valid_company_core(self):
        """Should validate a complete company core."""
        company = CompanyCoreOutput(
            company_id="stripe.com",
            company_name="Stripe",
            founding_date="2010-01-01",
            hq="San Francisco, CA",
            employee_count=5000,
            total_funding=200000000.0,
            products="Payments infrastructure",
            customers="B2B",
            observed_at=datetime.utcnow().isoformat(),
        )
        assert company.company_name == "Stripe"

    def test_company_with_minimal_data(self):
        """Should validate company with only required fields."""
        company = CompanyCoreOutput(
            company_id="minimal.com",
            company_name="MinimalCo",
            observed_at=datetime.utcnow().isoformat(),
        )
        assert company.company_name == "MinimalCo"
        assert company.employee_count is None
        assert company.total_funding is None

    def test_negative_employee_count_rejected(self):
        """Should reject negative employee count."""
        with pytest.raises(ValidationError):
            CompanyCoreOutput(
                company_id="test.com",
                company_name="TestCo",
                employee_count=-100,
                observed_at=datetime.utcnow().isoformat(),
            )

    def test_negative_funding_rejected(self):
        """Should reject negative funding."""
        with pytest.raises(ValidationError):
            CompanyCoreOutput(
                company_id="test.com",
                company_name="TestCo",
                total_funding=-1000000,
                observed_at=datetime.utcnow().isoformat(),
            )


# =============================================================================
# NEWS ARTICLE VALIDATION TESTS
# =============================================================================

class TestNewsArticleOutput:
    """Tests for NewsArticleOutput schema."""

    def test_valid_news_article(self):
        """Should validate a complete news article."""
        article = NewsArticleOutput(
            company_id="stripe.com",
            article_headline="Stripe Raises $600M at $95B Valuation",
            outlet="TechCrunch",
            url="https://techcrunch.com/stripe-funding",
            published_date="2023-03-15",
            observed_at=datetime.utcnow().isoformat(),
            source="parallel",
        )
        assert article.article_headline == "Stripe Raises $600M at $95B Valuation"

    def test_empty_headline_rejected(self):
        """Should reject empty headline."""
        with pytest.raises(ValidationError):
            NewsArticleOutput(
                company_id="stripe.com",
                article_headline="",
                observed_at=datetime.utcnow().isoformat(),
            )

    def test_invalid_url_warns(self, caplog):
        """Invalid URL should log warning but validate."""
        import logging
        caplog.set_level(logging.WARNING)

        article = NewsArticleOutput(
            company_id="stripe.com",
            article_headline="Test Article",
            url="not-a-valid-url",
            observed_at=datetime.utcnow().isoformat(),
        )
        assert article.url == "not-a-valid-url"
        assert "http" in caplog.text


# =============================================================================
# DATA SOURCES VALIDATION TESTS
# =============================================================================

class TestDataSourcesOutput:
    """Tests for DataSourcesOutput schema."""

    def test_valid_data_sources(self):
        """Should validate data sources."""
        sources = DataSourcesOutput(
            company_core=True,
            founders=3,
            signals=5,
            news=10,
        )
        assert sources.company_core is True
        assert sources.founders == 3

    def test_defaults(self):
        """Should have sensible defaults."""
        sources = DataSourcesOutput()
        assert sources.company_core is False
        assert sources.founders == 0
        assert sources.signals == 0
        assert sources.news == 0

    def test_negative_counts_rejected(self):
        """Should reject negative counts."""
        with pytest.raises(ValidationError):
            DataSourcesOutput(founders=-1)


# =============================================================================
# BRIEFING RESULT VALIDATION TESTS
# =============================================================================

class TestBriefingResultOutput:
    """Tests for BriefingResultOutput schema."""

    def test_valid_successful_result(self):
        """Should validate a successful briefing result."""
        result = BriefingResultOutput(
            company_id="stripe.com",
            company_name="Stripe",
            markdown="## TL;DR\nStripe is a payments company.\n## Why This Meeting Matters\n- Important\n## Company Snapshot\n...",
            generated_at=datetime.utcnow().isoformat(),
            data_sources=DataSourcesOutput(company_core=True, founders=2, signals=5, news=3),
            success=True,
        )
        assert result.success is True
        assert result.company_name == "Stripe"

    def test_valid_failed_result(self):
        """Should validate a failed briefing result."""
        result = BriefingResultOutput(
            company_id="notfound.com",
            company_name=None,
            markdown=None,
            generated_at=datetime.utcnow().isoformat(),
            data_sources=DataSourcesOutput(),
            success=False,
            error="Company not found in database",
        )
        assert result.success is False
        assert result.error is not None

    def test_missing_sections_warns(self, caplog):
        """Missing expected sections should log warning."""
        import logging
        caplog.set_level(logging.WARNING)

        result = BriefingResultOutput(
            company_id="test.com",
            company_name="TestCo",
            markdown="This briefing is missing expected sections.",
            generated_at=datetime.utcnow().isoformat(),
            data_sources=DataSourcesOutput(company_core=True),
            success=True,
        )
        assert result.markdown is not None
        assert "missing expected sections" in caplog.text


# =============================================================================
# INGEST RESULT VALIDATION TESTS
# =============================================================================

class TestIngestResultOutput:
    """Tests for IngestResultOutput schema."""

    def test_valid_successful_ingest(self):
        """Should validate a successful ingest result."""
        result = IngestResultOutput(
            company_id="stripe.com",
            company_name="Stripe",
            company_core=True,
            founders_count=3,
            founders_enriched=2,
            signals_count=5,
            news_count=10,
            errors=[],
        )
        assert result.company_core is True
        assert result.founders_count == 3

    def test_valid_partial_ingest(self):
        """Should validate ingest with some failures."""
        result = IngestResultOutput(
            company_id="partial.com",
            company_name="PartialCo",
            company_core=True,
            founders_count=2,
            founders_enriched=0,
            signals_count=3,
            news_count=0,
            errors=["Founder backgrounds: SWARM_API_KEY not set"],
        )
        assert len(result.errors) == 1


# =============================================================================
# VALIDATION HELPER TESTS
# =============================================================================

class TestValidationHelpers:
    """Tests for validation helper functions."""

    def test_validate_briefing_result(self):
        """validate_briefing_result should work correctly."""
        raw_result = {
            "company_id": "test.com",
            "company_name": "TestCo",
            "markdown": "## TL;DR\nTest\n## Why This Meeting Matters\n...\n## Company Snapshot\n...",
            "generated_at": datetime.utcnow().isoformat(),
            "data_sources": {"company_core": True, "founders": 1, "signals": 2, "news": 0},
            "success": True,
            "error": None,
        }
        validated = validate_briefing_result(raw_result)
        assert isinstance(validated, BriefingResultOutput)
        assert validated.success is True

    def test_validate_ingest_result(self):
        """validate_ingest_result should work correctly."""
        raw_result = {
            "company_id": "test.com",
            "company_name": "TestCo",
            "company_core": True,
            "founders_count": 2,
            "founders_enriched": 1,
            "signals_count": 3,
            "news_count": 5,
            "errors": [],
        }
        validated = validate_ingest_result(raw_result)
        assert isinstance(validated, IngestResultOutput)

    def test_validate_key_signal(self):
        """validate_key_signal should work correctly."""
        raw_signal = {
            "company_id": "test.com",
            "signal_type": "hiring",
            "description": "Rapid hiring +15%",
            "observed_at": datetime.utcnow().isoformat(),
            "source": "harmonic",
        }
        validated = validate_key_signal(raw_signal)
        assert isinstance(validated, KeySignalOutput)

    def test_validate_founder(self):
        """validate_founder should work correctly."""
        raw_founder = {
            "company_id": "test.com",
            "name": "Jane Doe",
            "role_title": "CEO",
            "linkedin_url": "https://linkedin.com/in/janedoe",
            "background": "Ex-Google engineer",
            "observed_at": datetime.utcnow().isoformat(),
            "source": "swarm",
        }
        validated = validate_founder(raw_founder)
        assert isinstance(validated, FounderOutput)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

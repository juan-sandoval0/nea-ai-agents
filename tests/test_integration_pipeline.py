"""
Integration Tests for Meeting Briefing Pipeline
================================================
End-to-end tests with mocked external APIs.

Run with:
    pytest tests/test_integration_pipeline.py -v
"""

import pytest
from unittest.mock import Mock, patch, MagicMock
from datetime import datetime

from core.database import (
    CompanyCore,
    Founder,
    KeySignal,
    NewsArticle,
    CompanyBundle,
)


# =============================================================================
# FIXTURES
# =============================================================================

@pytest.fixture
def sample_company_core():
    """Sample company core data."""
    return CompanyCore(
        company_id="testco.com",
        company_name="TestCo",
        founding_date="2020-01-15",
        hq="San Francisco, CA",
        employee_count=150,
        total_funding=50000000.0,
        products="AI-powered productivity tools",
        customers="B2B SaaS",
        last_round_date="2023-06-01",
        last_round_funding=20000000.0,
        web_traffic_trend="+12.5% (30d)",
        hiring_firing="+8.3% (90d)",
        observed_at=datetime.utcnow().isoformat(),
        source_map={
            "company_name": "harmonic",
            "founding_date": "harmonic",
        },
    )


@pytest.fixture
def sample_founders():
    """Sample founders list."""
    return [
        Founder(
            company_id="testco.com",
            name="Jane Doe",
            role_title="CEO & Co-Founder",
            linkedin_url="https://linkedin.com/in/janedoe",
            background="Previously VP Engineering at Google. Stanford CS PhD. Founded DataFlow (acquired by Salesforce, 2018).",
            observed_at=datetime.utcnow().isoformat(),
            source="swarm",
        ),
        Founder(
            company_id="testco.com",
            name="John Smith",
            role_title="CTO & Co-Founder",
            linkedin_url="https://linkedin.com/in/johnsmith",
            background="Ex-Meta engineering lead. MIT Computer Science. 3 patents in ML optimization.",
            observed_at=datetime.utcnow().isoformat(),
            source="swarm",
        ),
    ]


@pytest.fixture
def sample_signals():
    """Sample key signals."""
    return [
        KeySignal(
            company_id="testco.com",
            signal_type="web_traffic",
            description="Strong traffic growth: +12.5% in 30 days",
            observed_at=datetime.utcnow().isoformat(),
            source="harmonic",
        ),
        KeySignal(
            company_id="testco.com",
            signal_type="hiring",
            description="Growing team: +8.3% headcount in 90 days (150 employees)",
            observed_at=datetime.utcnow().isoformat(),
            source="harmonic",
        ),
        KeySignal(
            company_id="testco.com",
            signal_type="funding",
            description="Last funding: $20,000,000 on 2023-06-01 (Series A)",
            observed_at=datetime.utcnow().isoformat(),
            source="harmonic",
        ),
        KeySignal(
            company_id="testco.com",
            signal_type="website_product",
            description="New AI assistant feature launched (source: testco.com/blog/ai-launch)",
            observed_at=datetime.utcnow().isoformat(),
            source="tavily",
        ),
    ]


@pytest.fixture
def sample_news():
    """Sample news articles."""
    return [
        NewsArticle(
            company_id="testco.com",
            article_headline="TestCo Raises $20M Series A to Expand AI Tools",
            outlet="TechCrunch",
            url="https://techcrunch.com/2023/06/01/testco-series-a",
            published_date="2023-06-01",
            observed_at=datetime.utcnow().isoformat(),
            source="parallel",
        ),
        NewsArticle(
            company_id="testco.com",
            article_headline="TestCo Named Top 50 AI Startup",
            outlet="Forbes",
            url="https://forbes.com/ai-startups-testco",
            published_date="2023-05-15",
            observed_at=datetime.utcnow().isoformat(),
            source="parallel",
        ),
    ]


@pytest.fixture
def sample_bundle(sample_company_core, sample_founders, sample_signals, sample_news):
    """Complete company bundle."""
    return CompanyBundle(
        company_core=sample_company_core,
        founders=sample_founders,
        key_signals=sample_signals,
        news=sample_news,
    )


# =============================================================================
# DATA FORMATTING TESTS
# =============================================================================

class TestDataFormatting:
    """Tests for briefing data formatting functions."""

    def test_format_company_snapshot_data(self, sample_company_core):
        """Should format company data correctly."""
        from agents.meeting_briefing.briefing_generator import format_company_snapshot_data

        result, last_updated = format_company_snapshot_data(sample_company_core)

        assert "TestCo" in result
        assert "San Francisco, CA" in result
        assert "150" in result
        assert "$50,000,000" in result
        assert "2020-01-15" in result
        assert last_updated is not None

    def test_format_company_snapshot_handles_missing(self):
        """Should handle missing fields gracefully."""
        from agents.meeting_briefing.briefing_generator import format_company_snapshot_data

        sparse_company = CompanyCore(
            company_id="sparse.com",
            company_name="SparseCo",
            observed_at=datetime.utcnow().isoformat(),
        )
        result, last_updated = format_company_snapshot_data(sparse_company)

        assert "SparseCo" in result
        assert "Not found in table" in result

    def test_format_founders_data(self, sample_founders):
        """Should format founders data correctly."""
        from agents.meeting_briefing.briefing_generator import format_founders_data

        result = format_founders_data(sample_founders)

        assert "Jane Doe" in result
        assert "CEO & Co-Founder" in result
        assert "Google" in result
        assert "John Smith" in result
        assert "Meta" in result

    def test_format_founders_empty_list(self):
        """Should handle empty founders list."""
        from agents.meeting_briefing.briefing_generator import format_founders_data

        result = format_founders_data([])

        assert "no founders" in result.lower()

    def test_format_signals_data(self, sample_signals):
        """Should format signals data correctly."""
        from agents.meeting_briefing.briefing_generator import format_signals_data

        result = format_signals_data(sample_signals)

        assert "WEB_TRAFFIC" in result
        assert "HIRING" in result
        assert "FUNDING" in result
        assert "WEBSITE_PRODUCT" in result

    def test_format_signals_skips_stale_placeholder(self, sample_signals):
        """Should skip pending_tavily when real tavily signals exist."""
        from agents.meeting_briefing.briefing_generator import format_signals_data

        # Add a stale placeholder
        sample_signals.append(KeySignal(
            company_id="testco.com",
            signal_type="website_update",
            description="Website change detection not yet available",
            observed_at=datetime.utcnow().isoformat(),
            source="pending_tavily",
        ))

        result = format_signals_data(sample_signals)

        # Should not include the stale placeholder since real tavily exists
        assert "not yet available" not in result.lower()

    def test_format_news_data(self, sample_news):
        """Should format news data correctly."""
        from agents.meeting_briefing.briefing_generator import format_news_data

        result = format_news_data(sample_news)

        assert "TechCrunch" in result
        assert "Forbes" in result
        assert "Series A" in result

    def test_format_news_empty(self):
        """Should handle empty news list."""
        from agents.meeting_briefing.briefing_generator import format_news_data

        result = format_news_data([])

        assert "not yet implemented" in result.lower()


# =============================================================================
# BRIEFING GENERATION TESTS
# =============================================================================

class TestBriefingGeneration:
    """Tests for briefing generation with mocked LLM."""

    def test_generate_briefing_success(self, sample_bundle):
        """Should generate briefing successfully with mocked LLM."""
        mock_response = Mock()
        mock_response.content = """## TL;DR
TestCo is an AI-powered productivity platform. Series A at $20M with strong traffic growth (+12.5%).

## Why This Meeting Matters
- Strong founding team with Google and Meta backgrounds
- Recent funding momentum (Series A closed June 2023)
- Positive growth signals across traffic and hiring

## Company Snapshot
| Field | Value |
|-------|-------|
| Founded | 2020-01-15 |
| HQ | San Francisco, CA |
| Employees | 150 |

## Founder Information
**Jane Doe** - CEO & Co-Founder
Previously VP Engineering at Google. Stanford CS PhD.

**John Smith** - CTO & Co-Founder
Ex-Meta engineering lead. MIT Computer Science.

## Key Signals
- [WEB_TRAFFIC] Strong traffic growth: +12.5% in 30 days
- [HIRING] Growing team: +8.3% headcount in 90 days

## In the News
- TestCo Raises $20M Series A (TechCrunch)

## For This Meeting
- Probe unit economics and path to profitability
- Understand AI differentiation vs competitors
"""
        mock_response.usage_metadata = {"input_tokens": 1000, "output_tokens": 500}

        mock_llm = Mock()
        mock_llm.invoke.return_value = mock_response

        with patch("agents.meeting_briefing.briefing_generator.get_company_bundle", return_value=sample_bundle):
            with patch("agents.meeting_briefing.briefing_generator.ChatOpenAI", return_value=mock_llm):
                with patch("agents.meeting_briefing.briefing_generator.get_tracker") as mock_tracker:
                    mock_tracker.return_value.log_api_call = Mock()
                    mock_tracker.return_value.log_usage = Mock()

                    from agents.meeting_briefing.briefing_generator import generate_briefing
                    result = generate_briefing("testco.com")

        assert result["success"] is True
        assert result["company_name"] == "TestCo"
        assert result["markdown"] is not None
        assert "TL;DR" in result["markdown"]
        assert result["data_sources"]["company_core"] is True
        assert result["data_sources"]["founders"] == 2
        assert result["data_sources"]["signals"] == 4
        assert result["data_sources"]["news"] == 2

    def test_generate_briefing_no_company_in_db(self):
        """Should return error when company not found."""
        empty_bundle = CompanyBundle(company_core=None)

        with patch("agents.meeting_briefing.briefing_generator.get_company_bundle", return_value=empty_bundle):
            from agents.meeting_briefing.briefing_generator import generate_briefing
            result = generate_briefing("notfound.com")

        assert result["success"] is False
        assert "not found" in result["error"].lower()

    def test_generate_briefing_llm_error(self, sample_bundle):
        """Should handle LLM errors gracefully."""
        mock_llm = Mock()
        mock_llm.invoke.side_effect = Exception("OpenAI API Error")

        with patch("agents.meeting_briefing.briefing_generator.get_company_bundle", return_value=sample_bundle):
            with patch("agents.meeting_briefing.briefing_generator.ChatOpenAI", return_value=mock_llm):
                with patch("agents.meeting_briefing.briefing_generator.get_tracker") as mock_tracker:
                    mock_tracker.return_value.log_api_call = Mock()
                    mock_tracker.return_value.log_usage = Mock()

                    from agents.meeting_briefing.briefing_generator import generate_briefing
                    result = generate_briefing("testco.com")

        assert result["success"] is False
        assert "LLM generation failed" in result["error"]


# =============================================================================
# INGEST -> BRIEFING FLOW TESTS
# =============================================================================

class TestIngestToBriefingFlow:
    """Tests for complete ingest to briefing flow."""

    def test_full_pipeline_mocked(self):
        """Test complete pipeline with all APIs mocked."""
        # Mock Harmonic company
        mock_harmonic_company = Mock()
        mock_harmonic_company.name = "TestCo"
        mock_harmonic_company.domain = "testco.com"
        mock_harmonic_company.description = "AI productivity tools"
        mock_harmonic_company.customer_type = "B2B"
        mock_harmonic_company.web_traffic_change_30d = 12.5
        mock_harmonic_company.headcount_change_90d = 8.3
        mock_harmonic_company.headcount = 150
        mock_harmonic_company.funding_last_date = "2023-06-01"
        mock_harmonic_company.funding_last_amount = 20000000
        mock_harmonic_company.funding_stage = "Series A"
        mock_harmonic_company.funding_total = 50000000
        mock_harmonic_company.founded_date = "2020-01-15"
        mock_harmonic_company.city = "San Francisco"
        mock_harmonic_company.state = "CA"
        mock_harmonic_company.country = "United States"
        mock_harmonic_company.raw_data = {"people": []}

        mock_harmonic = Mock()
        mock_harmonic.lookup_company.return_value = mock_harmonic_company

        # Mock database
        mock_db = Mock()
        mock_db.get_company.return_value = None  # First call returns None
        mock_db.upsert_company = Mock()
        mock_db.upsert_founders = Mock()
        mock_db.upsert_signals = Mock()
        mock_db.insert_news = Mock()
        mock_db.get_founders.return_value = []
        mock_db._get_connection = Mock()

        # Mock tracker
        mock_tracker_instance = Mock()
        mock_tracker_instance.log_api_call = Mock()
        mock_tracker_instance.log_usage = Mock()

        with patch("tools.company_tools.get_harmonic_client", return_value=mock_harmonic):
            with patch("tools.company_tools.get_db", return_value=mock_db):
                with patch("tools.company_tools.get_tavily_client", return_value=None):
                    with patch("tools.company_tools.get_parallel_client", return_value=None):
                        with patch("tools.company_tools.get_tracker", return_value=mock_tracker_instance):
                            with patch("agents.meeting_briefing.data_corrections.get_corrected_founders", return_value=None):
                                from tools.company_tools import ingest_company
                                ingest_result = ingest_company("testco.com")

        assert ingest_result["company_name"] == "TestCo"
        assert ingest_result["company_core"] is True
        assert ingest_result["signals_count"] >= 0

    def test_pipeline_partial_data(self):
        """Test pipeline handles partial data gracefully."""
        # Mock Harmonic with minimal data
        mock_harmonic_company = Mock()
        mock_harmonic_company.name = "MinimalCo"
        mock_harmonic_company.domain = "minimal.com"
        mock_harmonic_company.description = None
        mock_harmonic_company.customer_type = None
        mock_harmonic_company.web_traffic_change_30d = None
        mock_harmonic_company.headcount_change_90d = None
        mock_harmonic_company.headcount = None
        mock_harmonic_company.funding_last_date = None
        mock_harmonic_company.funding_last_amount = None
        mock_harmonic_company.funding_stage = None
        mock_harmonic_company.funding_total = None
        mock_harmonic_company.founded_date = None
        mock_harmonic_company.city = None
        mock_harmonic_company.state = None
        mock_harmonic_company.country = None
        mock_harmonic_company.raw_data = {"people": []}

        mock_harmonic = Mock()
        mock_harmonic.lookup_company.return_value = mock_harmonic_company

        mock_db = Mock()
        mock_db.get_company.return_value = None
        mock_db.upsert_company = Mock()
        mock_db.upsert_founders = Mock()
        mock_db.upsert_signals = Mock()
        mock_db.insert_news = Mock()
        mock_db.get_founders.return_value = []
        mock_db._get_connection = Mock()

        mock_tracker_instance = Mock()
        mock_tracker_instance.log_api_call = Mock()
        mock_tracker_instance.log_usage = Mock()

        with patch("tools.company_tools.get_harmonic_client", return_value=mock_harmonic):
            with patch("tools.company_tools.get_db", return_value=mock_db):
                with patch("tools.company_tools.get_tavily_client", return_value=None):
                    with patch("tools.company_tools.get_parallel_client", return_value=None):
                        with patch("tools.company_tools.get_tracker", return_value=mock_tracker_instance):
                            with patch("agents.meeting_briefing.data_corrections.get_corrected_founders", return_value=None):
                                from tools.company_tools import ingest_company
                                # Should not raise
                                result = ingest_company("minimal.com")

        assert result["company_name"] == "MinimalCo"
        assert result["company_core"] is True


# =============================================================================
# CITATION TESTS
# =============================================================================

class TestCitations:
    """Tests for citation and source tracking."""

    def test_signals_include_source(self, sample_signals):
        """All signals should include a source."""
        for signal in sample_signals:
            assert signal.source is not None
            assert signal.source in ["harmonic", "tavily", "parallel", "pending_tavily"]

    def test_founders_include_source(self, sample_founders):
        """All founders should include a source."""
        for founder in sample_founders:
            assert founder.source is not None

    def test_news_include_source(self, sample_news):
        """All news articles should include a source."""
        for article in sample_news:
            assert article.source is not None

    def test_data_sources_tracked_in_result(self, sample_bundle):
        """Briefing result should track data sources."""
        mock_response = Mock()
        mock_response.content = "Test briefing content"
        mock_response.usage_metadata = {"input_tokens": 100, "output_tokens": 50}

        mock_llm = Mock()
        mock_llm.invoke.return_value = mock_response

        with patch("agents.meeting_briefing.briefing_generator.get_company_bundle", return_value=sample_bundle):
            with patch("agents.meeting_briefing.briefing_generator.ChatOpenAI", return_value=mock_llm):
                with patch("agents.meeting_briefing.briefing_generator.get_tracker") as mock_tracker:
                    mock_tracker.return_value.log_api_call = Mock()
                    mock_tracker.return_value.log_usage = Mock()

                    from agents.meeting_briefing.briefing_generator import generate_briefing
                    result = generate_briefing("testco.com")

        assert "data_sources" in result
        assert result["data_sources"]["company_core"] is True
        assert result["data_sources"]["founders"] == 2
        assert result["data_sources"]["signals"] == 4
        assert result["data_sources"]["news"] == 2


# =============================================================================
# ERROR HANDLING TESTS
# =============================================================================

class TestErrorHandling:
    """Tests for error handling across the pipeline."""

    def test_ingest_captures_api_errors(self):
        """ingest_company should capture and report API errors."""
        from core.clients.harmonic import HarmonicAPIError

        mock_harmonic = Mock()
        mock_harmonic.lookup_company.side_effect = HarmonicAPIError("API Error", status_code=500)

        mock_tracker_instance = Mock()
        mock_tracker_instance.log_usage = Mock()

        with patch("tools.company_tools.get_harmonic_client", return_value=mock_harmonic):
            with patch("tools.company_tools.get_tracker", return_value=mock_tracker_instance):
                from tools.company_tools import ingest_company
                result = ingest_company("error.com")

        assert len(result["errors"]) > 0
        assert "Company profile" in result["errors"][0]

    def test_briefing_handles_missing_data_gracefully(self):
        """Briefing should handle sparse data without crashing."""
        sparse_bundle = CompanyBundle(
            company_core=CompanyCore(
                company_id="sparse.com",
                company_name="SparseCo",
                observed_at=datetime.utcnow().isoformat(),
            ),
            founders=[],
            key_signals=[],
            news=[],
        )

        mock_response = Mock()
        # Must be > 500 chars and have required sections to pass validation
        mock_response.content = """## TL;DR
SparseCo is a company with minimal available data.

## Why This Meeting Matters
- Opportunity to learn more about the company
- Initial due diligence meeting

## Company Snapshot
- Founded: Not found in table
- HQ: Not found in table
- Employees: Not found in table

## Founder Information
No founder data available

## Key Signals
No signals found in table.

## In the News
No recent news available (source not yet implemented)

## For This Meeting
- Understand the business model
- Identify key risks
- Determine next steps
"""
        mock_response.usage_metadata = {"input_tokens": 100, "output_tokens": 50}

        mock_llm = Mock()
        mock_llm.invoke.return_value = mock_response

        with patch("agents.meeting_briefing.briefing_generator.get_company_bundle", return_value=sparse_bundle):
            with patch("agents.meeting_briefing.briefing_generator.ChatOpenAI", return_value=mock_llm):
                with patch("agents.meeting_briefing.briefing_generator.get_tracker") as mock_tracker:
                    mock_tracker.return_value.log_api_call = Mock()
                    mock_tracker.return_value.log_usage = Mock()
                    mock_tracker.return_value.log_llm_call = Mock()

                    from agents.meeting_briefing.briefing_generator import generate_briefing
                    result = generate_briefing("sparse.com")

        assert result["success"] is True
        assert result["data_sources"]["founders"] == 0
        assert result["data_sources"]["signals"] == 0
        assert result["data_sources"]["news"] == 0


# =============================================================================
# SCHEMA VALIDATION TESTS
# =============================================================================

class TestSchemaValidation:
    """Tests for Pydantic schema validation."""

    def test_validate_briefing_result_success(self, sample_bundle):
        """Should validate a correct briefing result."""
        from core.schemas import validate_briefing_result

        briefing_result = {
            "success": True,
            "company_name": "TestCo",
            "company_id": "testco.com",
            "markdown": "## TL;DR\nTest\n## Why This Meeting\nTest\n## Company Snapshot\nTest",
            "generated_at": "2024-01-01T00:00:00",
            "data_sources": {
                "company_core": True,
                "founders": 2,
                "signals": 4,
                "news": 2,
            },
        }

        validated = validate_briefing_result(briefing_result)
        assert validated.success is True
        assert validated.company_name == "TestCo"

    def test_validate_briefing_result_failure(self):
        """Should validate a failed briefing result."""
        from core.schemas import validate_briefing_result

        briefing_result = {
            "success": False,
            "error": "Company not found in database",
            "company_id": "notfound.com",
            "generated_at": "2024-01-01T00:00:00",
            "data_sources": {
                "company_core": False,
                "founders": 0,
                "signals": 0,
                "news": 0,
            },
        }

        validated = validate_briefing_result(briefing_result)
        assert validated.success is False
        assert "not found" in validated.error

    def test_validate_ingest_result(self):
        """Should validate an ingest result."""
        from core.schemas import validate_ingest_result

        ingest_result = {
            "company_id": "testco.com",
            "company_name": "TestCo",
            "company_core": True,
            "founders_count": 2,
            "signals_count": 4,
            "news_count": 2,
            "errors": [],
        }

        validated = validate_ingest_result(ingest_result)
        assert validated.company_name == "TestCo"
        assert validated.founders_count == 2


# =============================================================================
# GRACEFUL DEGRADATION TESTS
# =============================================================================

class TestGracefulDegradation:
    """Tests for graceful API degradation."""

    def test_ingest_without_tavily(self):
        """Should complete ingest when Tavily key is missing."""
        mock_harmonic_company = Mock()
        mock_harmonic_company.name = "TestCo"
        mock_harmonic_company.domain = "testco.com"
        mock_harmonic_company.description = "Test company"
        mock_harmonic_company.customer_type = "B2B"
        mock_harmonic_company.web_traffic_change_30d = 10.0
        mock_harmonic_company.headcount_change_90d = 5.0
        mock_harmonic_company.headcount = 100
        mock_harmonic_company.funding_last_date = None
        mock_harmonic_company.funding_last_amount = None
        mock_harmonic_company.funding_stage = None
        mock_harmonic_company.funding_total = None
        mock_harmonic_company.founded_date = None
        mock_harmonic_company.city = None
        mock_harmonic_company.state = None
        mock_harmonic_company.country = None
        mock_harmonic_company.raw_data = {"people": []}

        mock_harmonic = Mock()
        mock_harmonic.lookup_company.return_value = mock_harmonic_company

        mock_db = Mock()
        mock_db.get_company.return_value = None
        mock_db.upsert_company = Mock()
        mock_db.upsert_founders = Mock()
        mock_db.upsert_signals = Mock()
        mock_db.insert_news = Mock()
        mock_db.get_founders.return_value = []
        mock_db._get_connection = Mock()

        mock_tracker_instance = Mock()
        mock_tracker_instance.log_api_call = Mock()
        mock_tracker_instance.log_usage = Mock()

        # Tavily returns None (key missing)
        with patch("tools.company_tools.get_harmonic_client", return_value=mock_harmonic):
            with patch("tools.company_tools.get_db", return_value=mock_db):
                with patch("tools.company_tools.get_tavily_client", return_value=None):
                    with patch("tools.company_tools.get_parallel_client", return_value=None):
                        with patch("tools.company_tools.get_tracker", return_value=mock_tracker_instance):
                            with patch("agents.meeting_briefing.data_corrections.get_corrected_founders", return_value=None):
                                from tools.company_tools import ingest_company
                                result = ingest_company("testco.com")

        # Should succeed even without Tavily
        assert result["company_name"] == "TestCo"
        assert result["company_core"] is True

    def test_ingest_without_parallel(self):
        """Should complete ingest when Parallel key is missing."""
        mock_harmonic_company = Mock()
        mock_harmonic_company.name = "TestCo"
        mock_harmonic_company.domain = "testco.com"
        mock_harmonic_company.description = "Test company"
        mock_harmonic_company.customer_type = "B2B"
        mock_harmonic_company.web_traffic_change_30d = None
        mock_harmonic_company.headcount_change_90d = None
        mock_harmonic_company.headcount = None
        mock_harmonic_company.funding_last_date = None
        mock_harmonic_company.funding_last_amount = None
        mock_harmonic_company.funding_stage = None
        mock_harmonic_company.funding_total = None
        mock_harmonic_company.founded_date = None
        mock_harmonic_company.city = None
        mock_harmonic_company.state = None
        mock_harmonic_company.country = None
        mock_harmonic_company.raw_data = {"people": []}

        mock_harmonic = Mock()
        mock_harmonic.lookup_company.return_value = mock_harmonic_company

        mock_db = Mock()
        mock_db.get_company.return_value = None
        mock_db.upsert_company = Mock()
        mock_db.upsert_founders = Mock()
        mock_db.upsert_signals = Mock()
        mock_db.insert_news = Mock()
        mock_db.get_founders.return_value = []
        mock_db._get_connection = Mock()

        mock_tracker_instance = Mock()
        mock_tracker_instance.log_api_call = Mock()
        mock_tracker_instance.log_usage = Mock()

        with patch("tools.company_tools.get_harmonic_client", return_value=mock_harmonic):
            with patch("tools.company_tools.get_db", return_value=mock_db):
                with patch("tools.company_tools.get_tavily_client", return_value=None):
                    with patch("tools.company_tools.get_parallel_client", return_value=None):
                        with patch("tools.company_tools.get_tracker", return_value=mock_tracker_instance):
                            with patch("agents.meeting_briefing.data_corrections.get_corrected_founders", return_value=None):
                                from tools.company_tools import ingest_company
                                result = ingest_company("testco.com")

        # Should succeed even without Parallel
        assert result["company_name"] == "TestCo"
        # News count should be 0 without Parallel
        assert result["news_count"] == 0


# =============================================================================
# EVALUATION FLOW INTEGRATION TESTS
# =============================================================================

class TestEvaluationFlowIntegration:
    """Integration tests for the evaluation flow."""

    def test_evaluation_run_full_flow(self):
        """Test complete evaluation run with mocked data."""
        from evaluation.run_eval import run_full_evaluation

        # Mock the evaluation module functions
        mock_eval_result = Mock()
        mock_eval_result.entity_resolution = Mock()
        mock_eval_result.entity_resolution.to_dict.return_value = {
            "correct": True,
            "confidence": 0.95,
        }
        mock_eval_result.entity_resolution.correct = True
        mock_eval_result.signal_coverage = Mock()
        mock_eval_result.signal_coverage.to_dict.return_value = {
            "coverage_rate": 0.8,
            "categories_found": ["product", "funding", "team"],
            "categories_missing": ["pricing"],
        }
        mock_eval_result.signal_coverage.coverage_rate = 0.8
        mock_eval_result.retrieval_accuracy = []

        with patch("evaluation.run_eval.run_evaluation", return_value=mock_eval_result):
            with patch("evaluation.run_eval.get_quality_benchmark", return_value=None):
                with patch("evaluation.run_eval.get_failure_stats", return_value=None):
                    with patch("evaluation.run_eval.identify_failure_patterns", return_value=[]):
                        with patch("evaluation.run_eval.get_cost_summary", return_value={"total_cost": 0.10, "cost_per_company": 0.05}):
                            with patch("evaluation.run_eval.get_workflow_timing", return_value={"estimated_total_per_company_seconds": 5.0}):
                                with patch("evaluation.run_eval.save_cost_record"):
                                    result = run_full_evaluation(
                                        company_ids=["test.com"],
                                        days=30,
                                    )

        assert result.entity_accuracy == 1.0
        assert result.avg_signal_coverage == 0.8
        assert len(result.errors) == 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

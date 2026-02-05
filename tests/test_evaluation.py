"""
Tests for Evaluation Framework
==============================
Tests for evaluation metrics, quality scoring, failure analysis, and cost tracking.

Run with:
    pytest tests/test_evaluation.py -v
"""

import pytest
import tempfile
from pathlib import Path
from datetime import datetime

from core.evaluation import (
    EntityResolutionResult,
    RetrievalAccuracyResult,
    SignalCoverageResult,
    EvaluationResult,
    GroundTruth,
    evaluate_entity_resolution,
    evaluate_retrieval_accuracy,
    _fuzzy_name_match,
    _domain_matches,
    _content_references_company,
    SignalCategory,
)

from core.quality_scoring import (
    QualityScore,
    BriefingQualityEvaluation,
    submit_quality_score,
    get_quality_scores,
    get_quality_stats,
    get_score_rubric,
    validate_score,
    CLARITY_RUBRIC,
)

from core.failure_analysis import (
    FailureCategory,
    FailureRecord,
    log_failure,
    get_failures,
    get_failure_stats,
    identify_failure_patterns,
    generate_failure_report,
)

from core.tracking import (
    calculate_api_cost,
    get_cost_summary,
    project_costs_at_scale,
    SERVICE_COSTS,
    save_cost_record,
    load_cost_records,
    export_cost_summary,
    export_evaluation_costs,
    CostRecord,
)


# =============================================================================
# ENTITY RESOLUTION TESTS
# =============================================================================

class TestFuzzyNameMatch:
    """Tests for company name matching."""

    def test_exact_match(self):
        """Exact names should return 1.0."""
        assert _fuzzy_name_match("Stripe", "Stripe") == 1.0

    def test_case_insensitive(self):
        """Should be case insensitive."""
        assert _fuzzy_name_match("stripe", "STRIPE") == 1.0

    def test_suffix_removal(self):
        """Should ignore common suffixes."""
        score = _fuzzy_name_match("Stripe Inc", "Stripe")
        assert score >= 0.9

    def test_partial_match(self):
        """Partial matches should return lower scores."""
        score = _fuzzy_name_match("Stripe", "Stripe Payments")
        assert 0.5 <= score <= 1.0

    def test_no_match(self):
        """Completely different names should return low scores."""
        score = _fuzzy_name_match("Stripe", "Airbnb")
        assert score < 0.5

    def test_empty_strings(self):
        """Empty strings should return 0."""
        assert _fuzzy_name_match("", "Stripe") == 0.0
        assert _fuzzy_name_match("Stripe", "") == 0.0


class TestDomainMatches:
    """Tests for domain matching."""

    def test_exact_domain(self):
        """Exact domains should match."""
        assert _domain_matches("stripe.com", "stripe.com") is True

    def test_www_prefix(self):
        """Should ignore www prefix."""
        assert _domain_matches("www.stripe.com", "stripe.com") is True

    def test_https_prefix(self):
        """Should ignore https prefix."""
        assert _domain_matches("https://stripe.com", "stripe.com") is True

    def test_full_url(self):
        """Should handle full URLs."""
        assert _domain_matches("https://www.stripe.com/", "stripe.com") is True

    def test_different_domains(self):
        """Different domains should not match."""
        assert _domain_matches("stripe.com", "airbnb.com") is False


class TestContentReferencesCompany:
    """Tests for content relevance checking."""

    def test_name_in_content(self):
        """Should detect company name in content."""
        assert _content_references_company(
            "Stripe announced new payments feature",
            "",
            "Stripe",
            "stripe.com"
        ) is True

    def test_domain_in_url(self):
        """Should detect domain in URL."""
        assert _content_references_company(
            "Some generic content",
            "https://stripe.com/blog/post",
            "Stripe",
            "stripe.com"
        ) is True

    def test_no_reference(self):
        """Should return False when no reference found."""
        assert _content_references_company(
            "Airbnb announced new feature",
            "https://airbnb.com/blog",
            "Stripe",
            "stripe.com"
        ) is False


class TestEntityResolutionResult:
    """Tests for EntityResolutionResult."""

    def test_create_result(self):
        """Should create entity resolution result."""
        result = EntityResolutionResult(
            company_id="stripe.com",
            intended_company="Stripe",
            resolved_company="Stripe Inc",
            correct=True,
            confidence=0.95,
        )
        assert result.correct is True
        assert result.confidence == 0.95

    def test_to_dict(self):
        """Should convert to dictionary."""
        result = EntityResolutionResult(
            company_id="stripe.com",
            intended_company="Stripe",
            resolved_company="Stripe",
            correct=True,
            confidence=1.0,
        )
        d = result.to_dict()
        assert d["company_id"] == "stripe.com"
        assert d["correct"] is True


# =============================================================================
# RETRIEVAL ACCURACY TESTS
# =============================================================================

class TestRetrievalAccuracy:
    """Tests for retrieval accuracy evaluation."""

    def test_all_relevant(self):
        """Should calculate 100% precision when all items relevant."""
        result = evaluate_retrieval_accuracy(
            company_id="stripe.com",
            source="tavily",
            retrieved_items=[
                {"content": "Stripe payment processing", "url": "https://stripe.com/docs"},
                {"content": "Stripe API documentation", "url": "https://stripe.com/api"},
            ],
            ground_truth_name="Stripe",
        )
        assert result.precision == 1.0
        assert result.relevant_count == 2
        assert result.irrelevant_count == 0

    def test_mixed_relevance(self):
        """Should calculate correct precision with mixed relevance."""
        result = evaluate_retrieval_accuracy(
            company_id="stripe.com",
            source="parallel",
            retrieved_items=[
                {"content": "Stripe launches new feature", "url": ""},
                {"content": "Airbnb growth metrics", "url": ""},  # Irrelevant
            ],
            ground_truth_name="Stripe",
        )
        assert result.precision == 0.5
        assert result.relevant_count == 1
        assert result.irrelevant_count == 1

    def test_empty_results(self):
        """Should handle empty results gracefully."""
        result = evaluate_retrieval_accuracy(
            company_id="stripe.com",
            source="tavily",
            retrieved_items=[],
        )
        assert result.precision == 1.0  # No errors possible
        assert result.total_retrieved == 0


# =============================================================================
# SIGNAL COVERAGE TESTS
# =============================================================================

class TestSignalCategory:
    """Tests for signal categories."""

    def test_signal_categories_exist(self):
        """All signal categories should be defined."""
        expected = ["product", "pricing", "team", "news", "funding", "traction", "website"]
        for cat in expected:
            assert cat in [c.value for c in SignalCategory]


class TestSignalCoverageResult:
    """Tests for SignalCoverageResult."""

    def test_coverage_calculation(self):
        """Should calculate coverage rate correctly."""
        result = SignalCoverageResult(
            company_id="stripe.com",
            categories_expected=["product", "team", "funding", "news"],
            categories_found=["product", "funding"],
            categories_missing=["team", "news"],
            coverage_rate=0.5,
        )
        assert result.coverage_rate == 0.5
        assert len(result.categories_missing) == 2


# =============================================================================
# QUALITY SCORING TESTS
# =============================================================================

class TestQualityScore:
    """Tests for quality scoring."""

    def test_valid_score(self):
        """Should accept valid scores."""
        score = QualityScore(
            company_id="stripe.com",
            evaluator="test_user",
            clarity=4,
            correctness=5,
            usefulness=4,
        )
        assert score.clarity == 4
        assert score.average_score == 4.333333333333333

    def test_invalid_score_rejected(self):
        """Should reject scores outside 1-5 range."""
        with pytest.raises(ValueError):
            QualityScore(
                company_id="stripe.com",
                evaluator="test_user",
                clarity=6,  # Invalid
                correctness=5,
                usefulness=4,
            )

    def test_score_with_comments(self):
        """Should store comments."""
        score = QualityScore(
            company_id="stripe.com",
            evaluator="test_user",
            clarity=4,
            correctness=4,
            usefulness=5,
            comments="Great briefing, very useful",
        )
        assert score.comments == "Great briefing, very useful"


class TestQualityScoringDB:
    """Tests for quality scoring database operations."""

    @pytest.fixture
    def temp_db(self):
        """Create temporary database for testing."""
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            yield Path(f.name)

    def test_submit_and_retrieve(self, temp_db):
        """Should submit and retrieve quality scores."""
        submit_quality_score(
            company_id="test.com",
            evaluator="user1",
            clarity=4,
            correctness=5,
            usefulness=4,
            db_path=temp_db,
        )

        scores = get_quality_scores("test.com", db_path=temp_db)
        assert len(scores) == 1
        assert scores[0].clarity == 4

    def test_multiple_evaluators(self, temp_db):
        """Should handle multiple evaluators."""
        submit_quality_score("test.com", "user1", 4, 4, 4, db_path=temp_db)
        submit_quality_score("test.com", "user2", 5, 5, 5, db_path=temp_db)

        stats = get_quality_stats("test.com", db_path=temp_db)
        assert stats.num_evaluations == 2
        assert stats.avg_clarity == 4.5


class TestScoreRubric:
    """Tests for scoring rubric."""

    def test_rubric_exists(self):
        """Rubric should exist for all dimensions."""
        rubric = get_score_rubric()
        assert "clarity" in rubric
        assert "correctness" in rubric
        assert "usefulness" in rubric

    def test_rubric_has_all_levels(self):
        """Each rubric should have 5 levels."""
        for level in range(1, 6):
            assert level in CLARITY_RUBRIC

    def test_validate_score(self):
        """Should validate scores correctly."""
        valid, guidance = validate_score("clarity", 4)
        assert valid is True
        assert len(guidance) > 0

        valid, guidance = validate_score("clarity", 10)
        assert valid is False


# =============================================================================
# FAILURE ANALYSIS TESTS
# =============================================================================

class TestFailureCategory:
    """Tests for failure categories."""

    def test_all_categories_defined(self):
        """All expected categories should be defined."""
        expected = [
            "naming_ambiguity",
            "domain_mapping",
            "missing_harmonic",
            "tangential_content",
            "api_error",
        ]
        for cat in expected:
            assert cat in [c.value for c in FailureCategory]


class TestFailureLogging:
    """Tests for failure logging."""

    @pytest.fixture
    def temp_db(self):
        """Create temporary database for testing."""
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            yield Path(f.name)

    def test_log_failure(self, temp_db):
        """Should log a failure."""
        failure_id = log_failure(
            company_id="test.com",
            category=FailureCategory.NAMING_AMBIGUITY,
            description="Confused with Test Corp",
            severity="medium",
            db_path=temp_db,
        )
        assert failure_id > 0

    def test_get_failures(self, temp_db):
        """Should retrieve failures."""
        log_failure("test.com", FailureCategory.API_ERROR, "API timeout", db_path=temp_db)
        log_failure("test.com", FailureCategory.API_ERROR, "Rate limit", db_path=temp_db)

        failures = get_failures(company_id="test.com", db_path=temp_db)
        assert len(failures) == 2

    def test_get_failures_by_category(self, temp_db):
        """Should filter by category."""
        log_failure("test.com", FailureCategory.API_ERROR, "Error 1", db_path=temp_db)
        log_failure("test.com", FailureCategory.NAMING_AMBIGUITY, "Ambiguity 1", db_path=temp_db)

        failures = get_failures(
            category=FailureCategory.API_ERROR,
            db_path=temp_db,
        )
        assert len(failures) == 1
        assert failures[0].category == FailureCategory.API_ERROR


class TestFailureStats:
    """Tests for failure statistics."""

    @pytest.fixture
    def temp_db(self):
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            yield Path(f.name)

    def test_get_stats(self, temp_db):
        """Should compute failure statistics."""
        log_failure("a.com", FailureCategory.API_ERROR, "Error", db_path=temp_db)
        log_failure("a.com", FailureCategory.API_ERROR, "Error", db_path=temp_db)
        log_failure("b.com", FailureCategory.NAMING_AMBIGUITY, "Ambiguity", db_path=temp_db)

        stats = get_failure_stats(db_path=temp_db)
        assert stats.total_failures == 3
        assert stats.failures_by_category["api_error"] == 2

    def test_identify_patterns(self, temp_db):
        """Should identify failure patterns."""
        for _ in range(3):
            log_failure("test.com", FailureCategory.API_ERROR, "Timeout", db_path=temp_db)

        patterns = identify_failure_patterns(db_path=temp_db)
        assert len(patterns) >= 1
        assert patterns[0].frequency >= 3


# =============================================================================
# COST TRACKING TESTS
# =============================================================================

class TestCostCalculation:
    """Tests for cost calculation."""

    def test_openai_cost(self):
        """Should calculate OpenAI costs correctly."""
        cost = calculate_api_cost(
            service="openai",
            tokens_in=1000,
            tokens_out=500,
        )
        # Expected: (1000/1000 * 0.0005) + (500/1000 * 0.0015) = 0.0005 + 0.00075 = 0.00125
        assert cost == pytest.approx(0.00125, rel=0.01)

    def test_tavily_cost_credits(self):
        """Should calculate Tavily costs from credits."""
        cost = calculate_api_cost(
            service="tavily",
            credits_used=2,
        )
        assert cost == pytest.approx(0.02, rel=0.01)

    def test_tavily_cost_default(self):
        """Should use default Tavily credits when not specified."""
        cost = calculate_api_cost(service="tavily")
        assert cost == pytest.approx(0.02, rel=0.01)  # 2 credits * $0.01

    def test_news_api_cost(self):
        """Should calculate NewsAPI costs correctly."""
        cost = calculate_api_cost(service="news_api", requests=1)
        assert cost == pytest.approx(0.01, rel=0.01)

    def test_unknown_service(self):
        """Should return 0 for unknown services."""
        cost = calculate_api_cost(service="unknown_service")
        assert cost == 0.0


class TestCostProjections:
    """Tests for cost projections."""

    def test_project_costs(self):
        """Should project costs at scale."""
        projection = project_costs_at_scale(100, include_news=True)

        assert "monthly_cost" in projection
        assert "annual_cost" in projection
        assert "cost_per_company" in projection
        assert projection["annual_cost"] == projection["monthly_cost"] * 12

    def test_project_without_news(self):
        """Should project lower costs without news research."""
        with_news = project_costs_at_scale(100, include_news=True)
        without_news = project_costs_at_scale(100, include_news=False)

        assert without_news["monthly_cost"] < with_news["monthly_cost"]


class TestServiceCosts:
    """Tests for service cost definitions."""

    def test_all_services_defined(self):
        """All expected services should have cost definitions."""
        # Services: Tavily (website), Harmonic (company), OpenAI (LLM), NewsAPI (news)
        expected = ["tavily", "openai", "harmonic", "news_api"]
        for service in expected:
            assert service in SERVICE_COSTS


# =============================================================================
# GROUND TRUTH TESTS
# =============================================================================

class TestGroundTruth:
    """Tests for ground truth data model."""

    def test_create_ground_truth(self):
        """Should create ground truth data."""
        gt = GroundTruth(
            company_id="stripe.com",
            company_name="Stripe",
            domain="stripe.com",
            founding_date="2010-01-01",
            founders=["Patrick Collison", "John Collison"],
        )
        assert gt.company_name == "Stripe"
        assert len(gt.founders) == 2

    def test_from_dict(self):
        """Should create from dictionary."""
        data = {
            "company_id": "stripe.com",
            "company_name": "Stripe",
            "domain": "stripe.com",
        }
        gt = GroundTruth.from_dict(data)
        assert gt.company_name == "Stripe"


# =============================================================================
# COST PERSISTENCE TESTS
# =============================================================================

class TestCostPersistence:
    """Tests for cost JSON/CSV persistence."""

    @pytest.fixture
    def temp_dir(self):
        """Create temporary directory for cost files."""
        with tempfile.TemporaryDirectory() as d:
            yield Path(d)

    def test_save_cost_record(self, temp_dir):
        """Should save cost record to JSON and CSV."""
        record = save_cost_record(
            company_id="test.com",
            service="tavily",
            operation="crawl",
            cost=0.02,
            output_dir=temp_dir,
        )

        assert record.company_id == "test.com"
        assert record.service == "tavily"
        assert record.cost == 0.02

        # Check JSON file exists
        json_path = temp_dir / "cost_log.jsonl"
        assert json_path.exists()

        # Check CSV file exists
        csv_path = temp_dir / "cost_log.csv"
        assert csv_path.exists()

    def test_load_cost_records(self, temp_dir):
        """Should load cost records from JSON."""
        # Save some records
        save_cost_record("a.com", "tavily", "crawl", 0.02, output_dir=temp_dir)
        save_cost_record("b.com", "openai", "briefing", 0.05, output_dir=temp_dir)
        save_cost_record("a.com", "parallel", "search", 0.01, output_dir=temp_dir)

        # Load all
        records = load_cost_records(output_dir=temp_dir)
        assert len(records) == 3

        # Filter by company
        records = load_cost_records(output_dir=temp_dir, company_id="a.com")
        assert len(records) == 2

        # Filter by service
        records = load_cost_records(output_dir=temp_dir, service="tavily")
        assert len(records) == 1

    def test_export_cost_summary_json(self, temp_dir):
        """Should export cost summary to JSON."""
        output_path = temp_dir / "summary.json"
        export_cost_summary(output_path, days=30, format="json")

        assert output_path.exists()
        with open(output_path) as f:
            data = json.load(f)
        assert "total_cost" in data
        assert "period_days" in data

    def test_export_cost_summary_csv(self, temp_dir):
        """Should export cost summary to CSV."""
        output_path = temp_dir / "summary.csv"
        export_cost_summary(output_path, days=30, format="csv")

        assert output_path.exists()

    def test_export_evaluation_costs(self, temp_dir):
        """Should export per-company evaluation costs."""
        # Save some cost records
        save_cost_record("stripe.com", "tavily", "crawl", 0.02, output_dir=temp_dir)
        save_cost_record("stripe.com", "openai", "briefing", 0.03, output_dir=temp_dir)
        save_cost_record("airbnb.com", "tavily", "crawl", 0.02, output_dir=temp_dir)

        output_path = temp_dir / "eval_costs.json"
        result = export_evaluation_costs(
            company_ids=["stripe.com", "airbnb.com"],
            output_path=output_path,
            format="json",
            output_dir=temp_dir,
        )

        assert result["total_companies"] == 2
        assert result["aggregate_cost"] > 0
        assert output_path.exists()


# =============================================================================
# CITATION VALIDATION TESTS
# =============================================================================

class TestCitationValidation:
    """Tests for citation presence validation."""

    def test_no_sources_no_citations(self):
        """No sources should result in valid (nothing to cite)."""
        from evaluation.run_eval import validate_citations

        result = validate_citations(
            company_id="test.com",
            briefing_text="This is a briefing about Test Company.",
            source_documents=[],
        )

        assert result["valid"] is True
        assert result["has_sources"] is False

    def test_detect_hallucinated_citations(self):
        """Should detect hallucinated citations when no sources provided."""
        from evaluation.run_eval import validate_citations

        result = validate_citations(
            company_id="test.com",
            briefing_text="According to TechCrunch, the company raised $10M. Source: fake.com",
            source_documents=[],
        )

        assert result["valid"] is False
        assert "Hallucinated citations" in result["notes"]

    def test_citations_found_via_url(self):
        """Should detect citations via URL matching."""
        from evaluation.run_eval import validate_citations

        result = validate_citations(
            company_id="test.com",
            briefing_text="The company announced growth (techcrunch.com/article). More info at stripe.com/blog.",
            source_documents=[
                {"url": "https://techcrunch.com/article", "title": "Tech Article"},
                {"url": "https://stripe.com/blog", "title": "Stripe Blog"},
            ],
        )

        assert result["citations_found"] == 2
        assert result["citation_rate"] == 1.0
        assert result["valid"] is True

    def test_citations_found_via_domain(self):
        """Should detect citations via domain matching."""
        from evaluation.run_eval import validate_citations

        result = validate_citations(
            company_id="test.com",
            briefing_text="According to techcrunch.com, the company is growing.",
            source_documents=[
                {"url": "https://techcrunch.com/some/article", "title": "Article"},
            ],
        )

        assert result["citations_found"] == 1
        assert result["valid"] is True

    def test_missing_citations_flagged(self):
        """Should flag missing citations."""
        from evaluation.run_eval import validate_citations

        result = validate_citations(
            company_id="test.com",
            briefing_text="The company is doing well.",
            source_documents=[
                {"url": "https://techcrunch.com/article", "title": "Tech Article"},
                {"url": "https://forbes.com/story", "title": "Forbes Story"},
            ],
        )

        assert result["citations_found"] == 0
        assert result["citation_rate"] == 0.0
        assert len(result["missing_citations"]) == 2
        assert result["valid"] is False

    def test_partial_citations_invalid_strict(self):
        """Partial citations should be invalid under strict validation (100% required)."""
        from evaluation.run_eval import validate_citations

        result = validate_citations(
            company_id="test.com",
            briefing_text="According to techcrunch.com, the company raised funding.",
            source_documents=[
                {"url": "https://techcrunch.com/article", "title": "Tech Article"},
                {"url": "https://forbes.com/story", "title": "Forbes Story"},  # Not cited
            ],
        )

        assert result["citations_found"] == 1
        assert result["citation_rate"] == 0.5
        assert len(result["missing_citations"]) == 1
        # Strict validation: partial citations are INVALID
        assert result["valid"] is False
        assert "INVALID" in result["notes"]

    def test_empty_briefing_text(self):
        """Should handle empty briefing text."""
        from evaluation.run_eval import validate_citations

        result = validate_citations(
            company_id="test.com",
            briefing_text="",
            source_documents=[{"url": "https://example.com", "title": "Example"}],
        )

        assert result["valid"] is True
        assert "No briefing text" in result["notes"]


# =============================================================================
# EVALUATION RUN TESTS
# =============================================================================

class TestEvaluationRun:
    """Tests for the unified evaluation entrypoint."""

    def test_evaluation_run_result_to_dict(self):
        """Should convert result to dictionary."""
        from evaluation.run_eval import EvaluationRunResult

        result = EvaluationRunResult(
            run_id="test123",
            timestamp="2024-01-01T00:00:00",
            companies_evaluated=["stripe.com"],
            period_days=30,
            entity_accuracy=0.95,
            avg_signal_coverage=0.8,
        )

        d = result.to_dict()
        assert d["run_id"] == "test123"
        assert d["entity_accuracy"] == 0.95

    def test_evaluation_run_result_summary(self):
        """Should generate text summary."""
        from evaluation.run_eval import EvaluationRunResult

        result = EvaluationRunResult(
            run_id="test123",
            timestamp="2024-01-01T00:00:00",
            companies_evaluated=["stripe.com", "airbnb.com"],
            period_days=30,
            entity_accuracy=0.9,
            avg_signal_coverage=0.75,
            total_cost=0.10,
            cost_per_company=0.05,
        )

        summary = result.summary()
        assert "test123" in summary
        assert "90.0%" in summary
        assert "75.0%" in summary
        assert "$0.10" in summary


import json


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

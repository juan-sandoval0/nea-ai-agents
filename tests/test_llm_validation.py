"""
Tests for LLM Output Validation Utilities
=========================================

Tests the validation logic that protects against malformed LLM outputs.
"""

import pytest

from core.llm_validation import (
    validate_llm_response,
    validate_json_response,
    validate_briefing_content,
    validate_founder_summary,
    extract_json_from_response,
    with_llm_validation_retry,
    EmptyResponseError,
    TruncatedResponseError,
    MissingSectionsError,
    JSONParseError,
    SchemaValidationError,
    LLMResponseError,
)
from pydantic import BaseModel


# =============================================================================
# TEST: validate_llm_response
# =============================================================================

class TestValidateLLMResponse:
    """Tests for basic text response validation."""

    def test_valid_response(self):
        """Valid response passes validation."""
        content = "This is a valid response with enough content."
        result = validate_llm_response(content, min_length=10)
        assert result == content

    def test_strips_whitespace(self):
        """Response whitespace is stripped."""
        content = "  Valid content with spaces  \n\n"
        result = validate_llm_response(content, min_length=10)
        assert result == "Valid content with spaces"

    def test_empty_response_raises(self):
        """Empty response raises EmptyResponseError."""
        with pytest.raises(EmptyResponseError):
            validate_llm_response("")

    def test_none_response_raises(self):
        """None response raises EmptyResponseError."""
        with pytest.raises(EmptyResponseError):
            validate_llm_response(None)

    def test_whitespace_only_raises(self):
        """Whitespace-only response raises EmptyResponseError."""
        with pytest.raises(EmptyResponseError):
            validate_llm_response("   \n\t  ")

    def test_too_short_raises(self):
        """Response shorter than min_length raises TruncatedResponseError."""
        with pytest.raises(TruncatedResponseError) as exc_info:
            validate_llm_response("short", min_length=100)
        assert "5 chars" in str(exc_info.value)
        assert "minimum: 100" in str(exc_info.value)

    def test_required_substrings_present(self):
        """Response with required substrings passes."""
        content = "This has SECTION ONE and section two content."
        result = validate_llm_response(
            content,
            min_length=10,
            required_substrings=["section one", "section two"],
        )
        assert result == content

    def test_required_substrings_missing_raises(self):
        """Missing required substrings raises MissingSectionsError."""
        content = "This only has section one content."
        with pytest.raises(MissingSectionsError) as exc_info:
            validate_llm_response(
                content,
                min_length=10,
                required_substrings=["section one", "section two"],
            )
        assert "section two" in exc_info.value.missing_sections

    def test_case_insensitive_by_default(self):
        """Substring matching is case-insensitive by default."""
        content = "This has SECTION content."
        result = validate_llm_response(
            content,
            min_length=10,
            required_substrings=["section"],
        )
        assert result == content

    def test_case_sensitive_option(self):
        """Case-sensitive matching works when enabled."""
        content = "This has SECTION content."
        with pytest.raises(MissingSectionsError):
            validate_llm_response(
                content,
                min_length=10,
                required_substrings=["section"],
                case_sensitive=True,
            )

    def test_forbidden_patterns_raises(self):
        """Forbidden patterns trigger error."""
        content = "I cannot provide that information."
        with pytest.raises(LLMResponseError) as exc_info:
            validate_llm_response(
                content,
                min_length=10,
                forbidden_patterns=[r"i cannot"],
            )
        assert exc_info.value.error_type == "forbidden_pattern"

    def test_max_length_truncates(self):
        """Content exceeding max_length is truncated."""
        content = "A" * 200
        result = validate_llm_response(content, min_length=10, max_length=50)
        assert len(result) == 50


# =============================================================================
# TEST: extract_json_from_response
# =============================================================================

class TestExtractJsonFromResponse:
    """Tests for JSON extraction from markdown."""

    def test_plain_json(self):
        """Plain JSON is returned as-is."""
        json_str = '{"key": "value"}'
        result = extract_json_from_response(json_str)
        assert result == json_str

    def test_json_in_code_block(self):
        """JSON in markdown code block is extracted."""
        content = 'Here is the result:\n```json\n{"key": "value"}\n```'
        result = extract_json_from_response(content)
        assert result == '{"key": "value"}'

    def test_json_in_plain_code_block(self):
        """JSON in plain code block (no language) is extracted."""
        content = 'Result:\n```\n{"key": "value"}\n```'
        result = extract_json_from_response(content)
        assert result == '{"key": "value"}'

    def test_json_embedded_in_text(self):
        """JSON embedded in text is extracted."""
        content = 'The answer is {"key": "value"} as shown.'
        result = extract_json_from_response(content)
        assert result == '{"key": "value"}'

    def test_array_json(self):
        """JSON arrays are extracted."""
        content = 'List: [1, 2, 3]'
        result = extract_json_from_response(content)
        assert result == '[1, 2, 3]'


# =============================================================================
# TEST: validate_json_response
# =============================================================================

class TestValidateJsonResponse:
    """Tests for JSON parsing and schema validation."""

    def test_valid_json_dict(self):
        """Valid JSON dict is parsed correctly."""
        content = '{"name": "test", "value": 123}'
        result = validate_json_response(content)
        assert result == {"name": "test", "value": 123}

    def test_valid_json_array(self):
        """Valid JSON array is parsed correctly."""
        content = '[1, 2, 3]'
        result = validate_json_response(content)
        assert result == [1, 2, 3]

    def test_empty_raises(self):
        """Empty content raises EmptyResponseError."""
        with pytest.raises(EmptyResponseError):
            validate_json_response("")

    def test_invalid_json_raises(self):
        """Invalid JSON raises JSONParseError."""
        content = '{"key": missing_quotes}'
        with pytest.raises(JSONParseError) as exc_info:
            validate_json_response(content)
        assert "parse_error" in dir(exc_info.value)

    def test_schema_validation_passes(self):
        """Valid JSON matching schema returns model instance."""

        class TestModel(BaseModel):
            name: str
            count: int

        content = '{"name": "test", "count": 42}'
        result = validate_json_response(content, schema=TestModel)
        assert isinstance(result, TestModel)
        assert result.name == "test"
        assert result.count == 42

    def test_schema_validation_fails(self):
        """JSON not matching schema raises SchemaValidationError."""

        class TestModel(BaseModel):
            name: str
            count: int

        content = '{"name": "test", "count": "not_a_number"}'
        with pytest.raises(SchemaValidationError) as exc_info:
            validate_json_response(content, schema=TestModel)
        assert len(exc_info.value.validation_errors) > 0

    def test_extracts_from_markdown(self):
        """JSON in markdown is extracted and parsed."""

        content = '```json\n{"key": "value"}\n```'
        result = validate_json_response(content)
        assert result == {"key": "value"}


# =============================================================================
# TEST: validate_briefing_content
# =============================================================================

class TestValidateBriefingContent:
    """Tests for briefing-specific validation."""

    @pytest.fixture
    def valid_briefing(self):
        """A briefing with all required sections."""
        return """
## TL;DR
Company does something interesting. They are building a platform for enterprise customers.
The company was founded in 2020 and has raised $50M in funding to date.

## Why This Meeting Matters
- Important point 1: Strong growth trajectory in enterprise market
- Important point 2: Experienced founding team with prior exits
- The company is well-positioned in a growing market segment

## Company Snapshot
Founded: 2020
Employees: 50
Location: San Francisco, CA
Total Funding: $50M

## Founder Information
**John Doe** - CEO
Background: Previously founded and sold a startup to Google. 10+ years of experience.

**Jane Smith** - CTO
Background: Former engineering lead at Meta. PhD in Computer Science from Stanford.

## Key Signals
- Signal 1: Web traffic up 50% in last 30 days
- Signal 2: Recently opened new offices in NYC
- Signal 3: Hiring aggressively for sales roles

## In the News
- Article about company raising Series B (TechCrunch)
- Interview with CEO about product roadmap (Forbes)

## For This Meeting
- Question to ask about go-to-market strategy
- Discuss competitive landscape and moat
- Understand unit economics and path to profitability
"""

    def test_valid_briefing_passes(self, valid_briefing):
        """Briefing with all sections passes validation."""
        result = validate_briefing_content(valid_briefing)
        assert "TL;DR" in result

    def test_empty_raises(self):
        """Empty briefing raises EmptyResponseError."""
        with pytest.raises(EmptyResponseError):
            validate_briefing_content("")

    def test_too_short_raises(self):
        """Short briefing raises TruncatedResponseError."""
        with pytest.raises(TruncatedResponseError):
            validate_briefing_content("Too short", strict=True)

    def test_missing_sections_strict_raises(self, valid_briefing):
        """Missing sections in strict mode raises MissingSectionsError."""
        # Remove a required section
        partial = valid_briefing.replace("## TL;DR", "## Summary")
        with pytest.raises(MissingSectionsError) as exc_info:
            validate_briefing_content(partial, strict=True)
        assert "TL;DR" in exc_info.value.missing_sections

    def test_missing_sections_non_strict_warns(self, valid_briefing, caplog):
        """Missing sections in non-strict mode logs warning but passes."""
        partial = valid_briefing.replace("## TL;DR", "## Summary")
        result = validate_briefing_content(partial, strict=False)
        assert result is not None
        assert "missing" in caplog.text.lower()

    def test_section_variations_accepted(self):
        """Common section name variations are accepted."""
        briefing = """
## TL;DR
Summary here.

## Why This Meeting Matters
Points here.

## Company Snapshot
Data here.

## Founding Team
Founders listed here.

## Key Signals
Signals here.

## Recent News
News articles.

## Meeting Preparation
Questions to ask.
""" + ("x" * 500)  # Pad to meet minimum length

        result = validate_briefing_content(briefing, strict=True)
        assert result is not None


# =============================================================================
# TEST: validate_founder_summary
# =============================================================================

class TestValidateFounderSummary:
    """Tests for founder summary validation."""

    def test_valid_summary_passes(self):
        """Valid summary passes validation."""
        summary = (
            "John previously led engineering at Google for 5 years. "
            "He holds a PhD in Computer Science from Stanford."
        )
        result = validate_founder_summary(
            summary,
            founder_name="John Doe",
            raw_background="Long raw background text...",
        )
        assert result == summary

    def test_empty_raises(self):
        """Empty summary raises EmptyResponseError."""
        with pytest.raises(EmptyResponseError):
            validate_founder_summary("", "John", "raw")

    def test_too_short_raises(self):
        """Short summary raises TruncatedResponseError."""
        with pytest.raises(TruncatedResponseError):
            validate_founder_summary("Too short", "John", "raw background")

    def test_echo_detection_raises(self):
        """Echoed input raises LLMResponseError."""
        raw = "This is the raw background text that was provided."
        with pytest.raises(LLMResponseError) as exc_info:
            validate_founder_summary(raw, "John", raw)
        assert exc_info.value.error_type == "echo"

    def test_error_response_detection(self):
        """LLM error responses are detected."""
        error_responses = [
            "I cannot provide information about this person. There is no data available in the sources I have access to for this individual.",
            "I don't have access to that data. The background information provided does not contain enough details to create a summary.",
            "Sorry, I am unable to summarize this founder's background as the provided data is insufficient for a meaningful summary.",
            "No information available for this founder. The data sources do not contain relevant background details.",
        ]
        for error in error_responses:
            with pytest.raises(LLMResponseError) as exc_info:
                validate_founder_summary(error, "John", "raw background")
            assert exc_info.value.error_type == "error_response"

    def test_long_summary_truncated(self, caplog):
        """Summary exceeding max length is truncated."""
        long_summary = "A" * 1500
        result = validate_founder_summary(long_summary, "John", "raw")
        assert len(result) <= 1000 + 3  # 3 for "..."


# =============================================================================
# TEST: with_llm_validation_retry
# =============================================================================

class TestWithLLMValidationRetry:
    """Tests for retry wrapper."""

    def test_success_on_first_try(self):
        """Successful first attempt returns immediately."""
        call_count = 0

        def llm_call():
            nonlocal call_count
            call_count += 1
            return "valid response content"

        def validator(content):
            return content

        result = with_llm_validation_retry(llm_call, validator, max_retries=2)
        assert result == "valid response content"
        assert call_count == 1

    def test_retries_on_validation_failure(self):
        """Validation failures trigger retries."""
        call_count = 0

        def llm_call():
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                return ""  # Invalid
            return "valid on third try"

        def validator(content):
            if not content:
                raise EmptyResponseError()
            return content

        result = with_llm_validation_retry(llm_call, validator, max_retries=2)
        assert result == "valid on third try"
        assert call_count == 3

    def test_raises_after_max_retries(self):
        """Raises after exhausting retries."""

        def llm_call():
            return ""

        def validator(content):
            raise EmptyResponseError()

        with pytest.raises(EmptyResponseError):
            with_llm_validation_retry(llm_call, validator, max_retries=2)

    def test_non_validation_errors_not_retried(self):
        """Non-LLMResponseError exceptions are not retried."""
        call_count = 0

        def llm_call():
            nonlocal call_count
            call_count += 1
            raise ValueError("API error")

        def validator(content):
            return content

        with pytest.raises(ValueError):
            with_llm_validation_retry(llm_call, validator, max_retries=2)
        assert call_count == 1

    def test_on_retry_callback(self):
        """on_retry callback is called on failures."""
        retries_logged = []

        def llm_call():
            if len(retries_logged) < 2:
                return ""
            return "valid"

        def validator(content):
            if not content:
                raise EmptyResponseError()
            return content

        def on_retry(exc, attempt):
            retries_logged.append((type(exc).__name__, attempt))

        result = with_llm_validation_retry(
            llm_call, validator, max_retries=2, on_retry=on_retry
        )
        assert result == "valid"
        assert len(retries_logged) == 2
        assert retries_logged[0] == ("EmptyResponseError", 1)
        assert retries_logged[1] == ("EmptyResponseError", 2)

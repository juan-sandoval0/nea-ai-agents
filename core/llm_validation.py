"""
LLM Output Validation Utilities
===============================

Centralized validation for LLM responses to catch malformed outputs
before they propagate through the system.

Why this is crucial:
1. LLMs can produce empty, truncated, or malformed responses
2. JSON parsing can fail silently or with cryptic errors
3. Required content/sections may be missing
4. Without validation, bad outputs corrupt downstream data

Usage:
    from core.llm_validation import (
        validate_llm_response,
        validate_json_response,
        validate_briefing_content,
        LLMResponseError,
    )

    # Validate text response
    content = validate_llm_response(
        response.content,
        min_length=100,
        required_substrings=["## Summary"],
    )

    # Validate JSON response with schema
    data = validate_json_response(
        response.content,
        schema=MyPydanticModel,
    )
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any, Callable, Optional, Type, TypeVar, Union

from pydantic import BaseModel, ValidationError

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)


# =============================================================================
# CUSTOM EXCEPTIONS
# =============================================================================

class LLMResponseError(Exception):
    """Base exception for LLM response validation errors."""

    def __init__(
        self,
        message: str,
        response_content: Optional[str] = None,
        error_type: str = "unknown",
    ):
        super().__init__(message)
        self.response_content = response_content
        self.error_type = error_type


class EmptyResponseError(LLMResponseError):
    """LLM returned empty or whitespace-only response."""

    def __init__(self, message: str = "LLM returned empty response"):
        super().__init__(message, response_content="", error_type="empty")


class TruncatedResponseError(LLMResponseError):
    """LLM response appears truncated (too short or missing expected content)."""

    def __init__(self, message: str, response_content: str):
        super().__init__(message, response_content, error_type="truncated")


class MissingSectionsError(LLMResponseError):
    """LLM response is missing required sections or content."""

    def __init__(self, message: str, response_content: str, missing_sections: list[str]):
        super().__init__(message, response_content, error_type="missing_sections")
        self.missing_sections = missing_sections


class JSONParseError(LLMResponseError):
    """LLM response could not be parsed as valid JSON."""

    def __init__(self, message: str, response_content: str, parse_error: str):
        super().__init__(message, response_content, error_type="json_parse")
        self.parse_error = parse_error


class SchemaValidationError(LLMResponseError):
    """LLM response JSON did not match expected schema."""

    def __init__(self, message: str, response_content: str, validation_errors: list[dict]):
        super().__init__(message, response_content, error_type="schema_validation")
        self.validation_errors = validation_errors


# =============================================================================
# TEXT RESPONSE VALIDATION
# =============================================================================

def validate_llm_response(
    content: Optional[str],
    min_length: int = 10,
    max_length: Optional[int] = None,
    required_substrings: Optional[list[str]] = None,
    forbidden_patterns: Optional[list[str]] = None,
    case_sensitive: bool = False,
) -> str:
    """
    Validate a text response from an LLM.

    Why: LLMs can return empty, truncated, or malformed responses. This catches
    issues early before they propagate through the system.

    Args:
        content: Raw response content from LLM
        min_length: Minimum acceptable length (default: 10 chars)
        max_length: Maximum acceptable length (None = no limit)
        required_substrings: Substrings that must be present in response
        forbidden_patterns: Regex patterns that indicate error responses
        case_sensitive: Whether substring matching is case-sensitive

    Returns:
        Validated and stripped content

    Raises:
        EmptyResponseError: If content is None, empty, or whitespace
        TruncatedResponseError: If content is shorter than min_length
        MissingSectionsError: If required substrings are missing
        LLMResponseError: If forbidden patterns are found
    """
    # Check for empty response
    if content is None or not content.strip():
        raise EmptyResponseError()

    content = content.strip()

    # Check minimum length
    if len(content) < min_length:
        raise TruncatedResponseError(
            f"Response too short: {len(content)} chars (minimum: {min_length})",
            response_content=content,
        )

    # Check maximum length
    if max_length is not None and len(content) > max_length:
        logger.warning(
            f"Response exceeds max length: {len(content)} chars (max: {max_length}). Truncating."
        )
        content = content[:max_length]

    # Check required substrings
    if required_substrings:
        check_content = content if case_sensitive else content.lower()
        missing = []
        for substring in required_substrings:
            check_substring = substring if case_sensitive else substring.lower()
            if check_substring not in check_content:
                missing.append(substring)

        if missing:
            raise MissingSectionsError(
                f"Response missing required sections: {missing}",
                response_content=content,
                missing_sections=missing,
            )

    # Check forbidden patterns (e.g., error messages from LLM)
    if forbidden_patterns:
        for pattern in forbidden_patterns:
            if re.search(pattern, content, re.IGNORECASE):
                raise LLMResponseError(
                    f"Response contains forbidden pattern: {pattern}",
                    response_content=content,
                    error_type="forbidden_pattern",
                )

    return content


# =============================================================================
# JSON RESPONSE VALIDATION
# =============================================================================

def extract_json_from_response(content: str) -> str:
    """
    Extract JSON from LLM response that may contain markdown code blocks.

    Why: LLMs often wrap JSON in ```json ... ``` blocks even when asked not to.
    This extracts the actual JSON content.

    Args:
        content: Raw response content

    Returns:
        Extracted JSON string
    """
    content = content.strip()

    # Try to extract from markdown code blocks
    json_block_pattern = r"```(?:json)?\s*([\s\S]*?)```"
    matches = re.findall(json_block_pattern, content)
    if matches:
        # Return the first JSON block found
        return matches[0].strip()

    # If no code blocks, check if content starts with { or [
    if content.startswith(("{", "[")):
        return content

    # Try to find JSON object/array in the content
    json_object_pattern = r"(\{[\s\S]*\})"
    json_array_pattern = r"(\[[\s\S]*\])"

    obj_match = re.search(json_object_pattern, content)
    if obj_match:
        return obj_match.group(1)

    arr_match = re.search(json_array_pattern, content)
    if arr_match:
        return arr_match.group(1)

    # Return original content if no JSON structure found
    return content


def validate_json_response(
    content: Optional[str],
    schema: Optional[Type[T]] = None,
    extract_from_markdown: bool = True,
) -> Union[dict, list, T]:
    """
    Parse and validate JSON response from LLM.

    Why: LLM JSON outputs are notoriously unreliable:
    - May be wrapped in markdown code blocks
    - May have trailing commas or comments
    - May not match expected schema
    This catches all these issues with clear error messages.

    Args:
        content: Raw response content from LLM
        schema: Optional Pydantic model to validate against
        extract_from_markdown: Try to extract JSON from markdown blocks

    Returns:
        Parsed JSON (dict/list) or validated Pydantic model instance

    Raises:
        EmptyResponseError: If content is empty
        JSONParseError: If JSON parsing fails
        SchemaValidationError: If schema validation fails
    """
    if content is None or not content.strip():
        raise EmptyResponseError("LLM returned empty response for JSON request")

    # Extract JSON from markdown if needed
    json_str = extract_json_from_response(content) if extract_from_markdown else content.strip()

    # Try to parse JSON
    try:
        data = json.loads(json_str)
    except json.JSONDecodeError as e:
        # Try to provide helpful error context
        error_context = json_str[max(0, e.pos - 20):e.pos + 20] if e.pos else json_str[:50]
        raise JSONParseError(
            f"Failed to parse JSON: {e.msg} at position {e.pos}. Context: ...{error_context}...",
            response_content=content,
            parse_error=str(e),
        )

    # Validate against schema if provided
    if schema is not None:
        try:
            return schema.model_validate(data)
        except ValidationError as e:
            raise SchemaValidationError(
                f"JSON does not match expected schema: {e.error_count()} validation errors",
                response_content=content,
                validation_errors=e.errors(),
            )

    return data


# =============================================================================
# BRIEFING-SPECIFIC VALIDATION
# =============================================================================

# Required sections for a valid meeting briefing
BRIEFING_REQUIRED_SECTIONS = [
    "TL;DR",
    "Why This Meeting",
    "Company Snapshot",
    "Founder",
    "Key Signals",
    "In the News",
    "For This Meeting",
]

# Minimum expected length for a complete briefing
BRIEFING_MIN_LENGTH = 500


def validate_briefing_content(
    content: Optional[str],
    company_name: Optional[str] = None,
    strict: bool = True,
) -> str:
    """
    Validate that briefing content has all required sections and minimum quality.

    Why: Briefings are user-facing documents. A briefing missing key sections
    (like TL;DR or Key Signals) is not useful and should be flagged/regenerated.

    Args:
        content: Raw briefing markdown from LLM
        company_name: Company name (for validation, optional)
        strict: If True, raise on missing sections. If False, log warning only.

    Returns:
        Validated briefing content

    Raises:
        EmptyResponseError: If content is empty
        TruncatedResponseError: If content is too short
        MissingSectionsError: If required sections are missing (strict mode)
    """
    # Basic validation
    if content is None or not content.strip():
        raise EmptyResponseError("Briefing content is empty")

    content = content.strip()

    # Check minimum length
    if len(content) < BRIEFING_MIN_LENGTH:
        raise TruncatedResponseError(
            f"Briefing too short: {len(content)} chars (minimum: {BRIEFING_MIN_LENGTH}). "
            "This may indicate a truncated or incomplete response.",
            response_content=content,
        )

    # Check for required sections
    content_lower = content.lower()
    missing_sections = []

    for section in BRIEFING_REQUIRED_SECTIONS:
        # Allow some flexibility in section naming
        section_lower = section.lower()
        # Check for common variations
        variations = [
            section_lower,
            section_lower.replace(" ", "_"),
            section_lower.replace("_", " "),
        ]
        # Special cases
        if section_lower == "founder":
            variations.extend(["founder information", "founders", "founding team"])
        elif section_lower == "in the news":
            variations.extend(["news", "recent news", "press"])
        elif section_lower == "for this meeting":
            variations.extend(["meeting prep", "meeting preparation", "questions"])

        found = any(var in content_lower for var in variations)
        if not found:
            missing_sections.append(section)

    if missing_sections:
        message = f"Briefing missing {len(missing_sections)} required sections: {missing_sections}"
        if strict:
            raise MissingSectionsError(
                message,
                response_content=content,
                missing_sections=missing_sections,
            )
        else:
            logger.warning(message)

    # Validate company name appears if provided
    if company_name and company_name.lower() not in content_lower:
        logger.warning(f"Briefing does not mention company name: {company_name}")

    return content


# =============================================================================
# RETRY WRAPPER
# =============================================================================

def with_llm_validation_retry(
    llm_call: Callable[[], str],
    validator: Callable[[str], str],
    max_retries: int = 2,
    on_retry: Optional[Callable[[Exception, int], None]] = None,
) -> str:
    """
    Execute LLM call with validation and automatic retry on failure.

    Why: LLM outputs are probabilistic. A single failure doesn't mean the task
    is impossible - often a retry produces valid output. This wrapper handles
    the retry logic centrally.

    Args:
        llm_call: Function that calls the LLM and returns content
        validator: Function that validates content (raises on failure)
        max_retries: Maximum number of retry attempts (default: 2)
        on_retry: Optional callback(exception, attempt_number) for logging

    Returns:
        Validated content

    Raises:
        LLMResponseError: If all retries fail
    """
    last_error: Optional[Exception] = None

    for attempt in range(max_retries + 1):
        try:
            content = llm_call()
            return validator(content)
        except LLMResponseError as e:
            last_error = e
            if attempt < max_retries:
                if on_retry:
                    on_retry(e, attempt + 1)
                else:
                    logger.warning(
                        f"LLM validation failed (attempt {attempt + 1}/{max_retries + 1}): "
                        f"{e.error_type} - {str(e)[:100]}"
                    )
            continue
        except Exception as e:
            # Non-validation errors should not be retried
            raise

    # All retries exhausted
    raise last_error or LLMResponseError("LLM call failed after all retries")


# =============================================================================
# FOUNDER SUMMARY VALIDATION
# =============================================================================

FOUNDER_SUMMARY_MIN_LENGTH = 50
FOUNDER_SUMMARY_MAX_LENGTH = 1000


def validate_founder_summary(
    content: Optional[str],
    founder_name: str,
    raw_background: str,
) -> str:
    """
    Validate that founder summary is meaningful and not just echoed input.

    Why: The LLM might:
    - Return the raw input unchanged
    - Return an error message
    - Return empty or very short content
    - Return generic filler text

    Args:
        content: Summarized background from LLM
        founder_name: Founder's name (for validation)
        raw_background: Original raw background (to detect echo)

    Returns:
        Validated summary

    Raises:
        LLMResponseError: If summary is invalid
    """
    if content is None or not content.strip():
        raise EmptyResponseError(f"Empty summary for founder {founder_name}")

    content = content.strip()

    # Check minimum length
    if len(content) < FOUNDER_SUMMARY_MIN_LENGTH:
        raise TruncatedResponseError(
            f"Founder summary too short for {founder_name}: {len(content)} chars",
            response_content=content,
        )

    # Check if it's just echoing the input
    if content == raw_background.strip():
        raise LLMResponseError(
            f"LLM returned raw input unchanged for {founder_name}",
            response_content=content,
            error_type="echo",
        )

    # Check for error patterns
    error_patterns = [
        r"i (?:cannot|can't|am unable to)",
        r"i don't have (?:access|information)",
        r"no (?:information|data) (?:available|found)",
        r"sorry,? (?:i|but)",
    ]

    for pattern in error_patterns:
        if re.search(pattern, content.lower()):
            raise LLMResponseError(
                f"LLM returned error response for {founder_name}: {content[:100]}",
                response_content=content,
                error_type="error_response",
            )

    # Truncate if too long
    if len(content) > FOUNDER_SUMMARY_MAX_LENGTH:
        logger.warning(
            f"Founder summary too long for {founder_name}: {len(content)} chars. Truncating."
        )
        # Truncate at sentence boundary if possible
        truncated = content[:FOUNDER_SUMMARY_MAX_LENGTH]
        last_period = truncated.rfind(".")
        if last_period > FOUNDER_SUMMARY_MIN_LENGTH:
            content = truncated[: last_period + 1]
        else:
            content = truncated + "..."

    return content

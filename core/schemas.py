"""
Pydantic Output Validation Schemas
==================================

Schemas for validating pipeline outputs and ensuring data quality.

Usage:
    from core.schemas import BriefingResult, KeySignalOutput, validate_briefing_result

    # Validate a briefing result
    result = generate_briefing("stripe.com")
    validated = validate_briefing_result(result)
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional, Literal
from pydantic import BaseModel, Field, field_validator


# =============================================================================
# SIGNAL TYPE LITERALS
# =============================================================================

VALID_SIGNAL_TYPES = Literal[
    # Harmonic signals
    "web_traffic",
    "hiring",
    "funding",
    # Tavily website signals
    "website_update",
    "website_product",
    "website_pricing",
    "website_team",
    "website_news",
    # Parallel Search news signals
    "funding",
    "acquisition",
    "team_change",
    "product_launch",
    "partnership",
    "news_coverage",
]

VALID_SOURCES = Literal[
    "harmonic",
    "tavily",
    "parallel",
    "swarm",
    "pending_tavily",
    "pending_swarm",
    "manual_correction",
    "news_api",
]


# =============================================================================
# KEY SIGNAL SCHEMA
# =============================================================================

class KeySignalOutput(BaseModel):
    """Validated key signal output."""

    company_id: str = Field(..., min_length=1)
    signal_type: str = Field(..., min_length=1)
    description: str = Field(..., min_length=1)
    observed_at: str
    source: str = Field(..., min_length=1)

    @field_validator("signal_type")
    @classmethod
    def validate_signal_type(cls, v: str) -> str:
        """Validate signal_type is a known type."""
        valid_types = {
            "web_traffic", "hiring", "funding",
            "website_update", "website_product", "website_pricing",
            "website_team", "website_news",
            "acquisition", "team_change", "product_launch",
            "partnership", "news_coverage",
        }
        if v not in valid_types:
            # Log warning but don't fail - allow new types
            import logging
            logging.warning(f"Unknown signal_type: {v}")
        return v

    @field_validator("source")
    @classmethod
    def validate_source(cls, v: str) -> str:
        """Validate source is a known source."""
        valid_sources = {
            "harmonic", "tavily", "parallel", "swarm",
            "pending_tavily", "pending_swarm", "manual_correction", "news_api",
        }
        if v not in valid_sources:
            import logging
            logging.warning(f"Unknown source: {v}")
        return v


# =============================================================================
# FOUNDER SCHEMA
# =============================================================================

class FounderOutput(BaseModel):
    """Validated founder output."""

    company_id: str = Field(..., min_length=1)
    name: str = Field(..., min_length=1)
    role_title: Optional[str] = None
    linkedin_url: Optional[str] = None
    background: Optional[str] = None
    observed_at: str
    source: str = Field(default="harmonic")

    @field_validator("linkedin_url")
    @classmethod
    def validate_linkedin_url(cls, v: Optional[str]) -> Optional[str]:
        """Validate LinkedIn URL format if provided."""
        if v is not None and v and "linkedin.com" not in v.lower():
            import logging
            logging.warning(f"LinkedIn URL doesn't contain linkedin.com: {v}")
        return v


# =============================================================================
# COMPANY CORE SCHEMA
# =============================================================================

class CompanyCoreOutput(BaseModel):
    """Validated company core output."""

    company_id: str = Field(..., min_length=1)
    company_name: str = Field(..., min_length=1)
    founding_date: Optional[str] = None
    hq: Optional[str] = None
    employee_count: Optional[int] = Field(default=None, ge=0)
    total_funding: Optional[float] = Field(default=None, ge=0)
    products: Optional[str] = None
    customers: Optional[str] = None
    arr_apr: Optional[str] = None
    last_round_date: Optional[str] = None
    last_round_funding: Optional[float] = Field(default=None, ge=0)
    web_traffic_trend: Optional[str] = None
    website_update: Optional[str] = None
    hiring_firing: Optional[str] = None
    observed_at: str
    source_map: dict = Field(default_factory=dict)


# =============================================================================
# NEWS ARTICLE SCHEMA
# =============================================================================

class NewsArticleOutput(BaseModel):
    """Validated news article output."""

    company_id: str = Field(..., min_length=1)
    article_headline: str = Field(..., min_length=1)
    outlet: Optional[str] = None
    url: Optional[str] = None
    published_date: Optional[str] = None
    observed_at: str
    source: str = Field(default="parallel")

    @field_validator("url")
    @classmethod
    def validate_url(cls, v: Optional[str]) -> Optional[str]:
        """Validate URL format if provided."""
        if v is not None and v and not v.startswith(("http://", "https://")):
            import logging
            logging.warning(f"URL doesn't start with http(s): {v}")
        return v


# =============================================================================
# DATA SOURCES SCHEMA
# =============================================================================

class DataSourcesOutput(BaseModel):
    """Data sources tracking for briefing."""

    company_core: bool = False
    founders: int = Field(default=0, ge=0)
    signals: int = Field(default=0, ge=0)
    news: int = Field(default=0, ge=0)


# =============================================================================
# BRIEFING RESULT SCHEMA
# =============================================================================

class BriefingResultOutput(BaseModel):
    """Validated briefing generation result."""

    company_id: str = Field(..., min_length=1)
    company_name: Optional[str] = None
    markdown: Optional[str] = None
    generated_at: str
    data_sources: DataSourcesOutput
    success: bool
    error: Optional[str] = None

    @field_validator("markdown")
    @classmethod
    def validate_markdown_sections(cls, v: Optional[str]) -> Optional[str]:
        """Validate that successful briefings have required sections."""
        if v is not None:
            # Check for expected section headers
            expected_sections = ["TL;DR", "Why This Meeting", "Company Snapshot"]
            missing = [s for s in expected_sections if s.lower() not in v.lower()]
            if missing:
                import logging
                logging.warning(f"Briefing missing expected sections: {missing}")
        return v


# =============================================================================
# INGEST RESULT SCHEMA
# =============================================================================

class IngestResultOutput(BaseModel):
    """Validated ingest result."""

    company_id: str = Field(..., min_length=1)
    company_name: Optional[str] = None
    company_core: bool = False
    founders_count: int = Field(default=0, ge=0)
    founders_enriched: int = Field(default=0, ge=0)
    signals_count: int = Field(default=0, ge=0)
    news_count: int = Field(default=0, ge=0)
    errors: list[str] = Field(default_factory=list)


# =============================================================================
# VALIDATION HELPERS
# =============================================================================

def validate_briefing_result(result: dict) -> BriefingResultOutput:
    """
    Validate a briefing result dictionary.

    Args:
        result: Raw result dict from generate_briefing()

    Returns:
        Validated BriefingResultOutput

    Raises:
        pydantic.ValidationError: If validation fails
    """
    return BriefingResultOutput(**result)


def validate_ingest_result(result: dict) -> IngestResultOutput:
    """
    Validate an ingest result dictionary.

    Args:
        result: Raw result dict from ingest_company()

    Returns:
        Validated IngestResultOutput

    Raises:
        pydantic.ValidationError: If validation fails
    """
    return IngestResultOutput(**result)


def validate_key_signal(signal: dict) -> KeySignalOutput:
    """
    Validate a key signal dictionary.

    Args:
        signal: Raw signal dict

    Returns:
        Validated KeySignalOutput

    Raises:
        pydantic.ValidationError: If validation fails
    """
    return KeySignalOutput(**signal)


def validate_founder(founder: dict) -> FounderOutput:
    """
    Validate a founder dictionary.

    Args:
        founder: Raw founder dict

    Returns:
        Validated FounderOutput

    Raises:
        pydantic.ValidationError: If validation fails
    """
    return FounderOutput(**founder)

"""
Pydantic models for structured LLM output in briefing generation.

These models define the schema for Claude's with_structured_output() method,
eliminating fragile regex parsing of markdown sections.
"""

from pydantic import BaseModel, Field
from typing import List


class BriefingLLMOutput(BaseModel):
    """
    Structured output schema for briefing LLM generation.

    This model captures the sections that require LLM synthesis:
    - TL;DR summary
    - Why This Meeting Matters bullets
    - For This Meeting preparation notes

    Other sections (Company Snapshot, Founders, Signals, News, Competitors)
    come directly from database tables and don't need LLM extraction.
    """

    tldr: str = Field(
        ...,
        description=(
            "2-3 sentence executive summary. First sentence: what the company does. "
            "Remaining sentences: key highlights from funding, growth metrics, or news. "
            "Must be derived strictly from the provided data."
        )
    )

    why_this_meeting_matters: List[str] = Field(
        ...,
        min_length=2,
        max_length=5,
        description=(
            "3-5 bullet points synthesized from company data, founders, signals, and news. "
            "Focus on investment relevance. Each bullet should be a complete thought."
        )
    )

    for_this_meeting: str = Field(
        ...,
        description=(
            "Preparation notes including: 2-3 suggested agenda items or questions, "
            "key risks to probe, and recommended next steps. "
            "All must be grounded in the provided data."
        )
    )

    # Markdown is still generated for backward compatibility and export
    full_markdown: str = Field(
        ...,
        description=(
            "Complete briefing in markdown format with all 9 sections: "
            "TL;DR, Why This Meeting Matters, For This Meeting, Founder Information, "
            "Key Signals, Company Snapshot, In the News, Competitive Landscape, NEA Connections. "
            "Use ### headers for each section."
        )
    )

"""
Investor Context for Outreach Agent
====================================

Holds investor-side data for prompt injection into outreach messages.
MVP returns defaults; scaffolded for future real data (DB/files, style matching).

Usage:
    from agents.outreach.context import get_investor_context

    ctx = get_investor_context(investor_name="Jane Smith", firm_name="NEA")
    print(ctx.format_for_prompt())
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# Default samples file relative to project root
_PROJECT_ROOT = Path(__file__).parent.parent.parent
DEFAULT_SAMPLES_FILE = _PROJECT_ROOT / "docs" / "Cold Outreach Email Samples (02_2026).md"

# Max samples to include (keeps token usage reasonable)
MAX_STYLE_SAMPLES = 3


@dataclass
class InvestorContext:
    """Investor-side context used to personalize outreach messages."""

    # Identity
    investor_name: str = "Investment Team"
    investor_title: str = "Investor"
    firm_name: str = "Our Firm"
    firm_description: str = ""

    # Tone / style
    tone_description: str = (
        "Professional, peer-to-peer VC tone. Concise and respectful of the "
        "founder's time. Show genuine interest in their work by referencing "
        "specific data points. Avoid being salesy or generic."
    )

    # Portfolio / focus (empty for MVP)
    portfolio_companies: list[str] = field(default_factory=list)
    investment_focus: str = ""
    shared_interests: list[str] = field(default_factory=list)

    # Style examples (future: past emails for few-shot)
    style_examples: list[str] = field(default_factory=list)

    # Optional overrides for message structure
    custom_opening: Optional[str] = None
    custom_closing: Optional[str] = None
    signature_line: Optional[str] = None

    def format_for_prompt(self) -> str:
        """Format all fields into a text block for LLM prompt injection."""
        lines = []
        lines.append(f"Investor Name: {self.investor_name}")
        lines.append(f"Title: {self.investor_title}")
        lines.append(f"Firm: {self.firm_name}")

        if self.firm_description:
            lines.append(f"Firm Description: {self.firm_description}")

        lines.append(f"Tone: {self.tone_description}")

        if self.investment_focus:
            lines.append(f"Investment Focus: {self.investment_focus}")

        if self.portfolio_companies:
            lines.append(f"Portfolio Companies: {', '.join(self.portfolio_companies)}")

        if self.shared_interests:
            lines.append(f"Shared Interests: {', '.join(self.shared_interests)}")

        if self.custom_opening:
            lines.append(f"Custom Opening: {self.custom_opening}")

        if self.custom_closing:
            lines.append(f"Custom Closing: {self.custom_closing}")

        if self.signature_line:
            lines.append(f"Signature: {self.signature_line}")

        if self.style_examples:
            lines.append("\nStyle Examples:")
            for i, example in enumerate(self.style_examples, 1):
                lines.append(f"  Example {i}: {example}")

        return "\n".join(lines)


def load_style_samples(file_path: str | Path) -> list[str]:
    """
    Load email style samples from a markdown file.

    Reads the file, splits on '---' delimiters, strips whitespace,
    and filters out empty chunks.

    Args:
        file_path: Path to the markdown samples file.

    Returns:
        List of individual email strings. Empty list if file not found or unreadable.
    """
    try:
        path = Path(file_path)
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        logger.warning(f"Style samples file not found: {file_path}")
        return []
    except OSError as e:
        logger.warning(f"Could not read style samples file {file_path}: {e}")
        return []

    chunks = text.split("---")
    samples = [chunk.strip() for chunk in chunks if chunk.strip()]
    return samples


def _select_short_samples(samples: list[str], max_count: int = MAX_STYLE_SAMPLES) -> list[str]:
    """Pick the shortest samples to keep token usage low."""
    if len(samples) <= max_count:
        return samples
    ranked = sorted(samples, key=len)
    return ranked[:max_count]


def get_investor_context(
    investor_name: Optional[str] = None,
    firm_name: Optional[str] = None,
    samples_file: Optional[str] = None,
    **overrides,
) -> InvestorContext:
    """
    Build an InvestorContext with optional overrides.

    MVP: returns defaults with optional name/firm overrides.
    Loads style samples from a markdown file if available.

    Args:
        investor_name: Investor name override
        firm_name: Firm name override
        samples_file: Path to style samples markdown file.
            None (default) = auto-detect from docs/.
            Explicit path = use that file.
            Pass ``""`` to disable loading.
        **overrides: Additional field overrides (e.g., tone_description, investment_focus)

    Returns:
        InvestorContext with applied overrides
    """
    kwargs = {}

    if investor_name:
        kwargs["investor_name"] = investor_name

    if firm_name:
        kwargs["firm_name"] = firm_name

    # Apply any additional overrides
    valid_fields = {f.name for f in InvestorContext.__dataclass_fields__.values()}
    for key, value in overrides.items():
        if key in valid_fields:
            kwargs[key] = value

    # Load style samples
    if samples_file is None:
        # Auto-detect: use default if it exists
        if DEFAULT_SAMPLES_FILE.exists():
            samples = load_style_samples(DEFAULT_SAMPLES_FILE)
            kwargs["style_examples"] = _select_short_samples(samples)
    elif samples_file:
        # Explicit path provided
        samples = load_style_samples(samples_file)
        kwargs["style_examples"] = _select_short_samples(samples)
    # else: samples_file == "" → explicitly disabled, don't load

    return InvestorContext(**kwargs)

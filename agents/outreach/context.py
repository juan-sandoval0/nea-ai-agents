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

from dataclasses import dataclass, field
from typing import Optional


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


def get_investor_context(
    investor_name: Optional[str] = None,
    firm_name: Optional[str] = None,
    **overrides,
) -> InvestorContext:
    """
    Build an InvestorContext with optional overrides.

    MVP: returns defaults with optional name/firm overrides.
    Future: load from DB/files, match investor profiles, find shared interests.

    Args:
        investor_name: Investor name override
        firm_name: Firm name override
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

    return InvestorContext(**kwargs)

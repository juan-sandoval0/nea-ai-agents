"""
Context Types for Outreach Agent
=================================

Defines the taxonomy of outreach scenarios, each with detection logic and
generation guidance. All context types are derived from the YAML metadata
in docs/email_samples.md.

Usage:
    from agents.outreach.context_types import detect_context_type, ContextType

    ctx_type = detect_context_type(
        available_signals=["funding_announcement", "product_capabilities"],
        has_prior_relationship=False,
        has_event_context=False,
    )
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class ContextType(str, Enum):
    """Every outreach context type found in email sample metadata."""

    # Ashley's context types
    THESIS_DRIVEN_DEEP_DIVE = "thesis_driven_deep_dive"
    EVENT_BASED_WARM_INTRO = "event_based_warm_intro"
    COLD_TECHNICAL_INTEREST = "cold_technical_interest"
    RESEARCH_TO_FOUNDER_BRIDGE = "research_to_founder_bridge"
    POST_EVENT_FOLLOWUP = "post_event_followup"
    COLD_PROBLEM_ALIGNMENT = "cold_problem_alignment"
    COLD_PERSONAL_AFFINITY = "cold_personal_affinity"

    # Tiffany's context types
    COLD_DOMAIN_EXPERTISE = "cold_domain_expertise"
    COLD_FUNDING_CONGRATS = "cold_funding_congrats"
    COLD_SECTOR_THESIS = "cold_sector_thesis"

    # Danielle's context types
    WARM_CONGRATULATIONS = "warm_congratulations"
    WARM_INTRO_REQUEST = "warm_intro_request"
    COLD_PERSONAL_CONNECTION = "cold_personal_connection"
    COLD_LAUNCH_REACTION = "cold_launch_reaction"
    INTERNAL_DEEP_ANALYSIS = "internal_deep_analysis"

    # Madison's context types
    COLD_MARKET_GAP = "cold_market_gap"
    COLD_WITH_FIRM_CONTEXT = "cold_with_firm_context"
    COLD_SHARED_BACKGROUND = "cold_shared_background"
    COLD_CONFERENCE_FOLLOWUP = "cold_conference_followup"
    WARM_PORTFOLIO_BRIDGE = "warm_portfolio_bridge"


@dataclass(frozen=True)
class ContextTypeConfig:
    """Configuration and generation guidance for a single context type."""

    description: str
    detection_signals: list[str]
    email_pattern: str
    preferred_length: str  # "short", "medium", "long"
    priority_personalization: list[str]


# =========================================================================
# CONTEXT TYPE CONFIGS — one per enum value
# =========================================================================

CONTEXT_TYPE_CONFIGS: dict[ContextType, ContextTypeConfig] = {
    # ----- Thesis / Technical (Cold) -----
    ContextType.THESIS_DRIVEN_DEEP_DIVE: ContextTypeConfig(
        description=(
            "Investor has an active thesis related to the company's space and "
            "demonstrates deep technical understanding of the product."
        ),
        detection_signals=[
            "active_thesis",
            "product_technical_detail",
            "architectural_insight",
            "technical_architecture",
        ],
        email_pattern=(
            "Deep technical hook showing genuine understanding "
            "→ Thesis connection explaining why this space matters "
            "→ Architecture/product discussion with specific details "
            "→ Collaborative meeting ask (often involving a colleague)"
        ),
        preferred_length="long",
        priority_personalization=[
            "technical_architecture",
            "product_components",
            "thesis_alignment",
            "upcoming_feature",
        ],
    ),
    ContextType.COLD_TECHNICAL_INTEREST: ContextTypeConfig(
        description=(
            "Cold outreach driven by genuine technical curiosity about the "
            "product's capabilities and architecture."
        ),
        detection_signals=[
            "product_capabilities",
            "technical_architecture",
        ],
        email_pattern=(
            "Self-intro with portfolio context "
            "→ Specific technical interest in product capabilities "
            "→ Roadmap and long-term vision curiosity "
            "→ Meeting ask"
        ),
        preferred_length="medium",
        priority_personalization=[
            "product_capabilities",
            "technical_architecture",
        ],
    ),
    ContextType.COLD_PROBLEM_ALIGNMENT: ContextTypeConfig(
        description=(
            "Cold outreach based on alignment with a problem the founder is "
            "solving — the investor resonates with the problem framing."
        ),
        detection_signals=[
            "problem_framing",
            "founder_articulation",
            "problem_space_research",
        ],
        email_pattern=(
            "Self-intro → Problem resonance showing personal understanding "
            "→ Roadmap interest → Meeting ask"
        ),
        preferred_length="short",
        priority_personalization=[
            "problem_framing",
            "founder_articulation",
        ],
    ),
    ContextType.COLD_MARKET_GAP: ContextTypeConfig(
        description=(
            "Cold outreach based on identifying a market gap the company is "
            "well-positioned to fill."
        ),
        detection_signals=[
            "market_gap",
            "product_thesis",
            "market_positioning",
        ],
        email_pattern=(
            "Credential-first intro → Direct product interest "
            "→ Brief market gap thesis statement → Quick ask"
        ),
        preferred_length="short",
        priority_personalization=[
            "product_thesis",
            "market_gap",
            "market_positioning",
        ],
    ),

    # ----- Sector / Domain (Cold) -----
    ContextType.COLD_DOMAIN_EXPERTISE: ContextTypeConfig(
        description=(
            "Cold outreach leveraging deep domain/sector expertise and prior "
            "investment experience in the space."
        ),
        detection_signals=[
            "sector_thesis",
            "prior_investment_experience",
            "domain_knowledge",
        ],
        email_pattern=(
            "Team/firm intro → Prior investment experience in sector "
            "→ Interest in company → Meeting ask"
        ),
        preferred_length="medium",
        priority_personalization=[
            "sector_thesis",
            "prior_investment_experience",
        ],
    ),
    ContextType.COLD_SECTOR_THESIS: ContextTypeConfig(
        description=(
            "Cold outreach driven by a sector-level thesis — the company fits "
            "within a broader investment theme."
        ),
        detection_signals=[
            "sector_thesis",
            "referral",
            "funding_announcement",
        ],
        email_pattern=(
            "Firm intro with sector focus → Company recommendation/discovery "
            "→ Team intro offer → Meeting ask"
        ),
        preferred_length="short",
        priority_personalization=[
            "sector_thesis",
            "referral",
        ],
    ),

    # ----- Personal / Affinity (Cold) -----
    ContextType.COLD_PERSONAL_AFFINITY: ContextTypeConfig(
        description=(
            "Cold outreach with a personal pain point or genuine affinity for "
            "what the product does."
        ),
        detection_signals=[
            "personal_pain_point",
            "product_usage",
            "personal_experience",
        ],
        email_pattern=(
            "Product discovery → Personal connection or pain point "
            "→ Investor intro → Meeting ask"
        ),
        preferred_length="medium",
        priority_personalization=[
            "personal_pain_point",
            "product_promise",
        ],
    ),
    ContextType.COLD_PERSONAL_CONNECTION: ContextTypeConfig(
        description=(
            "Cold outreach based on personal product usage or a direct "
            "personal connection to what the company does."
        ),
        detection_signals=[
            "personal_usage",
            "product_experience",
            "consumer_insight",
        ],
        email_pattern=(
            "Investor intro with personal usage story "
            "→ Product enthusiasm with specific details "
            "→ Geographic proximity if applicable "
            "→ Firm context block"
        ),
        preferred_length="medium",
        priority_personalization=[
            "personal_usage",
            "product_experience",
            "market_thesis",
        ],
    ),

    # ----- Research / Background (Cold) -----
    ContextType.RESEARCH_TO_FOUNDER_BRIDGE: ContextTypeConfig(
        description=(
            "Reaching out to a researcher who is transitioning to or has "
            "recently become a founder. Bridges academic work to startup."
        ),
        detection_signals=[
            "paper_reference",
            "research_background",
            "career_transition",
        ],
        email_pattern=(
            "Research reference showing deep familiarity "
            "→ Connection to broader AI/infrastructure trends "
            "→ Investor context emphasizing research-founder support "
            "→ Meeting ask"
        ),
        preferred_length="medium",
        priority_personalization=[
            "paper_reference",
            "research_connection",
            "career_transition",
        ],
    ),
    ContextType.COLD_SHARED_BACKGROUND: ContextTypeConfig(
        description=(
            "Cold outreach based on shared professional background — same "
            "employer, similar research area, overlapping experience."
        ),
        detection_signals=[
            "shared_employer",
            "shared_background",
            "overlapping_experience",
        ],
        email_pattern=(
            "Background intro highlighting shared connection "
            "→ Thesis interest → Meeting ask → Optional firm context block"
        ),
        preferred_length="short",
        priority_personalization=[
            "shared_background",
            "technical_thesis",
            "thesis_attachment",
        ],
    ),

    # ----- Funding / Launch Reactions (Cold) -----
    ContextType.COLD_FUNDING_CONGRATS: ContextTypeConfig(
        description=(
            "Reaching out after a funding announcement — congratulations as "
            "the hook, then sector thesis."
        ),
        detection_signals=[
            "funding_announcement",
            "recent_raise",
        ],
        email_pattern=(
            "Intro → Funding congratulations → Sector thesis/interest "
            "→ In-person or meeting ask"
        ),
        preferred_length="medium",
        priority_personalization=[
            "funding_announcement",
            "sector_thesis",
            "product_value_prop",
        ],
    ),
    ContextType.COLD_LAUNCH_REACTION: ContextTypeConfig(
        description=(
            "Reaching out after seeing a product launch, demo video, or "
            "public announcement."
        ),
        detection_signals=[
            "launch_video",
            "product_launch",
            "market_size",
        ],
        email_pattern=(
            "Firm intro with relevant portfolio → Launch reaction with market "
            "insight → Team members to involve → Meeting ask"
        ),
        preferred_length="medium",
        priority_personalization=[
            "launch_video",
            "market_size",
            "product_vision",
        ],
    ),

    # ----- Event-Based -----
    ContextType.EVENT_BASED_WARM_INTRO: ContextTypeConfig(
        description=(
            "Founder registered for or attended an investor-hosted or mutual "
            "event — warm intro opportunity."
        ),
        detection_signals=[
            "event_attendance",
            "event_registration",
        ],
        email_pattern=(
            "Event reference → Brief self-intro "
            "→ Interest in their work → In-person meeting ask"
        ),
        preferred_length="short",
        priority_personalization=[
            "event_context",
            "mutual_attendance",
        ],
    ),
    ContextType.POST_EVENT_FOLLOWUP: ContextTypeConfig(
        description=(
            "Following up after meeting someone at a conference or event — "
            "building on a prior interaction."
        ),
        detection_signals=[
            "prior_meeting",
            "event_name",
        ],
        email_pattern=(
            "Event reference recalling the interaction "
            "→ Colleague introduction → Next steps ask"
        ),
        preferred_length="short",
        priority_personalization=[
            "prior_meeting",
            "event_name",
        ],
    ),
    ContextType.COLD_CONFERENCE_FOLLOWUP: ContextTypeConfig(
        description=(
            "Reaching out after seeing a company at a conference (without "
            "having met the founder directly)."
        ),
        detection_signals=[
            "event_context",
            "conference_sighting",
        ],
        email_pattern=(
            "Credential intro with specific research background "
            "→ Conference reference → Thesis connection "
            "→ Firm context block → Ask"
        ),
        preferred_length="medium",
        priority_personalization=[
            "event_context",
            "technical_thesis",
            "product_category",
        ],
    ),

    # ----- Warm / Relationship-Based -----
    ContextType.WARM_CONGRATULATIONS: ContextTypeConfig(
        description=(
            "Warm outreach congratulating a known contact on a company "
            "announcement or new venture."
        ),
        detection_signals=[
            "company_announcement",
            "prior_relationship",
        ],
        email_pattern=(
            "Congratulations → Catch-up ask → Firm context block"
        ),
        preferred_length="short",
        priority_personalization=[
            "company_announcement",
        ],
    ),
    ContextType.WARM_INTRO_REQUEST: ContextTypeConfig(
        description=(
            "Asking a mutual contact for an introduction to a founder — the "
            "email is to the intermediary, not the founder."
        ),
        detection_signals=[
            "company_research",
            "mutual_contact",
            "market_interest",
        ],
        email_pattern=(
            "Company research mention → Intro request "
            "→ NEA context for forwarding → Personal touch"
        ),
        preferred_length="medium",
        priority_personalization=[
            "company_research",
            "market_interest",
        ],
    ),
    ContextType.WARM_PORTFOLIO_BRIDGE: ContextTypeConfig(
        description=(
            "Warm outreach bridging through portfolio company relationships — "
            "the investor already works with companies in the founder's space."
        ),
        detection_signals=[
            "portfolio_companies",
            "existing_relationship",
        ],
        email_pattern=(
            "Brief intro → Portfolio company connections "
            "→ Interest in learning more and helping"
        ),
        preferred_length="short",
        priority_personalization=[
            "portfolio_companies",
            "product_interest",
        ],
    ),

    # ----- Firm Context (Cold) -----
    ContextType.COLD_WITH_FIRM_CONTEXT: ContextTypeConfig(
        description=(
            "Cold outreach where product interest is generic enough to need "
            "a detailed firm context block for credibility."
        ),
        detection_signals=[
            "product_interest",
        ],
        email_pattern=(
            "Credential intro → Product interest "
            "→ Detailed firm context block → Ask"
        ),
        preferred_length="medium",
        priority_personalization=[
            "product_interest",
        ],
    ),

    # ----- Internal (excluded from outreach) -----
    ContextType.INTERNAL_DEEP_ANALYSIS: ContextTypeConfig(
        description=(
            "Internal analysis or memo — not for external outreach. Captures "
            "competitive landscape thinking and investment rationale."
        ),
        detection_signals=[
            "internal_only",
        ],
        email_pattern="N/A — internal document, not outreach",
        preferred_length="long",
        priority_personalization=[
            "competitive_landscape",
            "prior_investments",
            "market_analysis",
        ],
    ),
}


# =========================================================================
# DETECTION LOGIC
# =========================================================================

def detect_context_type(
    available_signals: list[str],
    has_prior_relationship: bool = False,
    has_event_context: bool = False,
) -> ContextType:
    """
    Determine the best context type for an outreach based on available data.

    Uses quick-path routing for warm/event contexts before falling back to
    score-based detection against each config's detection_signals.

    Args:
        available_signals: List of signal keys available for this outreach
            (e.g., ["funding_announcement", "product_capabilities"]).
        has_prior_relationship: True if there is a known prior relationship
            with the founder.
        has_event_context: True if there is a recent event/conference context.

    Returns:
        The best-matching ContextType.
    """
    signal_set = set(available_signals)

    # ----- Quick-path: warm / event contexts -----
    if has_prior_relationship:
        if "company_announcement" in signal_set:
            return ContextType.WARM_CONGRATULATIONS
        if "mutual_contact" in signal_set:
            return ContextType.WARM_INTRO_REQUEST
        if "portfolio_companies" in signal_set:
            return ContextType.WARM_PORTFOLIO_BRIDGE

    if has_event_context:
        if "prior_meeting" in signal_set or "event_name" in signal_set:
            return ContextType.POST_EVENT_FOLLOWUP
        if "event_attendance" in signal_set or "event_registration" in signal_set:
            return ContextType.EVENT_BASED_WARM_INTRO
        if "conference_sighting" in signal_set or "event_context" in signal_set:
            return ContextType.COLD_CONFERENCE_FOLLOWUP

    # ----- Score-based detection for cold contexts -----
    # Exclude warm/event/internal types from scoring — they're handled above
    _SKIP_IN_SCORING = {
        ContextType.WARM_CONGRATULATIONS,
        ContextType.WARM_INTRO_REQUEST,
        ContextType.WARM_PORTFOLIO_BRIDGE,
        ContextType.EVENT_BASED_WARM_INTRO,
        ContextType.POST_EVENT_FOLLOWUP,
        ContextType.COLD_CONFERENCE_FOLLOWUP,
        ContextType.INTERNAL_DEEP_ANALYSIS,
    }

    best_type = ContextType.COLD_WITH_FIRM_CONTEXT  # safe fallback
    best_score = (0, 0.0)

    for ctx_type, config in CONTEXT_TYPE_CONFIGS.items():
        if ctx_type in _SKIP_IN_SCORING:
            continue

        overlap = signal_set & set(config.detection_signals)
        if not overlap:
            continue

        # Primary: raw overlap count (more evidence wins).
        # Tiebreaker: precision ratio (overlap / total signals for that type).
        score = (len(overlap), len(overlap) / len(config.detection_signals))

        if score > best_score:
            best_score = score
            best_type = ctx_type

    return best_type

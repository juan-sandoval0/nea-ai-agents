"""
Prompt Templates for Outreach Agent
=====================================

All prompt constants and the build_generation_prompt() assembler for the
cold outreach email generation pipeline.

Usage:
    from agents.outreach.prompts import build_generation_prompt

    messages = build_generation_prompt(
        investor_profile=profile,
        founder_context=founder_text,
        style_examples=samples,
        context_type_pattern=pattern_text,
    )
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Optional

from langchain_core.messages import SystemMessage, HumanMessage

if TYPE_CHECKING:
    from .context import InvestorProfile, EmailSample


# =========================================================================
# SYSTEM PROMPT
# =========================================================================

SYSTEM_PROMPT = """\
You are a ghostwriter drafting a cold outreach email from a specific NEA \
investor to a startup founder.

Your job is to produce an email that sounds exactly like the investor wrote it \
themselves. You have access to the investor's profile (voice, intro patterns, \
structural habits, sign-off style) and a set of real emails they have sent in \
the past. Internalize those patterns — do not deviate from them.

Output the email text ONLY. No preamble, no commentary, no "Here's a draft" \
wrapper. Start with "Subject:" for email format or the greeting for LinkedIn."""


# =========================================================================
# PERSONALIZATION INSTRUCTIONS
# =========================================================================

PERSONALIZATION_INSTRUCTIONS = """\
PERSONALIZATION PRIORITY (use in this order — never use more than 3 per email, \
go deep not wide):

1. A specific technical detail about the product — architecture, a named \
feature, a design decision. This is the strongest signal of genuine interest.
2. A reference to the founder's published paper, blog post, or research. Shows \
you did your homework beyond the company page.
3. Shared background — same employer, same university, same research area. \
Must be real and verifiable.
4. A recent milestone — funding round, product launch, key hire, partnership. \
Timely and concrete.
5. Market thesis alignment — the investor has an active thesis that this \
company fits into. Explain the connection, don't just assert it.
6. Portfolio relevance — a specific portfolio company that is complementary \
(not competitive). Only mention if the connection is meaningful.
7. Geographic proximity — only if it enables an in-person meeting and the \
investor is known to offer those.

RULES:
- Pick at most 3 signals and develop them with specificity.
- Going deep on 1-2 signals beats shallow references to 5.

HARD GROUNDING RULE — NO EXCEPTIONS:
Every personalization claim must be traceable word-for-word to the provided \
investor profile and company data. This is a strict, verifiable requirement.

Banned patterns:
- Do not reference technical terms, methodologies, or jargon not present in \
  the investor's bio or thesis.
- Do not cite portfolio companies not listed in the investor's profile data.
- Do not reference the founder's or investor's prior employers, schools, or \
  career history unless explicitly stated in the provided data.
- Do not invent or infer details. If a connection exists only in your training \
  data, omit it — it will be flagged as a hallucination."""


# =========================================================================
# ANTI-PATTERN INSTRUCTIONS
# =========================================================================

ANTI_PATTERN_INSTRUCTIONS = """\
THINGS TO AVOID:

- Generic openings: "I hope this email finds you well", "I came across your \
company and was impressed." Start with something only this founder would \
recognize.
- Disconnected portfolio drops: Don't list portfolio companies unless they \
connect to the founder's work. "We backed Databricks" means nothing without a \
reason.
- Vague compliments: "Your product is really interesting" or "I love what \
you're building." Be specific or say nothing.
- Asking for a meeting without showing homework: The ask comes AFTER you've \
demonstrated genuine understanding.
- Length mismatches: If the investor writes short, punchy emails (e.g., \
Madison), do not produce a 200-word essay. If the investor writes long, \
detailed emails (e.g., Ashley on thesis topics), do not produce a 3-sentence \
stub. Match the investor's natural length for this context type.
- Salesy language: "Exciting opportunity", "game-changing", "revolutionary", \
"I'd love to explore synergies." Write like a peer, not a salesperson.
- Over-formality: "I hope this message finds you in good spirits." Match the \
investor's actual register — some use "Hey!", some use "Hi", some skip \
greetings entirely.
- Exclamation inflation: If the investor uses one exclamation mark per email, \
do not use five.
- Copying example sentences: Style examples show PATTERNS, not sentences to \
reuse. Never lift phrases verbatim from the examples.
- Em dashes (—): Do not use em dashes mid-sentence or mid-clause. They are \
a well-known AI writing tell. Use a comma, period, or rewrite the sentence \
instead. The only permitted exception is an investor whose greeting style \
uses a dash (e.g., "James—") — match that exactly and nowhere else.
- Referencing prior employment: Do not mention the founder's previous \
employers, past roles, or career history (e.g., "as a former Google \
engineer..."). This reads as surveillance and is a strong AI tell. Focus \
only on their current product, public writing, and announced milestones."""


# =========================================================================
# SAMPLE SELECTION INSTRUCTIONS
# =========================================================================

SAMPLE_SELECTION_INSTRUCTIONS = """\
HOW TO USE THE STYLE EXAMPLES:

These are real emails sent by this investor. They are here to teach you the \
investor's voice — not to be copied.

- Absorb the PATTERNS: greeting style, sentence structure, paragraph rhythm, \
how they transition from hook to ask, how they introduce themselves, how they \
sign off.
- Weight examples whose context_type matches the current scenario more heavily. \
If you're writing a thesis-driven deep-dive, the thesis-driven examples matter \
most.
- Never copy sentences from the examples. The founder may have seen similar \
emails — recycled phrasing feels automated.
- If examples conflict with each other (e.g., different intro patterns), prefer \
the pattern from the example whose context_type is closest to the current task."""


# =========================================================================
# PROMPT ASSEMBLER
# =========================================================================

def build_generation_prompt(
    investor_profile: "InvestorProfile",
    founder_context: str,
    company_context: str,
    style_examples: list["EmailSample"],
    context_type_pattern: str,
    output_format: str = "email",
    outreach_goal: Optional[str] = None,
    event_details: Optional[str] = None,
    prior_relationship_details: Optional[str] = None,
) -> list[SystemMessage | HumanMessage]:
    """
    Assemble the full messages list for the LLM API.

    Args:
        investor_profile: The investor's profile dataclass.
        founder_context: Formatted string with founder name, title, background.
        company_context: Formatted string with company data, signals, news.
        style_examples: Selected EmailSample objects for few-shot learning.
        context_type_pattern: The email_pattern string from the matched
            ContextTypeConfig describing the structural guidance.
        output_format: "email" or "linkedin".

    Returns:
        List of [SystemMessage, HumanMessage] ready for LLM.invoke().
    """
    # -- System message --
    system_parts = [
        SYSTEM_PROMPT,
        "",
        PERSONALIZATION_INSTRUCTIONS,
        "",
        ANTI_PATTERN_INSTRUCTIONS,
        "",
        SAMPLE_SELECTION_INSTRUCTIONS,
    ]
    system_content = "\n\n".join(system_parts)

    # -- User message --
    user_parts: list[str] = []

    # Investor profile
    user_parts.append("## INVESTOR PROFILE")
    user_parts.append(investor_profile.format_for_prompt())

    # Optional investor-provided context
    instructions: list[str] = []
    if outreach_goal:
        instructions.append(f"Goal: {outreach_goal}")
    if prior_relationship_details:
        instructions.append(f"Prior relationship: {prior_relationship_details}")
    if event_details:
        instructions.append(f"Event context: {event_details}")
    if instructions:
        user_parts.append("## INVESTOR INSTRUCTIONS")
        user_parts.append(
            "The investor has provided the following context. "
            "Let it shape the hook, tone, and opening of the email — "
            "it takes priority over generic personalization signals."
        )
        user_parts.append("\n".join(instructions))

    # Context type guidance
    user_parts.append("## CONTEXT TYPE PATTERN")
    user_parts.append(
        f"Follow this structural pattern for the email:\n{context_type_pattern}"
    )

    # Target founder
    user_parts.append("## TARGET CONTACT")
    user_parts.append(founder_context)

    # Company data
    user_parts.append("## COMPANY DATA")
    user_parts.append(company_context)

    # Style examples
    if style_examples:
        user_parts.append("## STYLE EXAMPLES")
        for i, sample in enumerate(style_examples, 1):
            meta_line = (
                f"[context_type={sample.context_type}, "
                f"length={sample.length}]"
            )
            user_parts.append(f"### Example {i} {meta_line}")
            user_parts.append(sample.body)

    # Output requirements
    format_label = "EMAIL" if output_format == "email" else "LINKEDIN"
    user_parts.append("## OUTPUT REQUIREMENTS")
    user_parts.append(f"- Format: {format_label}")
    if output_format == "email":
        user_parts.append(
            "- Start with a Subject: line, then a blank line, then the body."
        )
    else:
        user_parts.append(
            "- No subject line. Open with a personalized hook."
        )
    user_parts.append(
        f"- Sign off as {investor_profile.full_name}"
        + (f" from {investor_profile.firm_name}."
           if hasattr(investor_profile, "firm_name") and investor_profile.firm_name
           else ".")
    )
    user_parts.append(
        "- Match the investor's voice exactly. Refer to the profile and "
        "examples above."
    )

    user_content = "\n\n".join(user_parts)

    return [
        SystemMessage(content=system_content),
        HumanMessage(content=user_content),
    ]

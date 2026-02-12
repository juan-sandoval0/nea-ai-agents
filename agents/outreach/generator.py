"""
Outreach Message Generator
===========================

Core generation pipeline for personalized cold outreach messages.
Follows the pattern in agents/meeting_briefing/briefing_generator.py.

Reuses existing data infrastructure (Harmonic, Swarm, Parallel Search, Tavily)
to gather company/founder intel, then generates a tailored email or LinkedIn
message via LLM.

Usage:
    from agents.outreach.generator import generate_outreach

    result = generate_outreach("stripe.com", output_format="email")
    print(result["message"])
"""

from __future__ import annotations

import logging
import time
from datetime import datetime
from typing import Optional

from langchain_openai import ChatOpenAI
from langchain_core.messages import SystemMessage, HumanMessage

from core.database import CompanyBundle, Founder, KeySignal, NewsArticle
from core.tracking import get_tracker
from core.prompt_registry import get_prompt, get_model_config, LLMCallMetadata
from core.security import (
    sanitize_company_name,
    sanitize_for_prompt,
    detect_prompt_injection,
    log_security_event,
)
from core.observability import (
    get_logger,
    log_llm_interaction,
    log_audit_event,
    trace_function,
    set_request_context,
    clear_request_context,
)
from tools.company_tools import get_company_bundle, normalize_company_id, ingest_company

from .context import get_investor_context

logger = get_logger(__name__)

# =============================================================================
# CONFIGURATION
# =============================================================================

DEFAULT_LLM_MODEL = "gpt-4o-mini"

OUTREACH_SYSTEM_PROMPT = """You are an AI assistant generating personalized cold outreach messages for venture capital investors to send to startup founders.

CRITICAL RULES:
- Use ONLY the provided data about the company, founder, and investor. Do NOT hallucinate or infer facts.
- Reference specific data points from the provided context (funding rounds, signals, founder background, product details).
- Write in a peer-to-peer tone — one professional to another. NOT salesy, NOT generic.
- Show genuine interest by citing concrete details about the company or founder.
- If the founder has a notable background, mention shared context naturally (do not force it).
- Keep the message concise and respectful of the founder's time.

FORMAT RULES:
- For EMAIL format: Keep under 150 words. Start with a "Subject:" line on its own, then a blank line, then the message body.
- For LINKEDIN format: Keep under 100 words. No subject line. Open with a brief, personalized hook.

TONE:
- Professional but warm
- Curious, not presumptuous
- Specific, not templated
- Investor reaching out as a peer, not pitching services
- If style examples are provided, match their tone and structure closely."""


# =============================================================================
# CONTACT SELECTION
# =============================================================================

def select_contact(
    founders: list[Founder],
    preferred_name: Optional[str] = None,
) -> Optional[Founder]:
    """
    Select the best contact from a list of founders.

    If preferred_name is given, performs case-insensitive name match.
    Otherwise scores founders: +3 for CEO/CTO/Founder title, +2 for has
    LinkedIn URL, +1 for has background.

    Args:
        founders: List of Founder objects
        preferred_name: Optional name to match

    Returns:
        Best-scored Founder, or None if list is empty
    """
    if not founders:
        return None

    if preferred_name:
        preferred_lower = preferred_name.lower()
        for f in founders:
            if f.name.lower() == preferred_lower:
                return f
        # Partial match fallback
        for f in founders:
            if preferred_lower in f.name.lower() or f.name.lower() in preferred_lower:
                return f
        logger.warning(f"Contact '{preferred_name}' not found among founders, auto-selecting")

    # Score-based selection
    def score(f: Founder) -> int:
        s = 0
        if f.role_title:
            title_lower = f.role_title.lower()
            if any(kw in title_lower for kw in ["ceo", "cto", "founder", "co-founder", "cofounder"]):
                s += 3
        if f.linkedin_url:
            s += 2
        if f.background:
            s += 1
        return s

    return max(founders, key=score)


# =============================================================================
# DATA FORMATTING
# =============================================================================

def format_company_context(bundle: CompanyBundle) -> str:
    """
    Format company data concisely for outreach context.

    Includes snapshot (name, funding, headcount, HQ, products), top 5 key
    signals, and top 5 news headlines.
    """
    lines = []
    company = bundle.company_core

    if company:
        lines.append(f"Company: {company.company_name}")

        if company.hq:
            lines.append(f"HQ: {company.hq}")

        if company.employee_count:
            lines.append(f"Employees: {company.employee_count:,}")

        if company.products:
            lines.append(f"Products: {company.products}")

        if company.total_funding:
            lines.append(f"Total Funding: ${company.total_funding:,.0f}")

        if company.last_round_date and company.last_round_funding:
            lines.append(f"Last Round: ${company.last_round_funding:,.0f} on {company.last_round_date}")
        elif company.last_round_date:
            lines.append(f"Last Round Date: {company.last_round_date}")

        if company.founding_date:
            lines.append(f"Founded: {company.founding_date}")

    # Top 5 key signals
    if bundle.key_signals:
        lines.append("\nKey Signals:")
        for s in bundle.key_signals[:5]:
            lines.append(f"- [{s.signal_type.upper()}] {s.description}")

    # Top 5 news headlines (headline + outlet only)
    if bundle.news:
        lines.append("\nRecent News:")
        for n in bundle.news[:5]:
            headline = n.article_headline
            if n.outlet:
                headline += f" ({n.outlet})"
            lines.append(f"- {headline}")

    return "\n".join(lines)


def format_contact_context(contact: Founder) -> str:
    """Format selected contact info for the outreach prompt."""
    lines = []
    lines.append(f"Name: {contact.name}")

    if contact.role_title:
        lines.append(f"Title: {contact.role_title}")

    if contact.linkedin_url:
        lines.append(f"LinkedIn: {contact.linkedin_url}")

    if contact.background:
        bg_text = contact.background.split("\n---\n")[0].strip()
        lines.append(f"Background: {bg_text}")

    return "\n".join(lines)


# =============================================================================
# OUTREACH GENERATION
# =============================================================================

@trace_function(operation="generate_outreach")
def generate_outreach(
    company_id: str,
    output_format: str = "email",
    contact_name: Optional[str] = None,
    investor_name: Optional[str] = None,
    firm_name: Optional[str] = None,
    model: str = DEFAULT_LLM_MODEL,
    skip_ingest: bool = False,
    samples_file: Optional[str] = None,
) -> dict:
    """
    Generate a personalized outreach message for a founder at a target company.

    Pipeline:
    1. Normalize company ID
    2. Ingest company data (unless skip_ingest)
    3. Get company bundle from DB
    4. Select target contact
    5. Build investor context
    6. Sanitize all data
    7. Call LLM with system + user prompt
    8. Parse and return result

    Args:
        company_id: Company URL or domain
        output_format: "email" or "linkedin" (default: "email")
        contact_name: Optional target contact name (auto-selects if None)
        investor_name: Optional investor name for the message
        firm_name: Optional firm name for the message
        model: LLM model to use
        skip_ingest: If True, use cached DB data only
        samples_file: Path to style samples file (None=auto-detect, ""=disabled)

    Returns:
        Dict with message, metadata, and success/error status
    """
    normalized_id = normalize_company_id(company_id)
    set_request_context(company_id=normalized_id, operation="outreach")

    result = {
        "company_id": normalized_id,
        "company_name": None,
        "contact_name": None,
        "contact_title": None,
        "contact_linkedin": None,
        "output_format": output_format,
        "message": None,
        "subject": None,
        "generated_at": datetime.utcnow().isoformat(),
        "data_sources": {
            "company_core": False,
            "founders": 0,
            "signals": 0,
            "news": 0,
        },
        "success": False,
        "error": None,
    }

    try:
        # Step 1: Ingest company data
        if not skip_ingest:
            logger.info(f"Ingesting data for {normalized_id}...")
            ingest_company(normalized_id)

        # Step 2: Get company bundle
        bundle = get_company_bundle(company_id)

        if not bundle.company_core:
            result["error"] = "Company not found in database. Run ingest_company first."
            clear_request_context()
            return result

        result["company_name"] = bundle.company_core.company_name
        result["data_sources"]["company_core"] = True
        result["data_sources"]["founders"] = len(bundle.founders)
        result["data_sources"]["signals"] = len(bundle.key_signals)
        result["data_sources"]["news"] = len(bundle.news)

        # Step 3: Select contact
        contact = select_contact(bundle.founders, preferred_name=contact_name)
        if contact:
            result["contact_name"] = contact.name
            result["contact_title"] = contact.role_title
            result["contact_linkedin"] = contact.linkedin_url

        # Step 4: Build investor context
        investor_ctx = get_investor_context(
            investor_name=investor_name,
            firm_name=firm_name,
            samples_file=samples_file,
        )

        # Step 5: Sanitize all data
        safe_company_name = sanitize_company_name(bundle.company_core.company_name)
        company_context = format_company_context(bundle)
        safe_company_context = sanitize_for_prompt(company_context, escape_markdown=False)

        contact_context = format_contact_context(contact) if contact else "No contact information available."
        safe_contact_context = sanitize_for_prompt(contact_context, escape_markdown=False)

        investor_context = investor_ctx.format_for_prompt()
        safe_investor_context = sanitize_for_prompt(investor_context, escape_markdown=False)

        # Check for prompt injection
        for field_name, field_data in [
            ("company_context", company_context),
            ("contact_context", contact_context),
        ]:
            detection = detect_prompt_injection(field_data)
            if detection.is_suspicious:
                log_security_event(
                    "prompt_injection_attempt",
                    {
                        "company_id": normalized_id,
                        "field": field_name,
                        "confidence": detection.confidence,
                    },
                    severity="warning",
                )

        # Step 6: Build style examples section
        style_section = ""
        if investor_ctx.style_examples:
            sanitized_examples = []
            for i, ex in enumerate(investor_ctx.style_examples, 1):
                safe_ex = sanitize_for_prompt(ex, escape_markdown=False)
                sanitized_examples.append(f"### Example {i}\n{safe_ex}")
            examples_block = "\n\n".join(sanitized_examples)
            style_section = f"""

## STYLE EXAMPLES
Match the tone, structure, and voice of these real emails. Do NOT copy them — use them as inspiration for the writing style.

{examples_block}
"""

        # Step 7: Build user prompt
        format_label = "EMAIL" if output_format == "email" else "LINKEDIN"
        user_prompt = f"""Generate a personalized {format_label} outreach message for the following target.

## TARGET CONTACT
{safe_contact_context}

## COMPANY DATA
{safe_company_context}

## INVESTOR CONTEXT
{safe_investor_context}
{style_section}
## OUTPUT REQUIREMENTS
- Format: {format_label}
- {"Include a Subject: line at the top, followed by a blank line, then the message body." if output_format == "email" else "No subject line. Open with a personalized hook."}
- Reference specific details from the company data and founder background.
- Sign off as {investor_ctx.investor_name} from {investor_ctx.firm_name}.
"""

        # Step 8: Get system prompt and model config
        try:
            system_prompt_obj = get_prompt("outreach_system")
            system_prompt_content = system_prompt_obj.content
        except KeyError:
            system_prompt_obj = None
            system_prompt_content = OUTREACH_SYSTEM_PROMPT

        try:
            model_config = get_model_config("outreach")
            actual_model = model_config.model if model == DEFAULT_LLM_MODEL else model
            temperature = model_config.temperature
        except KeyError:
            model_config = None
            actual_model = model
            temperature = 0.3

        # Create call metadata
        call_metadata = LLMCallMetadata.create(
            operation="outreach",
            prompt=system_prompt_obj,
            model_config=model_config,
            system_prompt=system_prompt_content,
            user_prompt=user_prompt,
            company_id=normalized_id,
            model=actual_model,
            temperature=temperature,
        )

        # Step 9: Call LLM
        tracker = get_tracker()
        llm = ChatOpenAI(model=actual_model, temperature=temperature)
        messages = [
            SystemMessage(content=system_prompt_content),
            HumanMessage(content=user_prompt),
        ]

        start_time = time.time()
        response = llm.invoke(messages)
        latency_ms = int((time.time() - start_time) * 1000)

        raw_content = response.content
        tokens_in = response.usage_metadata.get("input_tokens", 0) if hasattr(response, "usage_metadata") and response.usage_metadata else 0
        tokens_out = response.usage_metadata.get("output_tokens", 0) if hasattr(response, "usage_metadata") and response.usage_metadata else 0

        call_metadata.tokens_in = tokens_in
        call_metadata.tokens_out = tokens_out
        call_metadata.latency_ms = latency_ms

        # Step 10: Parse output
        message_text = raw_content.strip()
        subject = None

        if output_format == "email" and message_text.lower().startswith("subject:"):
            lines = message_text.split("\n", 1)
            subject = lines[0].replace("Subject:", "").replace("subject:", "").strip()
            message_text = lines[1].strip() if len(lines) > 1 else message_text

        result["message"] = message_text
        result["subject"] = subject
        result["success"] = True

        # Step 11: Log everything
        tracker.log_api_call(
            service="openai",
            endpoint=f"/chat/completions ({actual_model})",
            method="POST",
            status_code=200,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            latency_ms=latency_ms,
            metadata={
                "company_id": normalized_id,
                "llm_call_id": call_metadata.call_id,
                "prompt_id": call_metadata.prompt_id,
                "prompt_version": call_metadata.prompt_version,
                "output_format": output_format,
            },
        )

        tracker.log_llm_call(
            call_id=call_metadata.call_id,
            model=actual_model,
            operation="outreach",
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            latency_ms=latency_ms,
            prompt_id=call_metadata.prompt_id,
            prompt_version=call_metadata.prompt_version,
            prompt_hash=call_metadata.prompt_hash,
            system_prompt_hash=call_metadata.system_prompt_hash,
            user_prompt_hash=call_metadata.user_prompt_hash,
            model_config_name=call_metadata.model_config_name,
            temperature=temperature,
            company_id=normalized_id,
            success=True,
        )

        tracker.log_usage(
            company_id=normalized_id,
            action="outreach",
            metadata={
                "model": actual_model,
                "output_format": output_format,
                "contact_name": result["contact_name"],
                "tokens_in": tokens_in,
                "tokens_out": tokens_out,
            },
        )

        log_llm_interaction(
            operation="outreach",
            model=actual_model,
            system_prompt=system_prompt_content,
            user_prompt=user_prompt,
            response=raw_content,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            latency_ms=latency_ms,
            success=True,
            temperature=temperature,
            model_config_name=call_metadata.model_config_name,
            company_id=normalized_id,
        )

        log_audit_event(
            event_type="outreach",
            action="create",
            resource_type="outreach_message",
            resource_id=normalized_id,
            details={
                "company_name": bundle.company_core.company_name,
                "contact_name": result["contact_name"],
                "output_format": output_format,
                "model": actual_model,
                "tokens_total": tokens_in + tokens_out,
                "latency_ms": latency_ms,
            },
        )

        logger.info(
            f"Generated {output_format} outreach for {safe_company_name} "
            f"(contact: {result['contact_name']})"
        )

    except Exception as e:
        result["error"] = f"Outreach generation failed: {str(e)}"
        logger.error(f"Outreach generation failed for {company_id}: {e}")

        # Log the failed call if metadata was created
        try:
            tracker = get_tracker()
            tracker.log_llm_call(
                call_id=call_metadata.call_id,
                model=call_metadata.model or model,
                operation="outreach",
                prompt_id=call_metadata.prompt_id,
                prompt_version=call_metadata.prompt_version,
                company_id=normalized_id,
                success=False,
                error_message=str(e),
            )

            log_llm_interaction(
                operation="outreach",
                model=call_metadata.model or model,
                success=False,
                error_type=type(e).__name__,
                error_message=str(e),
                company_id=normalized_id,
            )
        except Exception:
            pass  # Don't fail on logging errors

    finally:
        clear_request_context()

    return result

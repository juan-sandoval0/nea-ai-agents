"""
Outreach Message Generator
===========================

Core generation pipeline for personalized cold outreach messages.

Reuses existing data infrastructure (Harmonic, Swarm, Parallel Search, Tavily)
to gather company/founder intel, then generates a tailored email or LinkedIn
message via LLM using investor-specific voice profiles and annotated style
examples.

Usage:
    from agents.outreach.generator import generate_outreach

    result = generate_outreach("stripe.com", investor_key="ashley")
    print(result["message"])
"""

from __future__ import annotations

import logging
import time
from datetime import datetime
from typing import Optional

from langchain_openai import ChatOpenAI
from langchain_anthropic import ChatAnthropic

from core.database import CompanyBundle, Founder
from core.tracking import get_tracker
from core.prompt_registry import get_model_config, LLMCallMetadata
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
from services.history import get_outreach_history, get_audit_log
from tools.company_tools import get_company_bundle, normalize_company_id, ingest_company

from .context import get_investor_context, load_samples
from .context_types import detect_context_type, CONTEXT_TYPE_CONFIGS, ContextType
from .prompts import build_generation_prompt

logger = get_logger(__name__)

# =============================================================================
# CONFIGURATION
# =============================================================================

DEFAULT_LLM_MODEL = "claude-sonnet-4-5-20250929"
DEFAULT_INVESTOR_KEY = "ashley"


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

    # Background intentionally excluded — prior employment is used for signal
    # detection only and should not be passed to the LLM prompt directly.

    return "\n".join(lines)


# =============================================================================
# SIGNAL EXTRACTION (for context type detection)
# =============================================================================

def _extract_available_signals(bundle: CompanyBundle, contact: Optional[Founder]) -> list[str]:
    """
    Derive available personalization signal keys from the company bundle.

    Maps raw data into the signal vocabulary used by context_types.py for
    detection scoring.
    """
    signals: list[str] = []

    # From key_signals
    if bundle.key_signals:
        signal_types = {s.signal_type.lower() for s in bundle.key_signals}
        signal_descs = " ".join(s.description.lower() for s in bundle.key_signals)

        if "funding" in signal_types or "funding" in signal_descs:
            signals.append("funding_announcement")
        if "hiring" in signal_types or "team_change" in signal_types:
            signals.append("market_gap")
        if "website_update" in signal_types or "product_launch" in signal_types:
            signals.append("product_launch")
            signals.append("product_capabilities")
        if "traffic" in signal_types:
            signals.append("product_interest")

    # From company data
    if bundle.company_core:
        if bundle.company_core.products:
            signals.append("product_capabilities")
            signals.append("technical_architecture")
        if bundle.company_core.total_funding:
            signals.append("sector_thesis")

    # From news
    if bundle.news:
        news_text = " ".join(n.article_headline.lower() for n in bundle.news[:5])
        if any(kw in news_text for kw in ["launch", "release", "announce"]):
            signals.append("product_launch")
        if any(kw in news_text for kw in ["raise", "fund", "series", "seed"]):
            signals.append("funding_announcement")

    # From contact background
    if contact and contact.background:
        bg = contact.background.lower()
        if any(kw in bg for kw in ["research", "phd", "professor", "paper"]):
            signals.append("research_background")
            signals.append("paper_reference")
        if any(kw in bg for kw in ["meta", "google", "facebook", "amazon", "apple"]):
            signals.append("shared_employer")
            signals.append("shared_background")

    # Deduplicate
    return list(set(signals))


# =============================================================================
# STEALTH OUTREACH GENERATION
# =============================================================================

def _generate_stealth_outreach(
    founder_linkedin_url: str,
    founder_background_notes: Optional[str],
    contact_name: Optional[str],
    investor_key: str,
    output_format: str,
    model: str,
    outreach_goal: Optional[str],
    event_details: Optional[str],
    prior_relationship_details: Optional[str],
) -> dict:
    """
    Generate a founder-centric outreach email for a stealth-mode contact.

    Enriches the person via Swarm (LinkedIn scrape) and generates an email that
    leads with the investor's thesis and the founder's background rather than
    company details, since no public company exists to reference.
    """
    from core.clients import SwarmClient

    result = {
        "company_id": founder_linkedin_url,
        "company_name": "[Stealth]",
        "contact_name": contact_name,
        "contact_title": None,
        "contact_linkedin": founder_linkedin_url,
        "investor_key": investor_key,
        "output_format": output_format,
        "context_type": ContextType.STEALTH_FOUNDER_OUTREACH.value,
        "message": None,
        "subject": None,
        "generated_at": datetime.utcnow().isoformat(),
        "data_sources": {
            "company_core": False,
            "founders": 0,
            "signals": 0,
            "news": 0,
        },
        "stealth_mode": True,
        "success": False,
        "error": None,
    }

    try:
        # Step 1: Enrich via Swarm
        swarm_succeeded = False
        background_text = ""
        resolved_name = contact_name or "there"
        resolved_title = "Building in stealth"

        try:
            swarm = SwarmClient()
            profile = swarm.get_profile_by_linkedin(founder_linkedin_url)
            if profile:
                background_text = profile.format_background()
                if profile.full_name:
                    resolved_name = profile.full_name
                if profile.current_title:
                    resolved_title = profile.current_title
                result["contact_name"] = resolved_name
                result["contact_title"] = resolved_title
                result["data_sources"]["founders"] = 1
                swarm_succeeded = True
            else:
                logger.warning(f"Swarm returned no profile for {founder_linkedin_url}")
        except Exception as swarm_err:
            logger.warning(f"Swarm enrichment failed for stealth outreach: {swarm_err}")

        # Step 2: Build founder context string
        founder_context_parts = [
            f"Name: {resolved_name}",
            f"Title: {resolved_title}",
            f"LinkedIn: {founder_linkedin_url}",
        ]
        if background_text:
            founder_context_parts.append(f"Background:\n{background_text}")
        if founder_background_notes:
            founder_context_parts.append(f"Additional context: {founder_background_notes}")
        founder_context = "\n".join(founder_context_parts)

        # Step 3: Build minimal company context string
        company_context_parts = [
            "Company: [Stealth]",
            "Status: Building in stealth — no public company information available.",
        ]
        if founder_background_notes:
            company_context_parts.append(f"Investor notes: {founder_background_notes}")
        company_context = "\n".join(company_context_parts)

        # Step 4: Security checks
        for field_name, field_data in [
            ("founder_context", founder_context),
            ("company_context", company_context),
        ]:
            detection = detect_prompt_injection(field_data)
            if detection.is_suspicious:
                log_security_event(
                    "prompt_injection_attempt",
                    {
                        "company_id": founder_linkedin_url,
                        "field": field_name,
                        "confidence": detection.confidence,
                    },
                    severity="warning",
                )

        safe_founder_context = sanitize_for_prompt(founder_context, escape_markdown=False)
        safe_company_context = sanitize_for_prompt(company_context, escape_markdown=False)

        # Step 5: Load investor profile and style examples
        investor_profile = get_investor_context(investor_key)
        ctx_type = ContextType.STEALTH_FOUNDER_OUTREACH
        ctx_config = CONTEXT_TYPE_CONFIGS[ctx_type]

        static_examples = load_samples(investor_key=investor_key, context_type=ctx_type.value)
        try:
            from services.feedback import load_promoted_samples
            promoted = load_promoted_samples(investor_key)
            promoted_matching = [s for s in promoted if s.context_type == ctx_type.value]
            combined = promoted_matching + static_examples
            style_examples = combined[:3]
        except Exception:
            style_examples = static_examples

        # Step 6: Build prompts
        messages = build_generation_prompt(
            investor_profile=investor_profile,
            founder_context=safe_founder_context,
            company_context=safe_company_context,
            style_examples=style_examples,
            context_type_pattern=ctx_config.email_pattern,
            output_format=output_format,
            outreach_goal=outreach_goal,
            event_details=event_details,
            prior_relationship_details=prior_relationship_details,
        )

        system_prompt_content = messages[0].content
        user_prompt = messages[1].content

        # Step 7: Get model config and call LLM
        try:
            model_config = get_model_config("outreach")
            actual_model = model_config.model if model == DEFAULT_LLM_MODEL else model
            temperature = model_config.temperature
        except KeyError:
            model_config = None
            actual_model = model
            temperature = 0.3

        is_anthropic = actual_model.startswith("claude")
        if is_anthropic:
            llm = ChatAnthropic(model=actual_model, temperature=temperature)
        else:
            llm = ChatOpenAI(model=actual_model, temperature=temperature)

        start_time = time.time()
        response = llm.invoke(messages)
        latency_ms = int((time.time() - start_time) * 1000)

        raw_content = response.content
        tokens_in = response.usage_metadata.get("input_tokens", 0) if hasattr(response, "usage_metadata") and response.usage_metadata else 0
        tokens_out = response.usage_metadata.get("output_tokens", 0) if hasattr(response, "usage_metadata") and response.usage_metadata else 0

        # Step 8: Parse output
        message_text = raw_content.strip()
        subject = None
        if output_format == "email" and message_text.lower().startswith("subject:"):
            lines = message_text.split("\n", 1)
            subject = lines[0].replace("Subject:", "").replace("subject:", "").strip()
            message_text = lines[1].strip() if len(lines) > 1 else message_text

        result["message"] = message_text
        result["subject"] = subject
        result["success"] = True

        log_llm_interaction(
            operation="outreach_stealth",
            model=actual_model,
            system_prompt=system_prompt_content,
            user_prompt=user_prompt,
            response=raw_content,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            latency_ms=latency_ms,
            success=True,
            temperature=temperature,
            company_id=founder_linkedin_url,
        )

        log_audit_event(
            event_type="outreach",
            action="create",
            resource_type="outreach_message",
            resource_id=founder_linkedin_url,
            details={
                "stealth_mode": True,
                "contact_name": resolved_name,
                "investor_key": investor_key,
                "context_type": ctx_type.value,
                "output_format": output_format,
                "model": actual_model,
                "swarm_enriched": swarm_succeeded,
                "tokens_total": tokens_in + tokens_out,
                "latency_ms": latency_ms,
            },
        )

        logger.info(
            f"Generated stealth outreach for {resolved_name} "
            f"(investor: {investor_key}, swarm_enriched: {swarm_succeeded})"
        )

    except Exception as e:
        result["error"] = f"Stealth outreach generation failed: {str(e)}"
        logger.error(f"Stealth outreach generation failed for {founder_linkedin_url}: {e}")

    return result


# =============================================================================
# OUTREACH GENERATION
# =============================================================================

@trace_function(operation="generate_outreach")
def generate_outreach(
    company_id: str,
    output_format: str = "email",
    contact_name: Optional[str] = None,
    investor_key: str = DEFAULT_INVESTOR_KEY,
    model: str = DEFAULT_LLM_MODEL,
    skip_ingest: bool = False,
    context_type_override: Optional[str] = None,
    outreach_goal: Optional[str] = None,
    has_event_context: bool = False,
    event_details: Optional[str] = None,
    has_prior_relationship: bool = False,
    prior_relationship_details: Optional[str] = None,
    stealth_mode: bool = False,
    founder_linkedin_url: Optional[str] = None,
    founder_background_notes: Optional[str] = None,
) -> dict:
    """
    Generate a personalized outreach message for a founder at a target company.

    Pipeline:
    1. Normalize company ID and ingest data
    2. Load investor profile and detect context type
    3. Select style examples matching investor + context type
    4. Build prompts via build_generation_prompt()
    5. Call LLM and parse result

    Args:
        company_id: Company URL or domain
        output_format: "email" or "linkedin" (default: "email")
        contact_name: Optional target contact name (auto-selects if None)
        investor_key: Investor profile key (default: "ashley")
        model: LLM model to use
        skip_ingest: If True, use cached DB data only
        context_type_override: Optional context type string to force

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
        "investor_key": investor_key,
        "output_format": output_format,
        "context_type": None,
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

    # Stealth mode bypasses all company data — redirect immediately
    if stealth_mode:
        return _generate_stealth_outreach(
            founder_linkedin_url=founder_linkedin_url,
            founder_background_notes=founder_background_notes,
            contact_name=contact_name,
            investor_key=investor_key,
            output_format=output_format,
            model=model,
            outreach_goal=outreach_goal,
            event_details=event_details,
            prior_relationship_details=prior_relationship_details,
        )

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

        # Step 4: Load investor profile
        investor_profile = get_investor_context(investor_key)

        # Step 5: Detect context type
        if context_type_override:
            try:
                ctx_type = ContextType(context_type_override)
            except ValueError:
                logger.warning(
                    f"Unknown context_type '{context_type_override}', "
                    f"falling back to auto-detection"
                )
                ctx_type = None
        else:
            ctx_type = None

        if ctx_type is None:
            available_signals = _extract_available_signals(bundle, contact)

            # Supplement with investor-provided context
            if has_event_context:
                available_signals.extend(["event_context", "event_attendance"])
            if has_prior_relationship:
                available_signals.extend(["prior_relationship", "company_announcement"])
            available_signals = list(set(available_signals))

            ctx_type = detect_context_type(
                available_signals=available_signals,
                has_prior_relationship=has_prior_relationship,
                has_event_context=has_event_context,
            )

        result["context_type"] = ctx_type.value
        ctx_config = CONTEXT_TYPE_CONFIGS[ctx_type]

        # Step 6: Load style examples (static file + DB-promoted)
        static_examples = load_samples(
            investor_key=investor_key,
            context_type=ctx_type.value,
        )

        try:
            from services.feedback import load_promoted_samples
            promoted = load_promoted_samples(investor_key)
            # Context-matching promoted examples take priority
            promoted_matching = [s for s in promoted if s.context_type == ctx_type.value]
            promoted_other = [s for s in promoted if s.context_type != ctx_type.value]
            # Merge: matching promoted → other promoted → static (capped at 3)
            combined = promoted_matching + promoted_other + static_examples
            style_examples = combined[:3]
        except Exception as _promo_err:
            logger.warning(f"Could not load promoted samples, using static only: {_promo_err}")
            style_examples = static_examples

        # Step 7: Format and sanitize data
        safe_company_name = sanitize_company_name(bundle.company_core.company_name)

        company_context = format_company_context(bundle)
        safe_company_context = sanitize_for_prompt(company_context, escape_markdown=False)

        contact_context = format_contact_context(contact) if contact else "No contact information available."
        safe_contact_context = sanitize_for_prompt(contact_context, escape_markdown=False)

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

        # Step 8: Build prompts via the prompts module
        messages = build_generation_prompt(
            investor_profile=investor_profile,
            founder_context=safe_contact_context,
            company_context=safe_company_context,
            style_examples=style_examples,
            context_type_pattern=ctx_config.email_pattern,
            output_format=output_format,
            outreach_goal=outreach_goal,
            event_details=event_details,
            prior_relationship_details=prior_relationship_details,
        )

        system_prompt_content = messages[0].content
        user_prompt = messages[1].content

        # Step 9: Get model config
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
            prompt=None,
            model_config=model_config,
            system_prompt=system_prompt_content,
            user_prompt=user_prompt,
            company_id=normalized_id,
            model=actual_model,
            temperature=temperature,
        )

        # Step 10: Call LLM (select provider based on model name)
        tracker = get_tracker()
        is_anthropic = actual_model.startswith("claude")
        if is_anthropic:
            llm = ChatAnthropic(model=actual_model, temperature=temperature)
        else:
            llm = ChatOpenAI(model=actual_model, temperature=temperature)

        start_time = time.time()
        response = llm.invoke(messages)
        latency_ms = int((time.time() - start_time) * 1000)

        raw_content = response.content
        tokens_in = response.usage_metadata.get("input_tokens", 0) if hasattr(response, "usage_metadata") and response.usage_metadata else 0
        tokens_out = response.usage_metadata.get("output_tokens", 0) if hasattr(response, "usage_metadata") and response.usage_metadata else 0

        call_metadata.tokens_in = tokens_in
        call_metadata.tokens_out = tokens_out
        call_metadata.latency_ms = latency_ms

        # Step 11: Parse output
        message_text = raw_content.strip()
        subject = None

        if output_format == "email" and message_text.lower().startswith("subject:"):
            lines = message_text.split("\n", 1)
            subject = lines[0].replace("Subject:", "").replace("subject:", "").strip()
            message_text = lines[1].strip() if len(lines) > 1 else message_text

        result["message"] = message_text
        result["subject"] = subject
        result["success"] = True

        # Step 12: Log everything
        tracker.log_api_call(
            service="anthropic" if is_anthropic else "openai",
            endpoint=f"/messages ({actual_model})" if is_anthropic else f"/chat/completions ({actual_model})",
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
                "investor_key": investor_key,
                "context_type": ctx_type.value,
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
                "investor_key": investor_key,
                "context_type": ctx_type.value,
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
                "investor_key": investor_key,
                "context_type": ctx_type.value,
                "output_format": output_format,
                "model": actual_model,
                "tokens_total": tokens_in + tokens_out,
                "latency_ms": latency_ms,
            },
        )

        # Save to persistent history
        try:
            outreach_history = get_outreach_history()
            message_content = result.get("email") or result.get("linkedin") or ""
            outreach_history.save_outreach(
                company_id=normalized_id,
                company_name=bundle.company_core.company_name,
                contact_name=result["contact_name"],
                investor_key=investor_key,
                context_type=ctx_type.value,
                output_format=output_format,
                message_preview=message_content[:500] if message_content else None,
                full_message=message_content,
                model=actual_model,
                tokens_total=tokens_in + tokens_out,
                latency_ms=latency_ms,
                success=True,
            )

            # Also save to persistent audit log
            audit_log = get_audit_log()
            audit_log.log(
                agent="outreach",
                event_type="generation",
                action="create",
                resource_type="outreach_message",
                resource_id=normalized_id,
                details={
                    "company_name": bundle.company_core.company_name,
                    "contact_name": result["contact_name"],
                    "investor_key": investor_key,
                    "context_type": ctx_type.value,
                    "output_format": output_format,
                    "tokens_total": tokens_in + tokens_out,
                },
            )
        except Exception as hist_err:
            logger.warning(f"Failed to save outreach history: {hist_err}")

        logger.info(
            f"Generated {output_format} outreach for {safe_company_name} "
            f"(contact: {result['contact_name']}, investor: {investor_key}, "
            f"context: {ctx_type.value})"
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

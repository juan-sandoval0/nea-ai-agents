"""
Briefing Generator for Meeting Briefing Agent
==============================================

Generates meeting briefings from structured database tables.
Uses ONLY data from the database - no external knowledge.

Sections:
1. TL;DR
2. Why This Meeting Matters
3. Company Snapshot
4. Founder Information
5. Key Signals
6. In the News
7. Competitive Landscape
8. For This Meeting

Usage:
    from agents.meeting_briefing.briefing_generator import generate_briefing

    # Ensure data is ingested first
    from agents.meeting_briefing.tools import ingest_company
    ingest_company("stripe.com")

    # Generate briefing
    briefing = generate_briefing("stripe.com")
    print(briefing["markdown"])
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Optional

import time
from langchain_anthropic import ChatAnthropic
from langchain_core.messages import SystemMessage, HumanMessage

from core.database import CompanyBundle, CompanyCore, Founder, KeySignal, NewsArticle, CompetitorSnapshot
from core.tracking import get_tracker
from core.llm_validation import (
    validate_briefing_content,
    LLMResponseError,
    EmptyResponseError,
    TruncatedResponseError,
    MissingSectionsError,
)
from core.prompt_registry import (
    get_prompt,
    get_model_config,
    LLMCallMetadata,
)
from core.security import (
    sanitize_company_name,
    sanitize_for_prompt,
    detect_prompt_injection,
    log_security_event,
)
from core.observability import (
    get_logger,
    LogContext,
    log_llm_interaction,
    log_audit_event,
    trace_function,
    set_request_context,
    clear_request_context,
)
from tools.company_tools import get_company_bundle, normalize_company_id

logger = get_logger(__name__)

# =============================================================================
# CONFIGURATION
# =============================================================================

DEFAULT_LLM_MODEL = "claude-sonnet-4-6"

# Mandatory system prompt - enforces data-only generation
SYSTEM_PROMPT = """You are an AI assistant generating meeting briefings for venture capital investors.

CRITICAL RULES:
- You may ONLY use the data provided from the database tables below.
- Do NOT use outside knowledge.
- If data is missing, say "Not found in table" or "Source not yet implemented."
- Do NOT infer, guess, or hallucinate facts.
- Be succinct but comprehensive.
- Use the exact structure provided.

Your output MUST follow the structure exactly as specified in the user prompt."""


# =============================================================================
# DATA FORMATTING HELPERS
# =============================================================================

def format_company_snapshot_data(company: CompanyCore) -> tuple[str, str]:
    """Format company core data for LLM context.

    Returns:
        Tuple of (formatted_data, last_updated_timestamp)
    """
    lines = []

    lines.append(f"Company Name: {company.company_name}")

    if company.founding_date:
        lines.append(f"Founded: {company.founding_date}")
    else:
        lines.append("Founded: Not found in table")

    if company.hq:
        lines.append(f"HQ: {company.hq}")
    else:
        lines.append("HQ: Not found in table")

    if company.employee_count:
        lines.append(f"Employees: {company.employee_count:,}")
    else:
        lines.append("Employees: Not found in table")

    if company.products:
        lines.append(f"Products/Tags: {company.products}")
    else:
        lines.append("Products: Not found in table")

    if company.customers:
        lines.append(f"Customer Type: {company.customers}")
    else:
        lines.append("Customers: Not found in table")

    if company.total_funding:
        lines.append(f"Total Funding: ${company.total_funding:,.0f}")
    else:
        lines.append("Total Funding: Not found in table")

    if company.last_round_date and company.last_round_funding:
        lines.append(f"Last Round: ${company.last_round_funding:,.0f} on {company.last_round_date}")
    elif company.last_round_date:
        lines.append(f"Last Round Date: {company.last_round_date}")
    else:
        lines.append("Last Round: Not found in table")

    if company.investors:
        lines.append(f"Key Investors: {', '.join(company.investors[:8])}")
    else:
        lines.append("Key Investors: Not found in table")

    # Extract just the date portion from the ISO timestamp for display
    last_updated = company.observed_at[:10] if company.observed_at else "Unknown"

    return "\n".join(lines), last_updated


def format_founders_data(founders: list[Founder]) -> str:
    """Format founders data for LLM context."""
    if not founders:
        return "No founders/executives found in table."

    lines = []
    for f in founders:
        # Name and title on first line
        header = f"**{f.name}**"
        if f.role_title:
            header += f" - {f.role_title}"
        lines.append(header)

        # LinkedIn on separate line
        if f.linkedin_url:
            lines.append(f"  LinkedIn: {f.linkedin_url}")

        # Background as indented block
        if f.background:
            # Clean up the background - remove source lines for cleaner display
            bg_text = f.background.split("\n---\n")[0].strip()
            # Indent each line
            for bg_line in bg_text.split("\n"):
                if bg_line.strip():
                    lines.append(f"  {bg_line}")
        else:
            lines.append("  Background: Not yet available")

        lines.append(f"  (Source: {f.source})")
        lines.append("")  # Blank line between founders

    max_observed = max(f.observed_at for f in founders) if founders else "N/A"
    lines.append(f"Data Last Updated: {max_observed}")

    return "\n".join(lines)


def format_signals_data(signals: list[KeySignal]) -> str:
    """Format key signals data for LLM context."""
    if not signals:
        return "No signals found in table."

    lines = []

    # Check which signal types are present
    signal_types_present = {s.signal_type for s in signals}
    tavily_types = {"website_update", "website_product", "website_pricing", "website_team", "website_news"}
    has_tavily = bool(signal_types_present & tavily_types)

    for s in signals:
        # Skip stale placeholder signals if real Tavily data exists
        if s.source == "pending_tavily" and has_tavily:
            continue
        lines.append(f"- [{s.signal_type.upper()}] {s.description} (Source: {s.source})")

    # Only show pending message if no Tavily signals exist at all
    if not has_tavily and not any(s.source == "tavily" for s in signals):
        lines.append("- [WEBSITE_UPDATE] Source not yet implemented (pending Tavily)")

    max_observed = max(s.observed_at for s in signals) if signals else "N/A"
    lines.append(f"\nData Last Updated: {max_observed}")

    return "\n".join(lines)


def format_news_data(news: list[NewsArticle]) -> str:
    """Format news data for LLM context, including excerpts for takeaway generation."""
    if not news:
        return "No recent news available (source not yet implemented)."

    lines = []
    for i, n in enumerate(news, 1):
        # Article header
        line = f"**Article {i}:** {n.article_headline}"
        if n.outlet:
            line += f" ({n.outlet})"
        if n.published_date:
            line += f" | {n.published_date}"
        if n.url:
            line += f"\n  URL: {n.url}"
        lines.append(line)

        # Include excerpts for LLM to generate takeaway (truncate to ~1000 chars per article)
        if n.excerpts:
            excerpt_text = n.excerpts[:1000]
            if len(n.excerpts) > 1000:
                excerpt_text += "..."
            lines.append(f"  Excerpt: {excerpt_text}")
        lines.append("")  # Blank line between articles

    max_observed = max(n.observed_at for n in news) if news else "N/A"
    lines.append(f"Data Last Updated: {max_observed}")

    return "\n".join(lines)


def fetch_nea_portfolio_companies() -> list[dict]:
    """Fetch NEA portfolio companies from nea_portfolio table."""
    try:
        from core.clients import get_supabase
        supabase = get_supabase()
        result = (
            supabase.table("nea_portfolio")
            .select("slug, company_name, domain, sector")
            .eq("is_active", True)
            .execute()
        )
        return result.data or []
    except Exception as e:
        logger.warning(f"Failed to fetch NEA portfolio companies: {e}")
        return []


def format_nea_connections_data(founders: list, portfolio_companies: list[dict]) -> str:
    """Format NEA portfolio companies and founder backgrounds for connection analysis."""
    lines = []

    if portfolio_companies:
        lines.append("NEA PORTFOLIO COMPANIES:")
        for co in portfolio_companies:
            name = co.get("company_name", "")
            domain = co.get("domain") or ""
            sector = co.get("sector") or ""
            parts = [name]
            if domain:
                parts.append(domain)
            if sector:
                parts.append(sector)
            lines.append(f"- {' | '.join(parts)}")
    else:
        lines.append("NEA PORTFOLIO COMPANIES: None found in table.")

    lines.append("")

    if founders:
        lines.append("FOUNDER BACKGROUNDS (for cross-reference):")
        for f in founders:
            lines.append(f"\n{f.name} ({f.role_title or 'Founder'}):")
            if f.background:
                bg_text = f.background.split("\n---\n")[0].strip()
                lines.append(bg_text)
            else:
                lines.append("Background not yet available.")
    else:
        lines.append("FOUNDER BACKGROUNDS: No founders found.")

    return "\n".join(lines)


def format_competitors_data(competitors: list[CompetitorSnapshot]) -> str:
    """Format competitor data for LLM context."""
    if not competitors:
        return "No competitor data available."

    startups = [c for c in competitors if c.competitor_type == "startup"]
    incumbents = [c for c in competitors if c.competitor_type == "incumbent"]

    def _fmt_competitor(c: CompetitorSnapshot) -> list[str]:
        parts = []
        if c.competitor_domain:
            parts.append(f"Domain: {c.competitor_domain}")
        if c.description:
            parts.append(f"Description: {c.description}")
        funding_parts = []
        if c.funding_total:
            funding_parts.append(f"Total Raised: ${c.funding_total:,.0f}")
        if c.funding_stage:
            funding_parts.append(f"Stage: {c.funding_stage}")
        if c.funding_last_amount and c.funding_last_date:
            funding_parts.append(f"Last Round: ${c.funding_last_amount:,.0f} ({c.funding_last_date})")
        elif c.funding_last_amount:
            funding_parts.append(f"Last Round: ${c.funding_last_amount:,.0f}")
        if funding_parts:
            parts.append(" | ".join(funding_parts))
        if c.headcount:
            parts.append(f"Headcount: {c.headcount:,}")
        if c.tags:
            parts.append(f"Tags: {c.tags}")
        return parts

    lines = []
    if startups:
        lines.append("[STARTUP COMPETITORS]")
        for i, c in enumerate(startups, 1):
            lines.append(f"Startup {i}: {c.competitor_name}")
            for detail in _fmt_competitor(c):
                lines.append(f"  {detail}")
            lines.append("")

    if incumbents:
        lines.append("[INCUMBENT COMPETITORS]")
        for i, c in enumerate(incumbents, 1):
            lines.append(f"Incumbent {i}: {c.competitor_name}")
            for detail in _fmt_competitor(c):
                lines.append(f"  {detail}")
            lines.append("")

    if not startups and not incumbents:
        return "No competitor data available."

    return "\n".join(lines)


# =============================================================================
# BRIEFING GENERATION
# =============================================================================

@trace_function(operation="generate_briefing")
def generate_briefing(company_id: str, model: str = DEFAULT_LLM_MODEL) -> dict:
    """
    Generate a meeting briefing from database tables.

    This function:
    1. Calls get_company_bundle() to retrieve all table data
    2. Formats data for LLM context
    3. Generates briefing with mandatory structure
    4. Returns structured result

    Args:
        company_id: Company URL or domain
        model: LLM model to use (default: claude-sonnet-4-6)

    Returns:
        Dict with:
        - company_id: normalized company ID
        - company_name: company name
        - markdown: full briefing markdown
        - generated_at: timestamp
        - data_sources: dict of what data was available
        - success: bool
        - error: optional error message
    """
    normalized_id = normalize_company_id(company_id)

    # Set up request context for structured logging and tracing
    # This ensures all logs within this function include company_id and operation
    set_request_context(company_id=normalized_id, operation="briefing")

    result = {
        "company_id": normalized_id,
        "company_name": None,
        "markdown": None,
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

    # Get company bundle from database
    bundle = get_company_bundle(company_id)

    if not bundle.company_core:
        result["error"] = f"Company not found in database. Run ingest_company first."
        clear_request_context()
        return result

    result["company_name"] = bundle.company_core.company_name
    result["data_sources"]["company_core"] = True
    result["data_sources"]["founders"] = len(bundle.founders)
    result["data_sources"]["signals"] = len(bundle.key_signals)
    result["data_sources"]["news"] = len(bundle.news)
    result["data_sources"]["competitors"] = len(bundle.competitors)

    # Fetch NEA portfolio companies for connections analysis
    portfolio_companies = fetch_nea_portfolio_companies()
    result["data_sources"]["nea_portfolio_companies"] = len(portfolio_companies)

    # Format data for LLM
    company_data, snapshot_last_updated = format_company_snapshot_data(bundle.company_core)
    founders_data = format_founders_data(bundle.founders)
    signals_data = format_signals_data(bundle.key_signals)
    news_data = format_news_data(bundle.news)
    competitors_data = format_competitors_data(bundle.competitors)
    nea_connections_data = format_nea_connections_data(bundle.founders, portfolio_companies)

    # Sanitize all external data before inserting into prompt
    # This prevents prompt injection from malicious data in external APIs
    safe_company_name = sanitize_company_name(bundle.company_core.company_name)
    safe_company_data = sanitize_for_prompt(company_data, escape_markdown=False)
    safe_founders_data = sanitize_for_prompt(founders_data, escape_markdown=False)
    safe_signals_data = sanitize_for_prompt(signals_data, escape_markdown=False)
    safe_news_data = sanitize_for_prompt(news_data, escape_markdown=False)
    safe_competitors_data = sanitize_for_prompt(competitors_data, escape_markdown=False)
    safe_nea_connections_data = sanitize_for_prompt(nea_connections_data, escape_markdown=False)

    # Check for prompt injection in the data
    for field_name, field_data in [
        ("company_data", company_data),
        ("founders_data", founders_data),
        ("signals_data", signals_data),
        ("news_data", news_data),
        ("competitors_data", competitors_data),
        ("nea_connections_data", nea_connections_data),
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

    # Build user prompt with exact structure requirements
    user_prompt = f"""Generate a meeting briefing for **{safe_company_name}**.

## DATABASE TABLE DATA

### Table: company_core
{safe_company_data}

### Table: founders
{safe_founders_data}

### Table: key_signals
{safe_signals_data}

### Table: news
{safe_news_data}

### Table: competitors
{safe_competitors_data}

### Table: nea_connections
{safe_nea_connections_data}

---

## REQUIRED OUTPUT STRUCTURE

Generate the briefing with EXACTLY these sections:

### 1) TL;DR
- 2-3 sentences summarizing the company and the most important investment-relevant insights
- First sentence: What the company does (derived from products/description field)
- Remaining sentences: Key highlights from funding, growth metrics, signals, or recent news
- MUST be derived strictly from table data

### 2) Why This Meeting Matters
- 2-4 bullet points
- Synthesize from ALL tables: company_core, founders, key_signals, and news
- Focus on investment relevance

### 3) Company Snapshot (last updated: {snapshot_last_updated})
Display as a formatted table or list:
- Founded: [from table or "Not found in table"]
- HQ: [from table or "Not found in table"]
- Employees: [from table or "Not found in table"]
- Products: [from table or "Not found in table"]
- Customers: [from table or "Not found in table"]
- Total Funding: [from table or "Not found in table"]
- Last Round: [from table or "Not found in table"]
- Key Investors: [from table or "Not found in table"]

### 4) Founder Information
For each founder, display:
- **Name** - Title | [LinkedIn](url)
- 2 bullet points max: most relevant prior role/company, and one notable credential or fact (e.g., domain expertise, prior exit, notable school)

IMPORTANT: Do NOT copy the raw background text. Synthesize it into 2 tight bullets. Omit anything not directly relevant to the investment context.
If background is missing: "Background not yet available"
If no founders: "No founder data available"

### 5) Key Signals
- One bullet per signal from the key_signals table
- Signal types include: web_traffic, hiring, funding, website_product, website_pricing, website_team, website_news, website_update
- Summarize website signals concisely (don't just repeat page titles)
- Include signal source and last updated timestamp

### 6) In the News
For each news article, display in this format:
- **[Article Headline]** | [Outlet] | [Published Date]
  - [URL]
  - Takeaway: [2-3 sentence summary of the key information and why it matters for the investment thesis]

IMPORTANT: Use the article excerpts provided in the data to generate meaningful takeaways. Do NOT display the raw excerpts - synthesize them into a concise takeaway.
If no news: "No recent news available (source not yet implemented)"

### 7) Competitive Landscape
Using data from the competitors table:

**Startup Competitors** (top 1-3):
- **[Name]** | [Stage] | Raised: $[total] | [One clause: how they compete]

**Incumbent Competitors** (top 1-3):
- **[Name]** | [One clause: how they compete]

Keep each entry to a single line. No multi-sentence descriptions.
If no competitor data: "Competitive landscape data not available"

### 8) For This Meeting
- 2-3 suggested agenda items or questions
- Key risks to probe
- Recommended next steps
- ALL must be grounded in table data

### 9) NEA Connections
Using ONLY the nea_connections table data above, identify any connections between this company/founders and the NEA ecosystem.

**Prior Portco Employment:**
Cross-reference each founder's background against the NEA PORTFOLIO COMPANIES list. For each match found:
- **[Founder Name]** → Previously at **[Portfolio Company Name]** ([role/title if visible in background])

**Shared Schools:**
If founder backgrounds mention universities/schools, note any that appear for multiple founders (useful for warm intros via NEA network).

**Other NEA Ecosystem Signals:**
Any other observable connections to the NEA portfolio or network visible in the data.

If no connections are found in the data: "No direct NEA ecosystem connections identified from available founder background data."

IMPORTANT: Only cite connections that are explicitly stated in the founder background text. Do not infer or guess.

---

Remember: Use ONLY the data provided above. If something is not in the tables, say so clearly."""

    # Generate briefing with LLM
    tracker = get_tracker()

    # Get versioned prompt and model config for reproducibility
    try:
        system_prompt_obj = get_prompt("briefing_system")
        system_prompt_content = system_prompt_obj.content
    except KeyError:
        # Fallback to inline prompt if registry not available
        system_prompt_obj = None
        system_prompt_content = SYSTEM_PROMPT

    try:
        model_config = get_model_config("briefing")
        actual_model = model_config.model if model == DEFAULT_LLM_MODEL else model
        temperature = model_config.temperature
    except KeyError:
        model_config = None
        actual_model = model
        temperature = 0

    # Create metadata for this LLM call (for reproducibility tracking)
    call_metadata = LLMCallMetadata.create(
        operation="briefing",
        prompt=system_prompt_obj,
        model_config=model_config,
        system_prompt=system_prompt_content,
        user_prompt=user_prompt,
        company_id=normalized_id,
        model=actual_model,
        temperature=temperature,
    )

    try:
        max_tokens = model_config.max_tokens if model_config and model_config.max_tokens else 4096
        llm = ChatAnthropic(model=actual_model, temperature=temperature, max_tokens=max_tokens)
        messages = [
            SystemMessage(content=system_prompt_content),
            HumanMessage(content=user_prompt),
        ]

        start_time = time.time()
        response = llm.invoke(messages)
        latency_ms = int((time.time() - start_time) * 1000)

        raw_content = response.content

        # Track LLM API call
        tokens_in = response.usage_metadata.get("input_tokens", 0) if hasattr(response, "usage_metadata") else 0
        tokens_out = response.usage_metadata.get("output_tokens", 0) if hasattr(response, "usage_metadata") else 0

        # Update metadata with actual metrics
        call_metadata.tokens_in = tokens_in
        call_metadata.tokens_out = tokens_out
        call_metadata.latency_ms = latency_ms

        # Log to both legacy api_calls table and new llm_calls table
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
            }
        )

        # Log detailed LLM call for reproducibility
        tracker.log_llm_call(
            call_id=call_metadata.call_id,
            model=actual_model,
            operation="briefing",
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

        # Validate LLM output before using it
        # This catches empty, truncated, or malformed responses
        try:
            briefing_content = validate_briefing_content(
                raw_content,
                company_name=bundle.company_core.company_name,
                strict=True,  # Raise on missing sections
            )
        except MissingSectionsError as e:
            # Log but continue with partial content - better than nothing
            logger.warning(
                f"Briefing for {normalized_id} missing sections: {e.missing_sections}. "
                "Proceeding with partial content."
            )
            briefing_content = raw_content.strip() if raw_content else ""
            result["data_sources"]["validation_warnings"] = [
                f"Missing sections: {e.missing_sections}"
            ]
        except (EmptyResponseError, TruncatedResponseError) as e:
            # These are fatal - can't use the response
            raise LLMResponseError(
                f"LLM returned unusable response: {e}",
                response_content=raw_content,
                error_type=e.error_type,
            )

        # Assemble final markdown
        final_markdown = f"""# {bundle.company_core.company_name} | Meeting Brief
**Website:** {normalized_id}

{briefing_content}
"""

        result["markdown"] = final_markdown
        result["success"] = True

        # Track briefing generation
        tracker.log_usage(
            company_id=normalized_id,
            action="briefing",
            metadata={
                "model": model,
                "tokens_in": tokens_in,
                "tokens_out": tokens_out,
            }
        )

        logger.info(f"Generated briefing for {bundle.company_core.company_name}")

        # Log comprehensive LLM interaction for debugging and auditing
        log_llm_interaction(
            operation="briefing",
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
            validation_passed=True,
            validation_warnings=result.get("data_sources", {}).get("validation_warnings"),
        )

        # Log audit event for briefing generation
        log_audit_event(
            event_type="briefing",
            action="create",
            resource_type="briefing",
            resource_id=normalized_id,
            details={
                "company_name": bundle.company_core.company_name,
                "model": actual_model,
                "tokens_total": tokens_in + tokens_out,
                "latency_ms": latency_ms,
            },
        )

    except LLMResponseError as e:
        # Specific LLM validation error - log the failed call
        result["error"] = f"LLM output validation failed ({e.error_type}): {str(e)}"
        logger.error(f"Briefing validation failed for {company_id}: {e}")

        # Log the failed call for debugging/analysis
        tracker.log_llm_call(
            call_id=call_metadata.call_id,
            model=call_metadata.model,
            operation="briefing",
            tokens_in=call_metadata.tokens_in,
            tokens_out=call_metadata.tokens_out,
            latency_ms=call_metadata.latency_ms,
            prompt_id=call_metadata.prompt_id,
            prompt_version=call_metadata.prompt_version,
            prompt_hash=call_metadata.prompt_hash,
            system_prompt_hash=call_metadata.system_prompt_hash,
            user_prompt_hash=call_metadata.user_prompt_hash,
            company_id=normalized_id,
            success=False,
            error_message=str(e),
        )

        # Log failed LLM interaction for observability
        log_llm_interaction(
            operation="briefing",
            model=call_metadata.model,
            system_prompt=system_prompt_content,
            user_prompt=user_prompt,
            response=getattr(e, 'response_content', None),
            tokens_in=call_metadata.tokens_in,
            tokens_out=call_metadata.tokens_out,
            latency_ms=call_metadata.latency_ms,
            success=False,
            error_type=e.error_type,
            error_message=str(e),
            temperature=temperature,
            company_id=normalized_id,
            validation_passed=False,
        )
    except Exception as e:
        result["error"] = f"LLM generation failed: {str(e)}"
        logger.error(f"Briefing generation failed for {company_id}: {e}")

        # Log the failed call
        tracker.log_llm_call(
            call_id=call_metadata.call_id,
            model=call_metadata.model,
            operation="briefing",
            prompt_id=call_metadata.prompt_id,
            prompt_version=call_metadata.prompt_version,
            company_id=normalized_id,
            success=False,
            error_message=str(e),
        )

        # Log failed LLM interaction for observability
        log_llm_interaction(
            operation="briefing",
            model=call_metadata.model,
            success=False,
            error_type=type(e).__name__,
            error_message=str(e),
            company_id=normalized_id,
        )

    # Clear request context before returning
    clear_request_context()
    return result


# =============================================================================
# CLI ENTRYPOINT
# =============================================================================

def main():
    """CLI entrypoint for generate_briefing."""
    import argparse

    parser = argparse.ArgumentParser(description="Generate meeting briefing from database")
    parser.add_argument(
        "--company_url",
        required=True,
        help="Company URL or domain (must be ingested first)"
    )
    parser.add_argument(
        "--model",
        default=DEFAULT_LLM_MODEL,
        help=f"LLM model to use (default: {DEFAULT_LLM_MODEL})"
    )
    parser.add_argument(
        "--output", "-o",
        help="Output file path (prints to stdout if not specified)"
    )

    args = parser.parse_args()

    from dotenv import load_dotenv
    load_dotenv()

    logging.basicConfig(level=logging.INFO)

    print(f"Generating briefing for: {args.company_url}")
    print("-" * 50)

    result = generate_briefing(args.company_url, model=args.model)

    if result["success"]:
        if args.output:
            with open(args.output, "w") as f:
                f.write(result["markdown"])
            print(f"Briefing saved to: {args.output}")
        else:
            print(result["markdown"])

        print("-" * 50)
        print(f"Company: {result['company_name']}")
        print(f"Data Sources: {result['data_sources']}")
    else:
        print(f"ERROR: {result['error']}")
        print("\nMake sure to run ingest_company first:")
        print(f"  python -m agents.meeting_briefing.tools --company_url {args.company_url}")


if __name__ == "__main__":
    main()

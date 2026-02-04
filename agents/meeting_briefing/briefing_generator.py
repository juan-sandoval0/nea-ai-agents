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
7. For This Meeting

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
from langchain_openai import ChatOpenAI
from langchain_core.messages import SystemMessage, HumanMessage

from core.database import CompanyBundle, CompanyCore, Founder, KeySignal, NewsArticle
from core.tracking import get_tracker
from tools.company_tools import get_company_bundle, normalize_company_id

logger = logging.getLogger(__name__)

# =============================================================================
# CONFIGURATION
# =============================================================================

DEFAULT_LLM_MODEL = "gpt-4o-mini"

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

def format_company_snapshot_data(company: CompanyCore) -> str:
    """Format company core data for LLM context."""
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

    lines.append(f"Data Last Updated: {company.observed_at}")

    return "\n".join(lines)


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
    """Format news data for LLM context."""
    if not news:
        return "No recent news available (source not yet implemented)."

    lines = []
    for n in news:
        line = f"- {n.article_headline}"
        if n.outlet:
            line += f" ({n.outlet})"
        if n.published_date:
            line += f" | {n.published_date}"
        if n.url:
            line += f" | {n.url}"
        lines.append(line)

    max_observed = max(n.observed_at for n in news) if news else "N/A"
    lines.append(f"\nData Last Updated: {max_observed}")

    return "\n".join(lines)


# =============================================================================
# BRIEFING GENERATION
# =============================================================================

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
        model: LLM model to use (default: gpt-4o-mini)

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
        return result

    result["company_name"] = bundle.company_core.company_name
    result["data_sources"]["company_core"] = True
    result["data_sources"]["founders"] = len(bundle.founders)
    result["data_sources"]["signals"] = len(bundle.key_signals)
    result["data_sources"]["news"] = len(bundle.news)

    # Format data for LLM
    company_data = format_company_snapshot_data(bundle.company_core)
    founders_data = format_founders_data(bundle.founders)
    signals_data = format_signals_data(bundle.key_signals)
    news_data = format_news_data(bundle.news)

    # Build user prompt with exact structure requirements
    user_prompt = f"""Generate a meeting briefing for **{bundle.company_core.company_name}**.

## DATABASE TABLE DATA

### Table: company_core
{company_data}

### Table: founders
{founders_data}

### Table: key_signals
{signals_data}

### Table: news
{news_data}

---

## REQUIRED OUTPUT STRUCTURE

Generate the briefing with EXACTLY these sections:

### 1) TL;DR
- Format: "[Company] is a [what they do in 5-7 words]. [Most critical investment-relevant insight]."
- Example: "Stripe is a payments infrastructure platform for the internet. Series I at $95B valuation with 35% YoY revenue growth."
- The "what they do" phrase should be derived from the products/description field
- The insight should highlight the most notable signal (funding, growth, traction, or risk)
- MUST be derived strictly from table data

### 2) Why This Meeting Matters
- 2-4 bullet points
- Synthesize from ALL tables: company_core, founders, key_signals, and news
- Focus on investment relevance

### 3) Company Snapshot
Display as a formatted table or list:
- Founded: [from table or "Not found in table"]
- HQ: [from table or "Not found in table"]
- Employees: [from table or "Not found in table"]
- Products: [from table or "Not found in table"]
- Customers: [from table or "Not found in table"]
- Total Funding: [from table or "Not found in table"]
- Last Round: [from table or "Not found in table"]
- Last Updated: [observed_at timestamp]

### 4) Founder Information
For each founder, display:
- **Name** - Title | [LinkedIn](url)
- Background summary (the 2-3 sentence summary from the data)

IMPORTANT: You MUST include the background text for each founder. Do not omit it.
If background is missing: "Background not yet available"
If no founders: "No founder data available"

### 5) Key Signals
- One bullet per signal from the key_signals table
- Signal types include: web_traffic, hiring, funding, website_product, website_pricing, website_team, website_news, website_update
- Summarize website signals concisely (don't just repeat page titles)
- Include signal source and last updated timestamp

### 6) In the News
- One bullet per news article if available
- If no news: "No recent news available (source not yet implemented)"
- Include last updated timestamp

### 7) For This Meeting
- 2-3 suggested agenda items or questions
- Key risks to probe
- Recommended next steps
- ALL must be grounded in table data

---

Remember: Use ONLY the data provided above. If something is not in the tables, say so clearly."""

    # Generate briefing with LLM
    tracker = get_tracker()
    try:
        llm = ChatOpenAI(model=model, temperature=0)
        messages = [
            SystemMessage(content=SYSTEM_PROMPT),
            HumanMessage(content=user_prompt),
        ]

        start_time = time.time()
        response = llm.invoke(messages)
        latency_ms = int((time.time() - start_time) * 1000)

        briefing_content = response.content

        # Track LLM API call
        tokens_in = response.usage_metadata.get("input_tokens", 0) if hasattr(response, "usage_metadata") else 0
        tokens_out = response.usage_metadata.get("output_tokens", 0) if hasattr(response, "usage_metadata") else 0

        tracker.log_api_call(
            service="openai",
            endpoint=f"/chat/completions ({model})",
            method="POST",
            status_code=200,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            latency_ms=latency_ms,
            metadata={"company_id": normalized_id}
        )

        # Assemble final markdown
        final_markdown = f"""# {bundle.company_core.company_name} | Meeting Brief
*Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}*

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

    except Exception as e:
        result["error"] = f"LLM generation failed: {str(e)}"
        logger.error(f"Briefing generation failed for {company_id}: {e}")

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

"""
Judge prompt builder for the NEA Company TLDR (Meeting Briefing) Agent.

Input data:
    company_bundle  - dict with keys:
                        company_core   — dict of core company fields from Harmonic
                        founders       — list of dicts (name, title, linkedin_url, background)
                        key_signals    — list of dicts (signal_type, description, source, timestamp)
                        news_articles  — list of dicts (headline, outlet, url, date, excerpt)
    agent_output    - dict with keys:
                        tldr, why_it_matters, company_snapshot, founders (as rendered),
                        signals (as rendered), news (as rendered), meeting_prep, markdown
                      OR just: markdown — the full rendered briefing string
    context_tags    - dict with keys:
                        data_richness, signal_coverage, news_availability,
                        founder_data, model, entity_resolution

Returns:
    (system_prompt: str, user_prompt: str) — ready for the Anthropic Messages API.
"""

from typing import Any

# ---------------------------------------------------------------------------
# SYSTEM PROMPT
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = """You are an expert evaluator for NEA, a top-tier venture capital firm. \
Your job is to score 1-page meeting briefings produced by an AI agent that synthesizes \
raw company data for investor review before founder meetings.

You will be given:
1. The four raw input data tables the agent had access to (company_core, founders,
   key_signals, news_articles)
2. The briefing the agent produced
3. The evaluation rubric with full scoring definitions

Your evaluation must be:
- Data-grounded. Every claim in the briefing must be traceable to the input tables.
  If a claim is not in the input data, it is either an inference (acceptable at score 4)
  or a hallucination (automatic hard failure).
- Hard-failures-first. Scan for HF1–HF5 before scoring any dimension.
- Chain-of-thought first. Reason through each dimension before assigning scores.
- Separation of concerns. Do not penalize the agent for data the upstream pipeline
  didn't provide. Only penalize for failing to use data that WAS provided, or for
  silently omitting fields that should be marked "Not found in table."
- Structured. Output valid JSON matching the schema at the end of the prompt.

Pass threshold: composite ≥ 70 / 100."""


# ---------------------------------------------------------------------------
# RUBRIC TEXT
# ---------------------------------------------------------------------------

RUBRIC_TEXT = """
═══════════════════════════════════════════════════════════
COMPANY TLDR AGENT SCORING RUBRIC v1.0
═══════════════════════════════════════════════════════════

GLOBAL SCALE
  5 = Excellent   — Meeting ready. Investor walks in confidently. No factual errors,
                    all sections present, synthesis is concise and investment-relevant.
  4 = Good        — Usable with minor polish. 1–2 small issues. Investors would skim-edit.
  3 = Acceptable  — Covers basics but lacks sharpness. Synthesis is shallow, some sections
                    read as data dumps. Investor needs 10+ min of additional research.
  2 = Below Std   — Missing sections, factual inaccuracies, raw excerpt dumping, or generic
                    content. Not usable without major rework.
  1 = Poor        — Hallucinated facts, wrong company data, empty/truncated output,
                    or structural collapse. Requires complete regeneration.

REQUIRED SECTIONS (7):
  1. TL;DR
  2. Why This Meeting Matters
  3. Company Snapshot
  4. Founders
  5. Key Signals
  6. In the News
  7. Meeting Prep

MISSING FIELD POLICY: If an input field was not available in the data, the agent must
explicitly write "Not found in table." Silently omitting a field is penalized.

──────────────────────────────────────────
D1: FACTUAL ACCURACY & DATA GROUNDING  (weight 20%)
──────────────────────────────────────────
Every claim in the output must be traceable to the input data tables.

Scoring method: holistic assessment across the entire briefing.
  5: Every factual claim directly traceable to input data. Missing fields acknowledged
     with "Not found in table." Zero hallucinations, zero outside knowledge.
  4: All major facts correct. One borderline inference that is reasonable but not directly
     stated in data (e.g., calling a 15-person company "early-stage").
  3: Mostly accurate. One minor factual error (e.g., wrong employee count by small margin)
     or one instance of unstated inference presented as fact.
  2: Multiple minor errors, or one significant error (wrong funding amount, wrong founding
     date). Or a missing field silently omitted rather than flagged.
  1: Hallucinated fact, outside knowledge used, or wrong company data. Hard failure.

HARD FAILURE TRIGGERS:
  - Any hallucinated fact (claim not in input data) = automatic 1 → composite = 0
  - Any use of outside knowledge (training data about the company) = automatic 1 → composite = 0
  - Wrong company data (entity resolution failure) = automatic 1 → composite = 0

Inference vs. Hallucination tiebreaker:
  If the claim could be directly quoted from an input field → grounded (score 5)
  If it requires a logical leap beyond what the data states → inference (score 4 if reasonable)
  If it contradicts the data or has no basis in the data → hallucination (score 1, hard failure)

──────────────────────────────────────────
D2: TL;DR QUALITY  (weight 12%)
──────────────────────────────────────────
  5: 2–3 sentences. Sentence 1 clearly states what the company does (from products field).
     Sentences 2–3 highlight the most investment-relevant signals.
     Example: "Acme builds real-time fraud detection APIs for fintech platforms. The company
     raised a $12M Series A in March 2024 led by Index Ventures, and web traffic has grown 32% over 30 days."
  4: Correct and relevant, but one sentence is slightly generic or redundant.
  3: Covers what the company does, but investment-relevant highlights are shallow or missing.
     May be 1 sentence too long or too short.
  2: Vague or partially inaccurate. Product description is unclear. Investment highlights
     are generic ("exciting space").
  1: Missing, empty, contains hallucinated facts, or exceeds 5 sentences.

──────────────────────────────────────────
D3: WHY THIS MEETING MATTERS  (weight 12%)
──────────────────────────────────────────
2–4 bullet points synthesizing investment relevance.
Must draw from ALL FOUR input tables (company_core, founders, key_signals, news).
  5: 2–4 bullets. Each is investment-specific and data-grounded. Draws from all 4 tables.
     Each bullet gives a distinct reason to take the meeting.
  4: Bullets are data-grounded and relevant, but draw from only 3 of 4 tables, or one bullet
     is slightly generic.
  3: Bullets present but mostly restate data without synthesizing investment relevance.
     Or draw from only 2 tables.
  2: Fewer than 2 bullets, or bullets contain generic reasoning rather than company-specific.
  1: Section missing, or bullets contain hallucinated reasoning or are completely generic.

──────────────────────────────────────────
D4: COMPANY SNAPSHOT COMPLETENESS  (weight 8%)
──────────────────────────────────────────
Required fields: Founded, HQ, Employees, Products, Customers, Total Funding, Last Round.
Missing fields must display "Not found in table." Must include "last updated" timestamp.
  5: All 7 required fields present. Missing fields explicitly marked "Not found in table."
     Last updated timestamp present and correct. Values match input data exactly.
  4: All fields present and correct. Minor formatting inconsistency (date format varies)
     or "last updated" uses a slightly different label.
  3: 6 of 7 fields present. Missing field silently omitted instead of marked "Not found in table."
     Or one field has a minor transcription error.
  2: Multiple fields missing or silently omitted. Or a field contains an incorrect value.
  1: Section missing, or contains hallucinated field values.

──────────────────────────────────────────
D5: FOUNDER INFORMATION QUALITY  (weight 8%)
──────────────────────────────────────────
Format: Name – Title | LinkedIn link + 2–3 sentence background.
Missing backgrounds must say "Background not yet available."
If no founders available: must say "No founder data available."
  5: All founders listed with correct names, titles, LinkedIn URLs. Each has a 2–3 sentence
     background from Swarm data. Missing backgrounds explicitly flagged. Backgrounds are
     informative summaries (not raw data dumps).
  4: All founders listed correctly. Backgrounds present but one is slightly thin (1 sentence)
     or lacks specificity.
  3: Founders listed but one background is omitted (no "Background not yet available" marker),
     or a title is slightly wrong.
  2: Significant omissions: a founder in the data is entirely missing, or backgrounds contain errors.
  1: Section missing, says "No founder data available" when data exists, or contains fabricated
     founder backgrounds.

──────────────────────────────────────────
D6: KEY SIGNALS QUALITY  (weight 10%)
──────────────────────────────────────────
One bullet per signal from key_signals table. Website signals should be summarized concisely
(not raw page titles). Each signal must include source and timestamp.
If no signals: must say "Source not yet implemented."
  5: All signals from the table represented. Each concisely described, includes source and
     timestamp. Website signals summarized. Investment relevance is clear.
  4: All signals present with sources. One signal's description is slightly vague.
  3: Most signals present. One signal missing source/timestamp. Or a website signal repeats
     a raw page title instead of summarizing.
  2: Fewer than half of available signals represented. Or descriptions so vague they provide
     no actionable information.
  1: Section missing, says "Source not yet implemented" when signals exist, or contains
     fabricated signals.

──────────────────────────────────────────
D7: NEWS SYNTHESIS QUALITY  (weight 10%)
──────────────────────────────────────────
One entry per article. Format: Headline | Outlet | Date, URL, then 2–3 sentence synthesized
takeaway. Takeaway must be synthesized from excerpts — not copied verbatim and not made up.
If no news: must say "No recent news available (source not yet implemented)."
  5: All articles represented. Correct metadata (headline, outlet, date, URL). Takeaways are
     synthesized: distill the excerpt into investment-relevant insights in the agent's own words.
  4: All articles present with correct metadata. Takeaways accurate but one slightly shallow.
  3: Most articles present. One takeaway is a near-verbatim copy of the excerpt (excerpt dumping).
     Or an article about a similarly-named company included without flagging ambiguity.
  2: Multiple takeaways are raw excerpt dumps. Or articles about wrong company included.
  1: Section missing, contains fabricated news, or says "No news" when articles were provided.

──────────────────────────────────────────
D8: MEETING PREP ACTIONABILITY  (weight 10%)
──────────────────────────────────────────
2–3 suggested agenda items/questions + 1 recommended next step.
Every item must be grounded in the input data — not generic VC advice.
  5: 2–3 questions specific to this company's data (referencing specific signals, founder
     backgrounds, or news). 1 concrete next step.
  4: Questions are data-grounded and company-specific, but one is slightly generic or
     the next step is vague.
  3: Questions are reasonable but only loosely connected to specific data points. Could
     apply to many similar companies.
  2: Questions are generic VC boilerplate with no company-specific grounding.
     (e.g., "What's your TAM?", "How do you think about competition?")
  1: Section missing, or contains questions based on hallucinated data, or entirely generic.

──────────────────────────────────────────
D9: STRUCTURAL COMPLIANCE  (weight 5%)
──────────────────────────────────────────
Does the output follow the required 7-section structure?
  5: All 7 sections present, in correct order, with correct headings. Markdown formatting
     is clean. Section lengths within expected ranges. No structural anomalies.
  4: All 7 sections present and in order. Minor formatting inconsistency.
  3: All 7 sections present but one is misordered or has a non-standard heading name.
     Or one section violates its length constraint (TL;DR exceeds 5 sentences).
  2: One section is missing. Or two sections are misordered. Or output truncated (<500 chars).
  1: Multiple sections missing. Or empty/near-empty. Or fundamentally different structure.
     Hard failure if ≥3 sections absent.

──────────────────────────────────────────
D10: CLARITY & READABILITY  (weight 5%)
──────────────────────────────────────────
Professional writing quality for a time-constrained reader. Scannable in under 5 minutes.
  5: Crisp and professional. Concise bullets, short paragraphs. Consistent formatting.
     No grammatical errors.
  4: Well-written with one minor issue (awkward sentence, unclear abbreviation, formatting inconsistency).
  3: Acceptable but not polished. Some sentences overly long. Minor grammatical errors.
     Readability adequate but not optimized for speed.
  2: Difficult to scan quickly. Multiple long/unclear sentences. Inconsistent tone. Multiple errors.
  1: Incoherent writing, excessive jargon, unreadable formatting. Or document reads like raw
     LLM output (system prompt artifacts, placeholder text, "As an AI language model" patterns).

──────────────────────────────────────────
HARD FAILURE CONDITIONS (composite = 0 if any triggered)
──────────────────────────────────────────
  HF1: HALLUCINATION — Any factual claim not traceable to any field in the four input tables.
       Single instance is sufficient. Cross-reference every specific claim (names, numbers,
       dates, events) against input data.
  HF2: OUTSIDE KNOWLEDGE — Agent uses information from training data rather than input tables.
       Indicators: mentions of events, competitors, or market data not present in any input source.
  HF3: WRONG COMPANY — The briefing describes a different company than the one requested.
  HF4: EMPTY/TRUNCATED — Agent returned no content or fewer than 500 characters.
  HF5: FORBIDDEN PATTERN — Output contains LLM refusal patterns ("I cannot help with that"),
       system prompt leakage, or apology patterns indicating a generation failure.

COMPOSITE FORMULA
  composite = (D1×20 + D2×12 + D3×12 + D4×8 + D5×8 + D6×10 + D7×10 + D8×10 + D9×5 + D10×5)
  Each dimension score (1–5) × weight × 4 = contribution to 0–100 scale.
  Pass threshold: composite ≥ 70. If any HF triggered: composite = 0.
═══════════════════════════════════════════════════════════
"""


# ---------------------------------------------------------------------------
# HELPERS
# ---------------------------------------------------------------------------

def _fmt_company_core(core: dict) -> str:
    if not core:
        return "  (no company_core data returned by Harmonic)"
    return "\n".join(f"  {k}: {v}" for k, v in core.items())


def _fmt_founders_input(founders: list) -> str:
    if not founders:
        return "  (no founder data returned by Harmonic/Swarm)"
    blocks = []
    for f in founders:
        name = f.get("name", "Unknown")
        title = f.get("title", "")
        linkedin = f.get("linkedin_url", "")
        background = f.get("background", "")
        blocks.append(
            f"  Name: {name}\n"
            f"  Title: {title}\n"
            f"  LinkedIn: {linkedin or 'N/A'}\n"
            f"  Background: {background or '(not available)'}"
        )
    return "\n\n".join(blocks)


def _fmt_signals_input(signals: list) -> str:
    if not signals:
        return "  (no key signals returned)"
    lines = []
    for s in signals:
        sig_type = s.get("signal_type", "unknown")
        desc = s.get("description", "")
        source = s.get("source", "")
        timestamp = s.get("timestamp", s.get("observed_at", ""))
        lines.append(f"  [{sig_type}] {desc}  (source: {source}, {timestamp})")
    return "\n".join(lines)


def _fmt_news_input(articles: list) -> str:
    if not articles:
        return "  (no news articles returned by Parallel Search)"
    items = []
    for a in articles:
        headline = a.get("headline", a.get("title", ""))
        outlet = a.get("outlet", a.get("source", ""))
        date = a.get("published_date", a.get("date", ""))
        url = a.get("url", "")
        excerpt = a.get("excerpt", a.get("description", ""))
        items.append(
            f"  Headline: {headline}\n"
            f"  Outlet: {outlet} | Date: {date}\n"
            f"  URL: {url}\n"
            f"  Excerpt: {excerpt}"
        )
    return "\n\n".join(items)


def _fmt_context_tags(tags: dict) -> str:
    return "\n".join(f"  {k}: {v}" for k, v in tags.items())


# ---------------------------------------------------------------------------
# MAIN BUILDER
# ---------------------------------------------------------------------------

def build_judge_prompt(
    company_bundle: dict[str, Any],
    agent_output: dict[str, Any],
    context_tags: dict[str, str],
) -> tuple[str, str]:
    """
    Build the (system_prompt, user_prompt) pair for the TLDR Agent judge.

    Args:
        company_bundle: Dict with keys company_core, founders, key_signals,
                        news_articles — exactly what the agent received from
                        Harmonic, Swarm, Tavily, and Parallel Search.
        agent_output:   Dict with briefing sections. Accepts either structured
                        keys (tldr, why_it_matters, company_snapshot, founders,
                        signals, news, meeting_prep) or just 'markdown' (the
                        full rendered briefing string).
        context_tags:   Dict with data_richness, signal_coverage,
                        news_availability, founder_data, model, entity_resolution.

    Returns:
        (system_prompt, user_prompt) strings for the Messages API.
    """
    company_core = company_bundle.get("company_core") or {}
    founders = company_bundle.get("founders") or []
    key_signals = company_bundle.get("key_signals") or []
    news_articles = company_bundle.get("news_articles") or company_bundle.get("news") or []

    # Agent output — prefer structured fields if available, fall back to markdown
    markdown = agent_output.get("markdown", "")
    tldr = agent_output.get("tldr", "")
    why_matters = agent_output.get("why_it_matters", [])
    snapshot = agent_output.get("company_snapshot", {})
    founders_out = agent_output.get("founders", [])
    signals_out = agent_output.get("signals", [])
    news_out = agent_output.get("news", [])
    meeting_prep = agent_output.get("meeting_prep", "")

    # Summarize what structured fields are present
    structured_available = any([tldr, why_matters, snapshot, founders_out, signals_out, news_out, meeting_prep])

    output_block = ""
    if structured_available:
        output_block = f"""
── TL;DR ──
{tldr or "(empty)"}

── WHY THIS MEETING MATTERS ──
{chr(10).join("• " + b for b in why_matters) if why_matters else "(empty)"}

── COMPANY SNAPSHOT ──
{chr(10).join(f"  {k}: {v}" for k, v in snapshot.items()) if isinstance(snapshot, dict) else str(snapshot) or "(empty)"}

── FOUNDERS (as rendered) ──
{chr(10).join(str(f) for f in founders_out) if founders_out else "(empty)"}

── KEY SIGNALS (as rendered) ──
{chr(10).join(str(s) for s in signals_out) if signals_out else "(empty)"}

── NEWS (as rendered) ──
{chr(10).join(str(n) for n in news_out) if news_out else "(empty)"}

── MEETING PREP ──
{meeting_prep or "(empty)"}

── FULL MARKDOWN ──
{markdown or "(no markdown output)"}
""".strip()
    else:
        output_block = f"""── FULL MARKDOWN BRIEFING ──
{markdown if markdown else "(EMPTY — generation failure)"}"""

    user_prompt = f"""
{RUBRIC_TEXT}

═══════════════════════════════════════════════════════════
EVALUATION CONTEXT TAGS
═══════════════════════════════════════════════════════════
{_fmt_context_tags(context_tags)}

═══════════════════════════════════════════════════════════
INPUT DATA (what the agent had access to)
═══════════════════════════════════════════════════════════

── TABLE 1: COMPANY CORE (Harmonic) ──
  Fields available: {len(company_core)} fields
{_fmt_company_core(company_core)}

── TABLE 2: FOUNDERS (Harmonic + Swarm) ──
  Founders available: {len(founders)}
{_fmt_founders_input(founders)}

── TABLE 3: KEY SIGNALS ──
  Signals available: {len(key_signals)}
{_fmt_signals_input(key_signals)}

── TABLE 4: NEWS ARTICLES (Parallel Search) ──
  Articles available: {len(news_articles)}
{_fmt_news_input(news_articles)}

═══════════════════════════════════════════════════════════
AGENT OUTPUT (the briefing to evaluate)
═══════════════════════════════════════════════════════════

{output_block}

═══════════════════════════════════════════════════════════
EVALUATION INSTRUCTIONS
═══════════════════════════════════════════════════════════

Follow these steps exactly:

STEP 1 — HARD FAILURE SCAN (HF1–HF5)
Before scoring anything, check each condition:
  HF1: Does the briefing contain ANY factual claim not traceable to the four input
       tables above? (Check every number, name, date, event.)
  HF2: Does the briefing use information that appears to come from training data
       rather than the input tables? (Events not in news_articles, competitors not
       in company_core, market data not in key_signals.)
  HF3: Does the briefing appear to be about a different company entirely?
  HF4: Is the briefing empty (< 500 characters) or clearly truncated mid-sentence?
  HF5: Does the output contain LLM artifacts (refusal language, system prompt text,
       placeholder text like [INSERT COMPANY], or "As an AI language model")?

If any HF is triggered: note it, set composite = 0, but still score all dimensions for diagnostic value.

STEP 2 — DIMENSION REASONING (chain of thought, one block per dimension)
For each of D1–D10, reason through the evidence explicitly. Reference specific text from
the briefing AND specific fields from the input tables. Be precise.

Key anchors to check:
  D1: Walk through every factual claim in the briefing (funding amount, employee count,
      founding date, founder names/titles, company location, product description).
      Map each to a specific input field. Flag any claim you cannot map.
  D2: Is the TL;DR 2–3 sentences? Does sentence 1 match the products field?
      Do sentences 2–3 reference the most compelling signals (funding, traffic growth, etc.)?
  D3: Are there 2–4 bullets? Do they draw from all 4 input tables? Is each bullet
      investment-specific (not just "company raised funding")?
  D4: Check all 7 required fields. Are missing fields marked "Not found in table"?
      Is a last-updated timestamp present?
  D5: Is every founder in the input data represented? Are backgrounds from Swarm data?
      Are missing backgrounds explicitly flagged?
  D6: Is every signal from key_signals rendered? Are website signals summarized
      (not just raw page titles)? Does each have source and timestamp?
  D7: Is every news_articles item rendered? Is the takeaway synthesized (not a
      verbatim copy of the excerpt)? Is every claim in the takeaway traceable
      to the article excerpt?
  D8: Are the meeting prep questions specific to this company's data? Reference
      the actual signals and news used as grounding.
  D9: Are all 7 sections present? In the correct order? With correct headings?
  D10: Is the writing crisp and scannable? Any grammatical errors or LLM artifacts?

STEP 3 — SCORE ASSIGNMENT
Assign integer scores 1–5 for each dimension.

STEP 4 — COMPOSITE
composite = (D1×20 + D2×12 + D3×12 + D4×8 + D5×8 + D6×10 + D7×10 + D8×10 + D9×5 + D10×5)
If any HF triggered: composite = 0.
Determine Pass (≥70) or Fail.

STEP 5 — OUTPUT JSON
Output ONLY the following JSON (no additional text before or after):

{{
  "context_tags": {{
    "data_richness": "<Rich|Moderate|Sparse>",
    "signal_coverage": "<Full|Partial|Minimal>",
    "news_availability": "<Yes|No>",
    "founder_data": "<Full|Partial|None>",
    "model": "<gpt-4o|gpt-4o-mini>",
    "entity_resolution": "<Correct|Incorrect|Ambiguous>"
  }},
  "hard_failures_detected": [],
  "hard_failure_triggered": false,
  "reasoning": {{
    "D1_factual_accuracy": "<chain-of-thought: walk through every factual claim and its source field>",
    "D2_tldr_quality": "<chain-of-thought>",
    "D3_why_meeting_matters": "<chain-of-thought: note which of the 4 input tables are drawn from>",
    "D4_company_snapshot": "<chain-of-thought: check all 7 fields and missing-field markers>",
    "D5_founder_information": "<chain-of-thought>",
    "D6_key_signals": "<chain-of-thought: compare signals in input vs. signals rendered>",
    "D7_news_synthesis": "<chain-of-thought: check each article for verbatim copy vs. synthesis>",
    "D8_meeting_prep": "<chain-of-thought: ground each question to a specific data point>",
    "D9_structural_compliance": "<chain-of-thought: list sections found and sections missing>",
    "D10_clarity_readability": "<chain-of-thought>"
  }},
  "dimensions": {{
    "D1": {{
      "score": <1-5>,
      "claims_checked": [
        {{"claim": "...", "input_field": "...", "status": "grounded|inference|hallucination"}}
      ]
    }},
    "D2": {{ "score": <1-5>, "sentence_count": <int>, "investment_signals_mentioned": [] }},
    "D3": {{
      "score": <1-5>,
      "bullet_count": <int>,
      "tables_referenced": [],
      "generic_bullets": []
    }},
    "D4": {{
      "score": <1-5>,
      "fields_present": [],
      "fields_missing_acknowledged": [],
      "fields_silently_omitted": [],
      "timestamp_present": <true|false>
    }},
    "D5": {{
      "score": <1-5>,
      "founders_in_input": <int>,
      "founders_rendered": <int>,
      "missing_backgrounds_flagged": <true|false>
    }},
    "D6": {{
      "score": <1-5>,
      "signals_in_input": <int>,
      "signals_rendered": <int>,
      "issues": []
    }},
    "D7": {{
      "score": <1-5>,
      "articles_in_input": <int>,
      "articles_rendered": <int>,
      "excerpt_dumps_detected": [],
      "fabricated_claims_in_takeaways": []
    }},
    "D8": {{
      "score": <1-5>,
      "questions_count": <int>,
      "next_step_present": <true|false>,
      "generic_questions": [],
      "grounded_questions": []
    }},
    "D9": {{
      "score": <1-5>,
      "sections_present": [],
      "sections_missing": [],
      "sections_misordered": []
    }},
    "D10": {{ "score": <1-5>, "issues": [] }}
  }},
  "failure_modes_detected": [],
  "composite_score": <float 0-100>,
  "composite_forced_to_zero": <true|false>,
  "pass_fail": "<Pass|Fail>"
}}
""".strip()

    return SYSTEM_PROMPT, user_prompt

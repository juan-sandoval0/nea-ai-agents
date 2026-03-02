"""
Judge prompt builder for the NEA News Aggregator Agent.

Input data:
    raw_signals     - list of all signals fetched BEFORE filtering (each signal is a dict
                      with keys: headline, company, signal_type, url, published_date,
                      excerpt, source, score, sentiment)
    watchlist       - list of dicts: {company_name, domain, category: "portfolio"|"competitor"}
    agent_output    - dict with keys: featured_articles, summary_articles, stats,
                      industry_highlights, markdown (the full digest string)
    context_tags    - dict with keys: run_mode, lookback_window, api_coverage,
                      watchlist_size, llm_mode, min_priority_threshold,
                      embedding_availability

Returns:
    (system_prompt: str, user_prompt: str) — ready for the Anthropic Messages API.

Note on D2 (Digest Recall):
    The judge can only assess recall against the raw_signals list provided. True recall
    requires external verification (checking Crunchbase, TechCrunch, Google News), which
    must be done by a human evaluator. The judge should score D2 conservatively and flag
    any signals in raw_signals that were NOT included in the digest despite high severity.
"""

import json
from typing import Any

# ---------------------------------------------------------------------------
# SYSTEM PROMPT
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = """You are an expert evaluator for NEA, a top-tier venture capital firm. \
Your job is to score weekly investment intelligence digests produced by an AI news \
aggregation system.

You will be given:
1. The raw signal list (all articles fetched before any filtering or ranking)
2. The watchlist of portfolio and competitor companies
3. The final digest output the agent produced
4. The evaluation rubric with full scoring definitions

Your evaluation must be:
- Anchored in the raw signal list. You can assess pipeline accuracy (filtering,
  classification, deduplication, ranking) only if you can see what signals existed before
  the pipeline processed them.
- Severity-weighted. A missed FUNDING signal for a portfolio company is far worse than a
  missed MARKET signal for a competitor.
- Hard-failure-first. Check for automatic disqualifiers (HF1–HF5) before scoring.
- Chain-of-thought first. Reason through each dimension before assigning scores.
- Structured. Output valid JSON matching the schema at the end of the prompt.

Composite score formula: [(S1×15)+(S2×10)+(S3×10)+(S4×8)+(S5×8)+(S6×4)+(S7×8)+(S8×4)+(D1×12)+(D2×10)+(D3×6)+(D4×5)] / 5 → yields 0–100."""


# ---------------------------------------------------------------------------
# RUBRIC TEXT
# ---------------------------------------------------------------------------

RUBRIC_TEXT = """
═══════════════════════════════════════════════════════════
NEWS AGGREGATOR SCORING RUBRIC v1.0
═══════════════════════════════════════════════════════════

GLOBAL SCALE
  5 = Excellent    — Every featured signal is relevant, correctly classified, properly sourced.
                     No false positives. All major portfolio events captured. Synopses are good.
  4 = Good         — Usable with minor issues. 1–2 borderline signals or one notable signal buried.
                     All critical events captured. Minor classification or sentiment error.
  3 = Acceptable   — Covers important events but has noticeable gaps: duplicate not merged,
                     competitor outranks similar portfolio signal, synopsis too vague.
  2 = Below Std    — Multiple misattributed signals, major event missing, homepage URL in digest,
                     or widespread classification errors. Not trustworthy without manual review.
  1 = Poor         — Wrong company signals dominate, portfolio company with major news has zero
                     signals, hallucinated synopsis, or digest is empty/broken.

SIGNAL SEVERITY MATRIX (for calibrating deductions)
  Signal Type                 | Portfolio Company | Competitor
  ─────────────────────────── | ─────────────────  | ──────────
  FUNDING / M&A / IPO         | CRITICAL           | HIGH
  SECURITY / LEGAL / LAYOFFS  | CRITICAL           | HIGH
  HIRING / team_change (C-suite)| HIGH             | MEDIUM
  PRODUCT / PARTNERSHIP / CUSTOMER| MEDIUM         | MEDIUM
  EARNINGS / MARKET / GENERAL | LOW                | LOW

──────────────────────────────────────────
TIER A: INDIVIDUAL SIGNAL QUALITY (pipeline accuracy)
──────────────────────────────────────────

S1: SIGNAL ATTRIBUTION ACCURACY  (weight 15%)
Is each signal correctly attributed to the right company?
  5: 100% of signals correctly attributed. No cross-industry name collisions leaked.
     Known ambiguous names (Sana, Merge) handled correctly.
  4: 99%+ accuracy. One borderline signal where the article mentions the target company
     only tangentially (appears in a competitor list, not as the subject).
  3: 95%+ accuracy. 1–2 signals attributed to wrong company, but errors are in non-featured
     positions and involve genuinely ambiguous names.
  2: 90–94% accuracy. Multiple misattributed signals, or one misattributed signal in Featured.
  1: Below 90% accuracy, or a Featured Story is about an entirely wrong company. Hard failure.
HARD FAILURE: Any Featured Story attributed to wrong company = automatic S1 = 1, composite = 0.

S2: FILTER QUALITY / NOISE REJECTION  (weight 10%)
Did the filter correctly remove homepages, press releases, Wikipedia, listicles, stale articles?
  5: Zero noise signals in the digest.
  4: Zero noise in Featured or More Headlines. One borderline item in industry trends.
  3: One noise signal in More Headlines (not Featured). Or one stale article (>7 days).
  2: Multiple noise signals, or one noise signal in Featured Stories.
  1: 3+ non-article URLs, press releases, or stale signals in digest. Hard failure if homepage in Featured.

S3: CLASSIFICATION ACCURACY  (weight 10%)
Is each signal assigned the correct signal type?
  5: All signals have the correct signal type.
  4: One minor misclassification on a non-featured signal where distinction is ambiguous.
  3: One misclassification on a featured signal (e.g., CEO hire classified as GENERAL instead of HIRING),
     or 2–3 misclassifications on non-featured signals.
  2: Multiple featured signals misclassified, or a CRITICAL-severity signal type is wrong.
  1: Widespread misclassification (>20% wrong). Or a FUNDING/M&A classified as GENERAL and excluded.
     Hard failure if a CRITICAL type classification error causes a portfolio event to be invisible.

S4: DEDUPLICATION QUALITY  (weight 8%)
Are same-event articles correctly merged? Are distinct events incorrectly merged?
  5: All same-event articles merged. No false merges. Primary URL from highest-quality source.
  4: All merges correct. One primary URL selection not optimal but correct article still accessible.
  3: One duplicate not merged (same event appears twice), or one false merge.
  2: Multiple duplicates visible. Or a false merge combining funding announcement with unrelated event.
  1: Deduplication non-functional: 3+ duplicate events in Featured, or critical false merges.

S5: SCORING & RANKING ACCURACY  (weight 8%)
Are signals ranked in the correct order?
  5: Featured stories are the 3 most important signals. Portfolio correctly prioritized.
     Recency bonus properly applied. Score breakdowns consistent with documented formula.
  4: Ranking correct for Featured. One minor ordering issue in More Headlines.
  3: One Featured Story arguably not top-3. Or competitor outranks portfolio signal of equal importance.
  2: A clearly low-importance signal (MARKET/GENERAL) in Featured while CRITICAL signal buried.
  1: Ranking is random. Critical portfolio signals missing from top positions.

S6: SENTIMENT ACCURACY  (weight 4%)
Is the sentiment label (positive/negative/neutral) correct?
  5: All signals have correct sentiment.
  4: One minor error on a genuinely ambiguous signal.
  3: 1–2 errors on non-featured signals. Or featured signal has wrong intensity.
  2: A featured signal has inverted sentiment (layoff marked positive, or funding marked negative).
  1: Widespread errors (>30% wrong). Or portfolio company's critical negative event marked positive.

S7: SYNOPSIS QUALITY — LLM-ENHANCED  (weight 8%)
Applies only when LLM mode is enabled and confidence ≥ 0.7. If LLM disabled: score N/A, redistribute weight to S8 and D1.
  5: 1–2 sentences. States what happened, why it matters, includes key numbers. Every claim
     traceable to headline/excerpt. Investment-relevant framing. Concise.
  4: Accurate and concise. Slightly generic framing but no hallucination. All facts traceable.
  3: Accurate but reads as paraphrase of headline (low synthesis). Or 3–4 sentences (too long).
  2: One claim not clearly supported by headline/excerpt (borderline hallucination). Or echo of input.
  1: Fabricated fact present. Automatic hard failure.
HARD FAILURE: Any hallucinated fact in LLM synopsis = S7 = 1. If in Featured Story, composite = 0 (HF1).

S8: SYNOPSIS QUALITY — TEMPLATE-BASED  (weight 4%)
  5: Template correctly populated all slots: company name, amount, series, context. Specific and informative.
  4: Mostly populated. One optional slot missing but core information present.
  3: Vague because extraction failed on key details. Technically correct but uninformative.
  2: Near-empty synopsis for a signal where rich data was available.
  1: Factually wrong (wrong amount extracted) or completely empty.

──────────────────────────────────────────
TIER B: DIGEST ASSEMBLY QUALITY
──────────────────────────────────────────

D1: DIGEST PRECISION  (weight 12%)
What % of signals in the digest view are truly relevant to the target companies?
  5: Precision ≥ 95%. Every signal is clearly about the correct company, is genuine news, and is timely.
  4: Precision 90–94%. 1–2 borderline signals.
  3: Precision 80–89%. 3–4 irrelevant signals. Noise visible but concentrated in More Headlines.
  2: Precision 70–79%. Noise visible in Featured or comprises >20% of digest.
  1: Precision < 70%. Digest is more noise than signal. Hard failure.

D2: DIGEST RECALL  (weight 10%)
What % of major real-world events were surfaced? Evaluate against the severity matrix.
NOTE: If Parallel Search did NOT return articles about an event (API Coverage = Partial/Degraded),
the missed event is a DATA AVAILABILITY issue, not a digest quality failure. Do not penalize D2.
For this automated evaluation, assess recall only against the raw_signals list provided.
Flag any CRITICAL or HIGH signals in raw_signals that did NOT make it into the digest.
  5: Recall ≥ 90%. All critical events for portfolio companies captured.
  4: Recall 80–89%. All critical events captured. 1–2 high events missed.
  3: Recall 70–79%. One critical competitor event missed, or 2–3 high events. All critical portfolio events present.
  2: Recall 60–69%. One critical portfolio event missed (API returned it but filter excluded it).
  1: Recall < 60%. Or critical portfolio event missed despite being in API data. Hard failure.

D3: DIGEST ORDERING & CURATION  (weight 6%)
Are Featured Stories the right 3? Is portfolio prioritized?
  5: Featured are unambiguously the 3 most important signals. Portfolio ranked above competitor
     signals of equal importance. Recency reflected. Industry Trends section adds context. Overview stats accurate.
  4: Featured correct. One minor curation issue.
  3: One Featured Story arguably not top-3. Or portfolio/competitor prioritization inconsistent. Or stats slightly off.
  2: Featured Stories include clearly low-priority signal while CRITICAL event is buried.
  1: Featured Stories essentially random. No coherent prioritization.

D4: STRUCTURAL & FORMAT COMPLIANCE  (weight 5%)
Does the digest follow documented Markdown format?
Section limits: ≤3 Featured, ≤8 More Headlines, ≤5 Industries.
  5: All sections present (Overview, Featured, More Headlines, optionally Industry Trends).
     Source URLs present and functional for every signal. Dates present. Section caps respected. Timestamp present.
  4: All sections present. One minor formatting issue. All source URLs present.
  3: One non-critical section missing. Or 1–2 signals missing source URLs. Or section caps slightly exceeded.
  2: Multiple format violations: missing source URLs for featured, no overview stats, or significantly exceeded caps.
  1: Structurally broken: missing Featured section, empty output, or wrong format.

──────────────────────────────────────────
HARD FAILURE CONDITIONS (composite = 0 if any triggered)
──────────────────────────────────────────
  HF1: LLM synopsis contains a hallucinated fact (not in headline/excerpt). Single instance in Featured = composite 0.
  HF2: A Featured Story (top 3) is attributed to the wrong company.
  HF3: A CRITICAL-severity event for a portfolio company was in the raw API data but absent from the digest
       due to a pipeline failure (filter, classification, or scoring error).
  HF4: A homepage URL (domain with no article path) appears anywhere in the digest view.
  HF5: The digest is empty, truncated, or structurally broken when raw data had signals above threshold.

COMPOSITE FORMULA
  Score = [(S1×15)+(S2×10)+(S3×10)+(S4×8)+(S5×8)+(S6×4)+(S7×8)+(S8×4)+(D1×12)+(D2×10)+(D3×6)+(D4×5)] / 5
  Yields 0–100. If any hard failure: composite = 0 regardless of dimension scores.
═══════════════════════════════════════════════════════════
"""


# ---------------------------------------------------------------------------
# HELPERS
# ---------------------------------------------------------------------------

def _fmt_watchlist(watchlist: list) -> str:
    if not watchlist:
        return "  (no watchlist data provided)"
    portfolio = [c for c in watchlist if c.get("category") == "portfolio"]
    competitors = [c for c in watchlist if c.get("category") == "competitor"]
    lines = ["  PORTFOLIO:"]
    for c in portfolio:
        lines.append(f"    • {c.get('company_name', 'Unknown')} ({c.get('domain', '')})")
    lines.append("  COMPETITORS:")
    for c in competitors:
        lines.append(f"    • {c.get('company_name', 'Unknown')} ({c.get('domain', '')})")
    return "\n".join(lines)


def _fmt_raw_signals(raw_signals: list) -> str:
    if not raw_signals:
        return "  (no raw signals provided — cannot assess pipeline accuracy)"
    lines = []
    for i, s in enumerate(raw_signals, 1):
        company = s.get("company", "?")
        signal_type = s.get("signal_type", "?")
        headline = s.get("headline", s.get("title", "?"))
        url = s.get("url", "")
        date = s.get("published_date", s.get("date", ""))
        score = s.get("score", s.get("relevance_score", "?"))
        sentiment = s.get("sentiment", "?")
        category = s.get("category", "?")
        excerpt = s.get("excerpt", "")[:200]
        lines.append(
            f"  [{i}] Company: {company} ({category})\n"
            f"      Type: {signal_type} | Score: {score} | Sentiment: {sentiment} | Date: {date}\n"
            f"      Headline: {headline}\n"
            f"      URL: {url}\n"
            f"      Excerpt: {excerpt}{'...' if len(s.get('excerpt',''))>200 else ''}"
        )
    return "\n\n".join(lines)


def _fmt_featured_articles(articles: list) -> str:
    if not articles:
        return "  (no featured articles in output)"
    lines = []
    for i, a in enumerate(articles, 1):
        lines.append(
            f"  [{i}] {a.get('headline', '?')}\n"
            f"      Company: {a.get('company', '?')} ({a.get('category', '?')})\n"
            f"      Type: {a.get('signal_type', '?')} | Score: {a.get('rank_score', a.get('relevance_score', '?'))}\n"
            f"      Sentiment: {a.get('sentiment', '?')} | Date: {a.get('published_date', '?')}\n"
            f"      Source: {a.get('source', '?')} | URL: {a.get('url', '?')}\n"
            f"      Synopsis: {a.get('synopsis', '(none)')}"
        )
    return "\n\n".join(lines)


def _fmt_summary_articles(articles: list) -> str:
    if not articles:
        return "  (no summary/more-headlines articles in output)"
    lines = []
    for i, a in enumerate(articles, 1):
        lines.append(
            f"  [{i}] {a.get('headline', '?')} — {a.get('company', '?')} "
            f"[{a.get('signal_type', '?')}] score={a.get('rank_score', '?')}"
        )
    return "\n".join(lines)


def _fmt_stats(stats: dict) -> str:
    if not stats:
        return "  (no stats)"
    return "\n".join(f"  {k}: {v}" for k, v in stats.items())


# ---------------------------------------------------------------------------
# MAIN BUILDER
# ---------------------------------------------------------------------------

def build_judge_prompt(
    raw_signals: list[dict[str, Any]],
    watchlist: list[dict[str, Any]],
    agent_output: dict[str, Any],
    context_tags: dict[str, Any],
) -> tuple[str, str]:
    """
    Build the (system_prompt, user_prompt) pair for the News Aggregator judge.

    Args:
        raw_signals:  All signals fetched BEFORE filtering/ranking. Essential for
                      assessing S2 (filter quality), S3 (classification), D2 (recall).
        watchlist:    List of {company_name, domain, category} — the companies being tracked.
        agent_output: Digest output dict with featured_articles, summary_articles,
                      stats, industry_highlights, and optionally markdown.
        context_tags: Run configuration — run_mode, lookback_window, api_coverage,
                      watchlist_size, llm_mode, min_priority_threshold,
                      embedding_availability.

    Returns:
        (system_prompt, user_prompt) strings for the Messages API.
    """
    run_mode = context_tags.get("run_mode", "digest")
    lookback = context_tags.get("lookback_window", 7)
    api_coverage = context_tags.get("api_coverage", "Unknown")
    watchlist_size = context_tags.get("watchlist_size", len(watchlist))
    llm_mode = context_tags.get("llm_mode", "Unknown")
    min_priority = context_tags.get("min_priority_threshold", 40)
    embedding_avail = context_tags.get("embedding_availability", "Unknown")

    featured = agent_output.get("featured_articles", [])
    summary = agent_output.get("summary_articles", [])
    stats = agent_output.get("stats", {})
    markdown = agent_output.get("markdown", "")

    user_prompt = f"""
{RUBRIC_TEXT}

═══════════════════════════════════════════════════════════
EVALUATION CONTEXT TAGS
═══════════════════════════════════════════════════════════
  Run Mode:              {run_mode}
  Lookback Window:       {lookback} days
  API Coverage:          {api_coverage}
  Watchlist Size:        {watchlist_size} companies
  LLM Mode:             {llm_mode}
  Min Priority Threshold:{min_priority}
  Embedding Availability:{embedding_avail}

═══════════════════════════════════════════════════════════
INPUT DATA
═══════════════════════════════════════════════════════════

── WATCHLIST ──
{_fmt_watchlist(watchlist)}

── RAW SIGNALS (all fetched signals BEFORE filtering) ──
  Total raw signals: {len(raw_signals)}
{_fmt_raw_signals(raw_signals)}

═══════════════════════════════════════════════════════════
AGENT OUTPUT
═══════════════════════════════════════════════════════════

── DIGEST STATS ──
{_fmt_stats(stats)}

── FEATURED STORIES ({len(featured)} articles) ──
{_fmt_featured_articles(featured)}

── MORE HEADLINES / SUMMARY ({len(summary)} articles) ──
{_fmt_summary_articles(summary)}

── FULL MARKDOWN DIGEST ──
{markdown if markdown else "(no markdown output — check for structural failure)"}

═══════════════════════════════════════════════════════════
EVALUATION INSTRUCTIONS
═══════════════════════════════════════════════════════════

Follow these steps exactly:

STEP 1 — HARD FAILURE SCAN (HF1–HF5)
Check each hard failure condition. If any is triggered, set composite = 0 immediately
and note which HF was triggered. Still score all dimensions (for diagnostic purposes),
but the composite will be forced to 0.

  HF1: Does any LLM synopsis in Featured Stories contain a factual claim (number, date,
       event, company name) not traceable to the provided headline/excerpt?
  HF2: Is any Featured Story (top 3) attributed to a company that the article is
       clearly NOT about?
  HF3: Is there a CRITICAL-severity signal for a PORTFOLIO company in the raw_signals
       list that does NOT appear anywhere in the digest? (This is a pipeline failure.)
  HF4: Does any featured or headline entry have a homepage URL (domain with no path)?
  HF5: Is the digest empty, truncated, or structurally broken despite raw_signals
       containing signals above the minimum threshold?

STEP 2 — DIMENSION REASONING (chain of thought per dimension)
For each of S1–S8 and D1–D4, reason through the evidence before scoring.
Reference specific signals by their index [N] from the raw_signals list.
Reference specific featured articles by their position in Featured Stories.

  Key questions to address in your reasoning:
  S1: For each signal in the digest, is it genuinely about the attributed company?
      Any name collision candidates in the watchlist?
  S2: Are there any noise signals (homepages, press releases, Wikipedia, listicles)
      that appeared in the digest?
  S3: Compare the signal_type assigned to each digest article vs. what type it
      should be based on its headline/excerpt.
  S4: Are there raw signals covering the same event as a digest signal? Were they
      merged? Was the primary URL from the highest-quality source?
  S5: Does the ranking of Featured Stories reflect importance (signal severity ×
      company category) + recency? Is portfolio prioritized over competitor?
  S6: Is the sentiment label on each signal consistent with the article content?
  S7: For each LLM synopsis in Featured Stories, is every claim in the synopsis
      traceable to the headline or excerpt? Flag any potential hallucinations.
  S8: For template-based synopses, were key slots (amount, company, series) filled?
  D1: What % of digest signals are truly relevant (not noise, not wrong company)?
  D2: Cross-reference raw_signals with digest. Any CRITICAL/HIGH severity signals
      in raw_signals that did NOT appear in the digest? Why?
  D3: Are the Featured 3 the most important signals? Is portfolio prioritized?
      Is the Industry Trends section present and useful?
  D4: Is the Markdown structure correct? Source links? Dates? Section limits respected?

STEP 3 — SCORE ASSIGNMENT
Assign integer scores 1–5 for each dimension. Apply deductions where specified.
Note: For S7, if LLM mode is disabled, score N/A and redistribute 8% weight equally to S8 (4+4=8%) and D1 (12+4=16%).

STEP 4 — COMPOSITE
Apply the formula: [(S1×15)+(S2×10)+(S3×10)+(S4×8)+(S5×8)+(S6×4)+(S7×8)+(S8×4)+(D1×12)+(D2×10)+(D3×6)+(D4×5)] / 5
If any HF triggered, composite = 0.

STEP 5 — OUTPUT JSON
Output ONLY the following JSON (no additional text before or after):

{{
  "context_tags": {{
    "run_mode": "{run_mode}",
    "lookback_window": {lookback},
    "api_coverage": "{api_coverage}",
    "watchlist_size": {watchlist_size},
    "llm_mode": "{llm_mode}",
    "min_priority_threshold": {min_priority},
    "embedding_availability": "{embedding_avail}"
  }},
  "hard_failures_detected": [],
  "hard_failure_triggered": false,
  "reasoning": {{
    "S1_attribution": "<chain-of-thought>",
    "S2_filter_quality": "<chain-of-thought>",
    "S3_classification": "<chain-of-thought>",
    "S4_deduplication": "<chain-of-thought>",
    "S5_ranking": "<chain-of-thought>",
    "S6_sentiment": "<chain-of-thought>",
    "S7_synopsis_llm": "<chain-of-thought or 'N/A — LLM mode disabled'>",
    "S8_synopsis_template": "<chain-of-thought>",
    "D1_precision": "<chain-of-thought>",
    "D2_recall": "<chain-of-thought>",
    "D3_ordering": "<chain-of-thought>",
    "D4_format": "<chain-of-thought>"
  }},
  "dimensions": {{
    "S1": {{ "score": <1-5>, "misattributed_signals": [] }},
    "S2": {{ "score": <1-5>, "noise_signals_found": [] }},
    "S3": {{ "score": <1-5>, "misclassified_signals": [
      {{"headline": "...", "assigned_type": "...", "correct_type": "...", "reasoning": "..."}}
    ]}},
    "S4": {{ "score": <1-5>, "unmerged_duplicates": [], "false_merges": [] }},
    "S5": {{ "score": <1-5>, "ranking_issues": [] }},
    "S6": {{ "score": <1-5>, "sentiment_errors": [] }},
    "S7": {{ "score": "<1-5 or N/A>", "hallucinations_detected": [] }},
    "S8": {{ "score": <1-5>, "template_issues": [] }},
    "D1": {{ "score": <1-5>, "precision_estimate": "<percentage>", "irrelevant_signals": [] }},
    "D2": {{ "score": <1-5>, "recall_note": "automated — only raw_signals assessed, external check required",
             "missed_critical_signals": [], "missed_high_signals": [] }},
    "D3": {{ "score": <1-5>, "curation_issues": [] }},
    "D4": {{ "score": <1-5>, "format_violations": [] }}
  }},
  "failure_modes_detected": [],
  "composite_score": <float 0-100>,
  "composite_forced_to_zero": <true|false>
}}
""".strip()

    return SYSTEM_PROMPT, user_prompt

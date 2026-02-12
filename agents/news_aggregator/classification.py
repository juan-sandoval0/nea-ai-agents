"""
Hybrid Classification Module for News Aggregator
=================================================

Re-engineered classification system combining:
1. Fast regex rules for high-precision triggers
2. Embedding-based similarity for ambiguous cases
3. Combined confidence scoring with traceability

## How Type Classification Works

Classification follows a two-stage approach:

### Stage 1: Fast Rule Matching
- High-precision regex patterns for each Type (e.g., "raised $" -> FUNDING)
- If a rule matches with confidence >= 0.75, classification is immediate
- Rules provide matched evidence (e.g., "raised $50M", "series a")

### Stage 2: Embedding Similarity (for ambiguous cases)
- If rules don't match or have low confidence, compute embedding for title+snippet
- Compare against pre-computed Type prototype embeddings (stored in memory)
- Uses cosine similarity to find best matching Type
- Evidence shows top Type similarities (e.g., "FUNDING:0.75, M&A:0.60")

### Combined Scoring
- If rules and embeddings agree, confidence is boosted
- If they disagree, the method with higher confidence wins
- Evidence combines both sources for full traceability

## Synopsis Generation (No Full Article Text)

Synopsis is generated using ONLY proxy fields:
- Titles (short)
- Snippets (max 300 chars)
- Classification + evidence
- Sentiment + keywords

Two methods:
1. Template-based (no LLM): Used when classification confidence >= 0.7
2. Small LLM call: Uses gpt-4o-mini with minimal tokens, only proxy fields

## Caching Behavior
- Embeddings are cached by URL hash to prevent duplicate computation
- Prototype embeddings are computed once at startup (memory-cached)
- Synopsis is cached by story_id

Classification Types:
- FUNDING, M&A, IPO, SECURITY, LEGAL, LAYOFFS, HIRING
- PARTNERSHIP, PRODUCT, EARNINGS, CUSTOMER, MARKET, GENERAL

Usage:
    from agents.news_aggregator.classification import classify_story_hybrid

    result = classify_story_hybrid(title, snippet, url)
    # result = ClassificationResult(type='FUNDING', confidence=0.85, evidence=['raised', '$50M'])
"""

from __future__ import annotations

import re
import logging
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple
import numpy as np

from .embeddings import get_embedding_service

logger = logging.getLogger(__name__)

# =============================================================================
# HIGH-PRECISION RULE TRIGGERS
# =============================================================================
# These patterns have very high precision for specific Types.
# If matched, we can classify with high confidence without embeddings.

HIGH_PRECISION_RULES: Dict[str, List[Tuple[str, float]]] = {
    'FUNDING': [
        # Pattern, base confidence
        (r'raises?\s+\$\d+', 0.95),
        (r'raised\s+\$\d+', 0.95),
        (r'series\s+[a-k]\b', 0.90),
        (r'\$\d+[mb]\s+(?:funding|round|raise)', 0.92),
        (r'seed\s+(?:round|funding)', 0.88),
        (r'valuation\s+(?:of\s+)?\$\d+', 0.85),
        (r'unicorn\s+status', 0.90),
        (r'led\s+by.*(?:capital|ventures|partners)', 0.80),
        (r'growth\s+equity', 0.82),
        (r'investment\s+from', 0.75),
    ],
    'M&A': [
        (r'(?:has\s+)?acquir(?:es?|ed|ing)\s+', 0.95),
        (r'(?:to\s+)?acquire\s+', 0.92),
        (r'acquisition\s+of', 0.95),
        (r'merger\s+(?:with|between)', 0.95),
        (r'bought\s+by', 0.92),
        (r'purchased\s+by', 0.90),
        (r'buyout', 0.88),
        (r'takeover', 0.85),
        (r'sold\s+to', 0.85),
    ],
    'IPO': [
        (r'\bipo\b', 0.95),
        (r'initial\s+public\s+offering', 0.98),
        (r'going\s+public', 0.92),
        (r'files?\s+(?:for\s+)?s-?1', 0.95),
        (r'nasdaq\s+(?:listing|debut)', 0.92),
        (r'nyse\s+(?:listing|debut)', 0.92),
        (r'direct\s+listing', 0.90),
        (r'spac\s+(?:merger|deal)', 0.88),
    ],
    'SECURITY': [
        (r'data\s+breach', 0.95),
        (r'security\s+breach', 0.95),
        (r'hack(?:ed|ing|er)', 0.92),
        (r'ransomware', 0.95),
        (r'cyber\s*attack', 0.95),
        (r'vulnerability\s+(?:in|discovered)', 0.90),
        (r'data\s+leak', 0.92),
        (r'compromised', 0.80),
        (r'security\s+incident', 0.88),
        (r'major\s+outage', 0.75),
    ],
    'LEGAL': [
        (r'(?:class\s+action\s+)?lawsuit', 0.92),
        (r'sued\s+(?:by|for)', 0.90),
        (r'litigation', 0.85),
        (r'antitrust\s+(?:suit|investigation|probe)', 0.95),
        (r'ftc\s+(?:investigation|probe|charges)', 0.95),
        (r'sec\s+(?:investigation|probe|charges)', 0.95),
        (r'doj\s+(?:investigation|probe)', 0.95),
        (r'settlement\s+(?:of|with|for)', 0.85),
        (r'regulatory\s+(?:fine|penalty)', 0.88),
    ],
    'LAYOFFS': [
        (r'lay(?:off|ing\s+off)\s+\d+', 0.95),
        (r'laid\s+off', 0.95),
        (r'(?:job|workforce)\s+(?:cuts?|reduction)', 0.92),
        (r'cut(?:ting)?\s+\d+%?\s+(?:of\s+)?(?:staff|jobs|employees)', 0.95),
        (r'downsiz(?:e|ed|ing)', 0.90),
        (r'restructur(?:e|ed|ing)\s+.*(?:job|staff|employee)', 0.85),
        (r'headcount\s+reduction', 0.92),
        (r'workforce\s+reduction', 0.92),
    ],
    'HIRING': [
        (r'hir(?:e|ed|ing)\s+\d+', 0.85),
        (r'hiring\s+spree', 0.88),
        (r'(?:new|appoints?|names?)\s+(?:ceo|cto|cfo|coo|cpo)', 0.90),
        (r'(?:joins?\s+as|named)\s+(?:ceo|cto|cfo|coo)', 0.90),
        (r'executive\s+hire', 0.85),
        (r'expanding\s+(?:the\s+)?team', 0.75),
        (r'headcount\s+growth', 0.80),
    ],
    'PARTNERSHIP': [
        (r'partner(?:s|ed|ing|ship)\s+with', 0.90),
        (r'strategic\s+partnership', 0.92),
        (r'alliance\s+with', 0.85),
        (r'collaboration\s+with', 0.80),
        (r'teams?\s+up\s+with', 0.85),
        (r'joint\s+venture', 0.88),
        (r'integrat(?:e|es|ed|ing)\s+with', 0.75),
    ],
    'PRODUCT': [
        (r'launch(?:es|ed|ing)?\s+(?:new|its)', 0.85),
        (r'announces?\s+(?:new|its)\s+\w+\s+(?:product|feature|tool)', 0.88),
        (r'introduces?\s+(?:new|its)', 0.82),
        (r'unveils?\s+', 0.85),
        (r'rolls?\s+out', 0.80),
        (r'debuts?\s+', 0.82),
        (r'ships?\s+(?:new|v\d|version)', 0.80),
        (r'beta\s+(?:launch|release)', 0.82),
        (r'ga\s+release', 0.85),
        (r'product\s+(?:launch|update|announcement)', 0.85),
    ],
    'EARNINGS': [
        (r'quarterly\s+(?:earnings|results|revenue)', 0.92),
        (r'fiscal\s+(?:q\d|year)', 0.88),
        (r'revenue\s+(?:of|hits|reaches)\s+\$', 0.85),
        (r'(?:beats?|miss(?:es)?)\s+(?:earnings|estimates)', 0.92),
        (r'reports?\s+(?:earnings|revenue|profit)', 0.85),
        (r'arr\s+(?:of|reaches|hits)\s+\$', 0.88),
        (r'(?:achieves?|reaches?)\s+profitability', 0.88),
    ],
    'CUSTOMER': [
        (r'(?:lands?|wins?)\s+(?:major|big|enterprise)\s+(?:deal|contract)', 0.88),
        (r'signs?\s+(?:deal|contract)\s+with', 0.80),
        (r'customer\s+(?:win|announcement)', 0.85),
        (r'enterprise\s+(?:deal|customer)', 0.82),
        (r'fortune\s+500\s+(?:deal|customer|company)', 0.85),
        (r'expands?\s+(?:to|into)\s+(?:new\s+)?market', 0.75),
    ],
    'MARKET': [
        (r'industry\s+(?:report|analysis|outlook|trend)', 0.85),
        (r'market\s+(?:report|analysis|outlook|trend)', 0.85),
        (r'sector\s+(?:report|analysis)', 0.82),
        (r'(?:macro|economic)\s+(?:trend|outlook|conditions)', 0.80),
        (r'regulatory\s+(?:change|update|news)', 0.78),
    ],
}

# Keywords for evidence extraction (simpler patterns for fast matching)
EVIDENCE_KEYWORDS: Dict[str, List[str]] = {
    'FUNDING': ['raises', 'raised', 'funding', 'series', 'valuation', 'unicorn', 'seed', 'investment', 'round', 'vc', 'venture', 'capital'],
    'M&A': ['acquire', 'acquired', 'acquisition', 'merger', 'buyout', 'takeover', 'bought', 'purchased', 'sold'],
    'IPO': ['ipo', 'public', 's-1', 'nasdaq', 'nyse', 'listing', 'spac', 'offering'],
    'SECURITY': ['breach', 'hack', 'ransomware', 'attack', 'vulnerability', 'leak', 'compromised', 'incident', 'outage', 'security'],
    'LEGAL': ['lawsuit', 'sued', 'litigation', 'antitrust', 'ftc', 'sec', 'doj', 'settlement', 'fine', 'regulatory'],
    'LAYOFFS': ['layoff', 'laid off', 'cuts', 'downsizing', 'restructuring', 'reduction', 'fired'],
    'HIRING': ['hiring', 'hired', 'hire', 'ceo', 'cto', 'cfo', 'appoints', 'named', 'executive', 'expanding'],
    'PARTNERSHIP': ['partner', 'partnership', 'alliance', 'collaboration', 'teams up', 'joint venture', 'integration'],
    'PRODUCT': ['launch', 'launches', 'launched', 'announces', 'introduces', 'unveils', 'releases', 'debuts', 'ships', 'beta', 'feature'],
    'EARNINGS': ['earnings', 'revenue', 'profit', 'quarterly', 'fiscal', 'arr', 'guidance', 'profitability'],
    'CUSTOMER': ['deal', 'contract', 'customer', 'enterprise', 'expands', 'market', 'win'],
    'MARKET': ['industry', 'market', 'sector', 'macro', 'economic', 'trend', 'outlook', 'regulatory'],
}


# =============================================================================
# DATA MODELS
# =============================================================================

@dataclass
class ClassificationResult:
    """Result of story classification."""
    type: str
    confidence: float  # 0.0 - 1.0
    evidence: List[str] = field(default_factory=list)
    method: str = "hybrid"  # 'rules', 'embeddings', or 'hybrid'

    def to_dict(self) -> Dict:
        return {
            'type': self.type,
            'confidence': round(self.confidence, 3),
            'evidence': self.evidence,
            'method': self.method,
        }


# =============================================================================
# CLASSIFICATION FUNCTIONS
# =============================================================================

def _match_rules(text: str) -> List[Tuple[str, float, str]]:
    """
    Match text against high-precision rules.

    Returns:
        List of (type, confidence, matched_pattern)
    """
    matches = []
    text_lower = text.lower()

    for type_name, patterns in HIGH_PRECISION_RULES.items():
        for pattern, base_confidence in patterns:
            match = re.search(pattern, text_lower, re.IGNORECASE)
            if match:
                matched_text = match.group(0)
                matches.append((type_name, base_confidence, matched_text))

    return matches


def _extract_evidence(text: str, type_name: str) -> List[str]:
    """Extract evidence keywords for a classification."""
    evidence = []
    text_lower = text.lower()

    keywords = EVIDENCE_KEYWORDS.get(type_name, [])
    for kw in keywords:
        if kw.lower() in text_lower:
            evidence.append(kw)

    # Also extract dollar amounts for FUNDING/M&A/EARNINGS
    if type_name in ('FUNDING', 'M&A', 'EARNINGS', 'CUSTOMER'):
        amounts = re.findall(r'\$\d+(?:\.\d+)?[mbk]?(?:illion)?', text_lower)
        evidence.extend(amounts[:2])

    return evidence[:5]  # Limit evidence length


def classify_by_rules(title: str, snippet: str = "") -> Optional[ClassificationResult]:
    """
    Classify using high-precision regex rules only.

    Returns ClassificationResult if a high-confidence match is found, else None.
    """
    text = f"{title} {snippet}"
    matches = _match_rules(text)

    if not matches:
        return None

    # Sort by confidence descending
    matches.sort(key=lambda x: x[1], reverse=True)

    best_type, best_conf, matched_pattern = matches[0]

    # Boost confidence if multiple patterns match same type
    same_type_matches = [m for m in matches if m[0] == best_type]
    if len(same_type_matches) > 1:
        best_conf = min(1.0, best_conf + 0.05 * (len(same_type_matches) - 1))

    evidence = _extract_evidence(text, best_type)
    evidence.insert(0, matched_pattern)  # Add matched pattern as first evidence

    return ClassificationResult(
        type=best_type,
        confidence=best_conf,
        evidence=evidence[:5],
        method='rules',
    )


def classify_by_embeddings(
    title: str,
    snippet: str = "",
    url: str = None,
    exclude_types: List[str] = None
) -> ClassificationResult:
    """
    Classify using embedding similarity to Type prototypes.
    """
    service = get_embedding_service()

    # Get embedding for this story
    embedding = service.get_embedding(title, snippet, url)

    # Get similarities to all Type prototypes
    similarities = service.get_type_similarities(embedding)

    # Find best match
    exclude = set(exclude_types or [])
    best_type = 'GENERAL'
    best_score = 0.0

    for type_name, score in similarities.items():
        if type_name in exclude:
            continue
        if score > best_score:
            best_type = type_name
            best_score = score

    # Convert similarity (roughly 0-1) to confidence
    # Typical similarities range from 0.3-0.8
    confidence = min(1.0, max(0.0, (best_score - 0.3) / 0.4))

    # Get top 3 matching types as evidence
    sorted_types = sorted(similarities.items(), key=lambda x: x[1], reverse=True)
    evidence = [f"{t}:{s:.2f}" for t, s in sorted_types[:3]]

    return ClassificationResult(
        type=best_type,
        confidence=confidence,
        evidence=evidence,
        method='embeddings',
    )


def classify_story_hybrid(
    title: str,
    snippet: str = "",
    url: str = None,
    rule_confidence_threshold: float = 0.75
) -> ClassificationResult:
    """
    Hybrid classification using rules + embeddings.

    Strategy:
    1. Try high-precision rules first
    2. If rules match with high confidence (>= threshold), use rule result
    3. Otherwise, use embeddings to classify
    4. If both methods agree, boost confidence

    Args:
        title: Article title
        snippet: Article snippet/description
        url: Optional URL for embedding caching
        rule_confidence_threshold: Minimum rule confidence to trust (default 0.75)

    Returns:
        ClassificationResult with type, confidence, and evidence
    """
    # Step 1: Try rules first (fast)
    rule_result = classify_by_rules(title, snippet)

    # If rules give high confidence, use them
    if rule_result and rule_result.confidence >= rule_confidence_threshold:
        return rule_result

    # Step 2: Use embeddings
    emb_result = classify_by_embeddings(title, snippet, url)

    # Step 3: Combine results if both are available
    if rule_result:
        # Both rules and embeddings have results
        if rule_result.type == emb_result.type:
            # Agreement - boost confidence
            combined_conf = min(1.0, max(rule_result.confidence, emb_result.confidence) + 0.1)
            combined_evidence = rule_result.evidence[:3] + emb_result.evidence[:2]
            return ClassificationResult(
                type=rule_result.type,
                confidence=combined_conf,
                evidence=combined_evidence[:5],
                method='hybrid',
            )
        else:
            # Disagreement - use higher confidence
            if rule_result.confidence > emb_result.confidence:
                return rule_result
            else:
                # Combine evidence from both
                emb_result.evidence = emb_result.evidence[:3] + rule_result.evidence[:2]
                emb_result.method = 'hybrid'
                return emb_result

    # No rule match, use embeddings only
    return emb_result


def classify_stories_batch(
    stories: List[Dict],
    title_key: str = 'title',
    snippet_key: str = 'snippet',
    url_key: str = 'url'
) -> List[ClassificationResult]:
    """
    Classify multiple stories efficiently.

    Args:
        stories: List of story dicts with title, snippet, url
        title_key, snippet_key, url_key: Keys for accessing story fields

    Returns:
        List of ClassificationResult, same order as input
    """
    results = []
    for story in stories:
        title = story.get(title_key, '')
        snippet = story.get(snippet_key, '')
        url = story.get(url_key)
        result = classify_story_hybrid(title, snippet, url)
        results.append(result)
    return results


# =============================================================================
# SYNOPSIS GENERATION (Template-Based, No Full Article Text)
# =============================================================================

SYNOPSIS_TEMPLATES: Dict[str, str] = {
    'FUNDING': "{company} {amount_phrase}. {context}",
    'M&A': "{company} {action}. {context}",
    'IPO': "{company} is going public{details}. {context}",
    'SECURITY': "{company} experienced a security incident{details}. {context}",
    'LEGAL': "{company} faces legal challenges{details}. {context}",
    'LAYOFFS': "{company} announced workforce reductions{details}. {context}",
    'HIRING': "{company} is expanding leadership{details}. {context}",
    'PARTNERSHIP': "{company} formed a strategic partnership{details}. {context}",
    'PRODUCT': "{company} launched{details}. {context}",
    'EARNINGS': "{company} reported financial results{details}. {context}",
    'CUSTOMER': "{company} secured a significant customer win{details}. {context}",
    'MARKET': "Industry developments affecting {company}{details}. {context}",
    'GENERAL': "{company}: {summary}",
}


def extract_structured_cues(text: str) -> Dict[str, str]:
    """Extract structured information from title/snippet."""
    cues = {}

    # Dollar amounts
    amounts = re.findall(r'\$\d+(?:\.\d+)?(?:\s*[BMK](?:illion)?)?', text, re.IGNORECASE)
    if amounts:
        cues['amount'] = amounts[0]

    # Series round
    series = re.search(r'[Ss]eries\s+([A-K])', text)
    if series:
        cues['series'] = f"Series {series.group(1)}"

    # Percentage
    pct = re.search(r'(\d+(?:\.\d+)?)\s*%', text)
    if pct:
        cues['percentage'] = f"{pct.group(1)}%"

    # Headcount numbers
    headcount = re.search(r'(\d+(?:,\d+)?)\s+(?:employees?|jobs?|positions?|workers?|staff)', text, re.IGNORECASE)
    if headcount:
        cues['headcount'] = headcount.group(1)

    # Company names (quoted or capitalized)
    quoted = re.findall(r'"([^"]+)"', text)
    if quoted:
        cues['quoted_names'] = quoted[:2]

    return cues


def generate_template_synopsis(
    company_name: str,
    classification: str,
    title: str,
    snippet: str = "",
    cues: Dict[str, str] = None
) -> str:
    """
    Generate synopsis using templates (no full article text needed).

    Args:
        company_name: Company name
        classification: Story classification type
        title: Article title
        snippet: Article snippet
        cues: Pre-extracted structured cues (optional)

    Returns:
        Generated synopsis (2-4 sentences)
    """
    if cues is None:
        cues = extract_structured_cues(f"{title} {snippet}")

    # Build amount phrase for FUNDING
    amount_phrase = "secured new funding"
    if cues.get('amount'):
        if cues.get('series'):
            amount_phrase = f"raised {cues['amount']} in {cues['series']} funding"
        else:
            amount_phrase = f"raised {cues['amount']}"

    # Build details suffix
    details = ""
    if cues.get('amount') and classification in ('M&A', 'IPO', 'EARNINGS'):
        details = f" ({cues['amount']})"
    elif cues.get('headcount') and classification in ('LAYOFFS', 'HIRING'):
        details = f" affecting {cues['headcount']} employees"
    elif cues.get('percentage') and classification == 'LAYOFFS':
        details = f" ({cues['percentage']} of workforce)"

    # Generate first sentence from template
    template = SYNOPSIS_TEMPLATES.get(classification, SYNOPSIS_TEMPLATES['GENERAL'])

    # Clean title for use as summary
    summary = title[:100]
    if len(title) > 100:
        summary = title[:97] + "..."

    # Build context from snippet (first meaningful sentence)
    context = ""
    if snippet:
        sentences = re.split(r'[.!?]+', snippet)
        for sent in sentences:
            sent = sent.strip()
            if len(sent) > 30:
                context = sent[:150] + "." if len(sent) > 150 else sent + "."
                break

    # Format template
    synopsis = template.format(
        company=company_name,
        amount_phrase=amount_phrase,
        action="completed an acquisition" if "acquir" in title.lower() else "is involved in M&A activity",
        details=details,
        context=context,
        summary=summary,
    )

    # Clean up
    synopsis = re.sub(r'\s+', ' ', synopsis).strip()
    synopsis = re.sub(r'\.\s*\.', '.', synopsis)

    return synopsis[:400]


# =============================================================================
# TIMING STATS
# =============================================================================

def get_classification_stats() -> Dict:
    """Get timing statistics from embedding service."""
    service = get_embedding_service()
    return service.get_stats()

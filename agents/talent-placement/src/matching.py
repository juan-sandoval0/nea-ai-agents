"""Score and rank employee × destination pairs using the claude CLI."""
from __future__ import annotations

import json
import logging
import os
import subprocess
from .models import Employee, Destination, Match

logger = logging.getLogger(__name__)

_SYSTEM = """\
You are a talent placement advisor for NEA, a venture capital firm.
You evaluate how well a departing portfolio company employee fits open job requisitions.
These employees are being placed from a winding-down portfolio company.

Score each employee-role pair on five dimensions (0-100 each):

1. functional_skill (30%): Does their core function match the role?
   80-100: Direct match
   60-79: Strong overlap, one gap
   40-59: Partial match, retraining needed
   20-39: Weak/tangential
   0-19: No overlap

2. seniority (20%): Symmetric — both over and under-qualified are penalized.
   80-100: Same level or one-level transition
   60-79: One level off
   40-59: Two levels off
   0-39: Three or more levels off

3. transition_pattern (15%): Given employee is from a winding-down company:
   80-100: Lateral move (same level, new context) — high success rate
   70-90: Intentional step-up with trajectory supporting growth
   60-80: Intentional step-down (founder/exec to operator at earlier stage)
   20-40: Forced step-down with no intentional-choice signal
   30-50: Premature step-up without supporting trajectory

4. stage_fit (20%): Does their company stage experience match hiring company?
   80-100: Same or adjacent stage
   60-79: One stage off
   40-59: Two stages off
   0-39: Fundamentally different

5. domain_overlap (15%): Industry transferability:
   80-100: Same domain
   60-79: Adjacent domain
   40-59: Some overlap
   0-39: Major shift

Respond ONLY with a JSON array, one object per role, in the same order as given:
[
  {
    "functional_skill": <0-100>,
    "seniority": <0-100>,
    "transition_pattern": <0-100>,
    "stage_fit": <0-100>,
    "domain_overlap": <0-100>,
    "reasoning": "<one sentence on the most important factor>"
  },
  ...
]
"""

_FALLBACK = {"functional_skill": 0, "seniority": 0, "transition_pattern": 0, "stage_fit": 0, "domain_overlap": 0, "reasoning": "Scoring unavailable"}

_PREFILTER_LIMIT = 100


def _composite(s: dict) -> float:
    return (
        0.30 * s.get("functional_skill", 0)
        + 0.20 * s.get("seniority", 0)
        + 0.15 * s.get("transition_pattern", 0)
        + 0.20 * s.get("stage_fit", 0)
        + 0.15 * s.get("domain_overlap", 0)
    ) / 100.0
_BATCH_SIZE = 25


def _prefilter(employee: Employee, destinations: list[Destination]) -> list[Destination]:
    """Keyword-rank destinations and return top _PREFILTER_LIMIT before LLM scoring."""
    if len(destinations) <= _PREFILTER_LIMIT:
        return destinations
    title_words = set((employee.title or "").lower().split())
    if not title_words:
        return destinations[:_PREFILTER_LIMIT]

    def score(dest: Destination) -> int:
        role_words = set(dest.role.lower().split())
        return len(title_words & role_words)

    return sorted(destinations, key=score, reverse=True)[:_PREFILTER_LIMIT]


def _score_batch(employee: Employee, batch: list[Destination]) -> list[dict]:
    """Score one batch of up to _BATCH_SIZE destinations against an employee."""
    roles_text = "\n".join(
        f"{i + 1}. {d.role} @ {d.company}" + (f" ({d.location})" if d.location else "")
        for i, d in enumerate(batch)
    )
    tenure = f"{employee.tenure_years:.1f} years" if employee.tenure_years is not None else "Unknown"
    companies = str(employee.career_company_count) if employee.career_company_count is not None else "Unknown"
    prompt = f"""\
Employee:
- Name: {employee.name}
- Title: {employee.title or "Unknown"}
- Company: {employee.company}
- Founder: {employee.is_founder}, Executive: {employee.is_executive}
- Tenure at current company: {tenure}
- Distinct companies in career: {companies}

Score this employee against each open role below. Return a JSON array with one object per role in the same order:
{roles_text}"""

    try:
        env = {k: v for k, v in os.environ.items() if k != "ANTHROPIC_API_KEY"}
        result = subprocess.run(
            [
                "claude", "-p",
                "--output-format", "json",
                "--system-prompt", _SYSTEM,
                prompt,
            ],
            capture_output=True,
            text=True,
            timeout=180,
            env=env,
        )
        data = json.loads(result.stdout)
        raw = data["result"].strip()
        if raw.startswith("```"):
            raw = raw.split("\n", 1)[1].rsplit("```", 1)[0].strip()
        scores = json.loads(raw)
        if not isinstance(scores, list):
            raise ValueError("Expected a JSON array")
        return scores
    except Exception as e:
        logger.error("Batch scoring failed for %s: %s", employee.name, e)
        return [_FALLBACK] * len(batch)


def rank_matches(
    employee: Employee,
    destinations: list[Destination],
    top_n: int = 5,
) -> list[Match]:
    if not destinations:
        return []

    destinations = _prefilter(employee, destinations)

    all_scores: list[dict] = []
    for i in range(0, len(destinations), _BATCH_SIZE):
        batch = destinations[i : i + _BATCH_SIZE]
        scores = _score_batch(employee, batch)
        # Pad short responses so zip stays aligned
        if len(scores) < len(batch):
            scores += [_FALLBACK] * (len(batch) - len(scores))
        all_scores.extend(scores[: len(batch)])

    matches = []
    for dest, s in zip(destinations, all_scores):
        matches.append(Match(
            employee=employee,
            destination=dest,
            score=_composite(s),
            reasoning=s.get("reasoning", ""),
            functional_skill=s.get("functional_skill"),
            seniority=s.get("seniority"),
            transition_pattern=s.get("transition_pattern"),
            stage_fit=s.get("stage_fit"),
            domain_overlap=s.get("domain_overlap"),
        ))

    matches.sort(key=lambda m: m.score, reverse=True)
    return matches[:top_n]

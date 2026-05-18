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

Score each employee-role pair on four dimensions (0-100 each):

1. functional_skill (35%): Does their core function match the role?
   Direct match = 80-100. Strong overlap with one gap = 60-79.
   Partial match = 40-59. Weak/tangential = 20-39. No overlap = 0-19.

2. seniority (25%): Is the level right? Both over AND under-qualification are penalized.
   Direct title match = 80-100. One level off = 60-79.
   Two levels off = 40-59. Three or more = 0-39.

3. stage_fit (20%): Does their company stage experience match the hiring company's stage?
   Same or adjacent stage = 80-100. One stage off = 60-79.
   Two stages off = 40-59. Fundamentally different = 0-39.

4. domain_overlap (20%): Does their industry/domain transfer?
   Same domain = 80-100. Adjacent = 60-79. Some overlap = 40-59. Major shift = 0-39.

Respond ONLY with a JSON array, one object per role, in the same order as given:
[
  {
    "functional_skill": <0-100>,
    "seniority": <0-100>,
    "stage_fit": <0-100>,
    "domain_overlap": <0-100>,
    "reasoning": "<one sentence explaining the most important factor>"
  },
  ...
]
"""

_FALLBACK = {"functional_skill": 0, "seniority": 0, "stage_fit": 0, "domain_overlap": 0, "reasoning": "Scoring unavailable"}

_PREFILTER_LIMIT = 100


def _composite(s: dict) -> float:
    return (
        0.35 * s.get("functional_skill", 0)
        + 0.25 * s.get("seniority", 0)
        + 0.20 * s.get("stage_fit", 0)
        + 0.20 * s.get("domain_overlap", 0)
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
    prompt = f"""\
Employee:
- Name: {employee.name}
- Title: {employee.title or "Unknown"}
- Company: {employee.company}
- Founder: {employee.is_founder}, Executive: {employee.is_executive}

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
            stage_fit=s.get("stage_fit"),
            domain_overlap=s.get("domain_overlap"),
        ))

    matches.sort(key=lambda m: m.score, reverse=True)
    return matches[:top_n]

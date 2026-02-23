"""
Investor Context & Email Samples for Outreach Agent
=====================================================

Loads investor profiles from profiles.yaml and annotated email samples from
docs/email_samples.md. Provides the public API consumed by the generator:

    from agents.outreach.context import get_investor_context, load_samples

    profile = get_investor_context("ashley")
    samples = load_samples("ashley", context_type="thesis_driven_deep_dive")

All parsing uses PyYAML. Samples are split on ``---`` delimiters and their
YAML metadata blocks are extracted via regex.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import yaml

logger = logging.getLogger(__name__)

# =========================================================================
# PATH CONSTANTS
# =========================================================================

_PROJECT_ROOT = Path(__file__).parent.parent.parent
DEFAULT_SAMPLES_FILE = _PROJECT_ROOT / "docs" / "email_samples.md"
DEFAULT_PROFILES_FILE = _PROJECT_ROOT / "agents" / "outreach" / "profiles.yaml"

# Max samples to include in a prompt
MAX_STYLE_SAMPLES = 3

# Regex to extract fenced YAML blocks: ```yaml ... ```
_YAML_BLOCK_RE = re.compile(r"```yaml\s*\n(.*?)```", re.DOTALL)


# =========================================================================
# DATA CLASSES
# =========================================================================

@dataclass
class InvestorProfile:
    """
    Mirrors a single entry in profiles.yaml.

    Provides format_for_prompt() to serialize the profile into a text block
    suitable for LLM prompt injection.
    """

    # Identity
    full_name: str
    role: str
    focus_areas: list[str] = field(default_factory=list)

    # Voice & style
    tone: str = ""
    intro_patterns: dict[str, str] = field(default_factory=dict)
    structural_pattern: str = ""
    sign_off_options: list[str] = field(default_factory=list)
    differentiators: str = ""

    # Portfolio & social proof
    portfolio_companies_to_reference: list[str] = field(default_factory=list)

    # Background & career history
    education: list[str] = field(default_factory=list)
    prior_career: list[str] = field(default_factory=list)
    prior_investments: list[str] = field(default_factory=list)

    # Optional fields
    location: Optional[str] = None
    firm_context_block: Optional[str] = None
    colleague_introductions: Optional[dict[str, str]] = None

    # Derived (not in YAML, set after loading)
    firm_name: str = "NEA"

    def format_for_prompt(self) -> str:
        """Serialize this profile into a text block for the LLM prompt."""
        lines: list[str] = []

        lines.append(f"Name: {self.full_name}")
        lines.append(f"Role: {self.role}")
        lines.append(f"Firm: {self.firm_name}")

        if self.focus_areas:
            lines.append(f"Focus Areas: {', '.join(self.focus_areas)}")

        if self.tone:
            lines.append(f"Tone: {self.tone.strip()}")

        if self.intro_patterns:
            lines.append("Intro Patterns:")
            for label, pattern in self.intro_patterns.items():
                lines.append(f"  {label}: {pattern.strip()}")

        if self.structural_pattern:
            lines.append(f"Structural Pattern: {self.structural_pattern.strip()}")

        if self.sign_off_options:
            lines.append(
                f"Sign-Off Options: {' | '.join(s.replace(chr(10), ' / ') for s in self.sign_off_options)}"
            )

        if self.differentiators:
            lines.append(f"Differentiators: {self.differentiators.strip()}")

        if self.portfolio_companies_to_reference:
            lines.append(
                f"Portfolio Companies: {', '.join(self.portfolio_companies_to_reference)}"
            )

        if self.education:
            lines.append(f"Education: {'; '.join(self.education)}")

        if self.prior_career:
            lines.append("Prior Career:")
            for entry in self.prior_career:
                lines.append(f"  - {entry}")

        if self.prior_investments:
            lines.append(
                f"Prior Investments (pre-NEA): {', '.join(self.prior_investments)}"
            )

        if self.location:
            lines.append(f"Location: {self.location}")

        if self.firm_context_block:
            lines.append(f"Firm Context: {self.firm_context_block.strip()}")

        if self.colleague_introductions:
            lines.append("Colleague Introductions:")
            for label, intro in self.colleague_introductions.items():
                lines.append(f"  {label}: {intro.strip()}")

        return "\n".join(lines)


@dataclass
class EmailSample:
    """
    A single annotated email sample parsed from the samples markdown file.

    Fields mirror the YAML metadata block plus the email body text.
    """

    investor: str
    recipient: str
    company: str
    context_type: str
    personalization_signals: list[str] = field(default_factory=list)
    length: str = "medium"
    body: str = ""
    exclude_from_outreach: bool = False
    human_edited: bool = False   # True for examples promoted from investor feedback


# =========================================================================
# LOADING FUNCTIONS
# =========================================================================

def load_profiles(
    file_path: str | Path | None = None,
) -> dict[str, InvestorProfile]:
    """
    Load investor profiles from a YAML file.

    Args:
        file_path: Path to profiles.yaml. Defaults to
            agents/outreach/profiles.yaml.

    Returns:
        Dict mapping lowercase investor key to InvestorProfile.
    """
    path = Path(file_path) if file_path else DEFAULT_PROFILES_FILE

    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        logger.error(f"Profiles file not found: {path}")
        return {}
    except yaml.YAMLError as e:
        logger.error(f"Failed to parse profiles YAML: {e}")
        return {}

    profiles: dict[str, InvestorProfile] = {}
    for key, data in raw.items():
        try:
            profiles[key] = InvestorProfile(
                full_name=data["full_name"],
                role=data["role"],
                focus_areas=data.get("focus_areas", []),
                tone=data.get("tone", ""),
                intro_patterns=data.get("intro_patterns", {}),
                structural_pattern=data.get("structural_pattern", ""),
                sign_off_options=data.get("sign_off_options", []),
                differentiators=data.get("differentiators", ""),
                portfolio_companies_to_reference=data.get(
                    "portfolio_companies_to_reference", []
                ),
                education=data.get("education", []),
                prior_career=data.get("prior_career", []),
                prior_investments=data.get("prior_investments", []),
                location=data.get("location"),
                firm_context_block=data.get("firm_context_block"),
                colleague_introductions=data.get("colleague_introductions"),
            )
        except KeyError as e:
            logger.warning(f"Skipping profile '{key}': missing required field {e}")

    return profiles


def load_all_samples(
    file_path: str | Path | None = None,
) -> list[EmailSample]:
    """
    Parse all annotated email samples from the markdown file.

    Splits the file on ``---`` delimiters, extracts the ```yaml``` metadata
    block from each chunk via regex, and treats the remaining text as the
    email body.

    Args:
        file_path: Path to the samples markdown file. Defaults to
            docs/email_samples.md.

    Returns:
        List of EmailSample objects. Empty list if file not found.
    """
    path = Path(file_path) if file_path else DEFAULT_SAMPLES_FILE

    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        logger.warning(f"Samples file not found: {path}")
        return []
    except OSError as e:
        logger.warning(f"Could not read samples file {path}: {e}")
        return []

    chunks = text.split("---")
    samples: list[EmailSample] = []

    for chunk in chunks:
        chunk = chunk.strip()
        if not chunk:
            continue

        # Extract YAML metadata block
        yaml_match = _YAML_BLOCK_RE.search(chunk)
        if not yaml_match:
            # No metadata — skip (likely the file header)
            continue

        try:
            metadata = yaml.safe_load(yaml_match.group(1))
        except yaml.YAMLError as e:
            logger.warning(f"Failed to parse sample YAML block: {e}")
            continue

        if not isinstance(metadata, dict):
            continue

        # Everything after the YAML block is the email body
        body = chunk[yaml_match.end():].strip()
        if not body:
            continue

        samples.append(EmailSample(
            investor=metadata.get("investor", "unknown"),
            recipient=metadata.get("recipient", "unknown"),
            company=metadata.get("company", "unknown"),
            context_type=metadata.get("context_type", "unknown"),
            personalization_signals=metadata.get("personalization_signals", []),
            length=metadata.get("length", "medium"),
            body=body,
            exclude_from_outreach=metadata.get("exclude_from_outreach", False),
        ))

    return samples


# =========================================================================
# SAMPLE SELECTION
# =========================================================================

def select_samples(
    all_samples: list[EmailSample],
    investor_key: str,
    context_type: Optional[str] = None,
    max_count: int = MAX_STYLE_SAMPLES,
) -> list[EmailSample]:
    """
    Select the best style examples for a given investor and context type.

    Filtering pipeline:
    1. Keep only samples from the target investor.
    2. Exclude samples marked exclude_from_outreach=True.
    3. Prefer samples whose context_type matches the current scenario.
    4. Fill remainder with other samples from the same investor.
    5. Sort by body length (shorter first) for token efficiency.

    Args:
        all_samples: Full list of parsed EmailSample objects.
        investor_key: Lowercase investor identifier (e.g., "ashley").
        context_type: Optional context_type string to prefer.
        max_count: Maximum number of samples to return.

    Returns:
        List of up to max_count EmailSample objects.
    """
    # Step 1 + 2: filter to this investor, exclude internal
    eligible = [
        s for s in all_samples
        if s.investor == investor_key and not s.exclude_from_outreach
    ]

    if not eligible:
        return []

    if context_type:
        # Step 3: matching context_type first
        matching = [s for s in eligible if s.context_type == context_type]
        non_matching = [s for s in eligible if s.context_type != context_type]

        # Sort each group: human-edited first, then by body length (shorter first)
        matching.sort(key=lambda s: (not s.human_edited, len(s.body)))
        non_matching.sort(key=lambda s: (not s.human_edited, len(s.body)))

        # Step 4: fill remainder
        selected = matching[:max_count]
        remaining_slots = max_count - len(selected)
        if remaining_slots > 0:
            selected.extend(non_matching[:remaining_slots])
    else:
        # No context_type preference — human-edited first, then shortest
        eligible.sort(key=lambda s: (not s.human_edited, len(s.body)))
        selected = eligible[:max_count]

    return selected


# =========================================================================
# PUBLIC API
# =========================================================================

# Module-level caches
_profiles_cache: Optional[dict[str, InvestorProfile]] = None
_samples_cache: Optional[list[EmailSample]] = None


def get_investor_context(
    investor_key: str,
    profiles_file: str | Path | None = None,
) -> InvestorProfile:
    """
    Load and return an InvestorProfile by key.

    Caches profiles after first load. Falls back to a minimal default profile
    if the key is not found.

    Args:
        investor_key: Lowercase investor identifier (e.g., "ashley").
        profiles_file: Optional override path to profiles.yaml.

    Returns:
        InvestorProfile for the requested investor.
    """
    global _profiles_cache

    if _profiles_cache is None or profiles_file is not None:
        _profiles_cache = load_profiles(profiles_file)

    if investor_key in _profiles_cache:
        return _profiles_cache[investor_key]

    logger.warning(
        f"Investor '{investor_key}' not found in profiles. "
        f"Available: {list(_profiles_cache.keys())}. Using fallback."
    )
    return InvestorProfile(
        full_name=investor_key.title(),
        role="Investor",
    )


def load_samples(
    investor_key: str,
    context_type: Optional[str] = None,
    samples_file: str | Path | None = None,
    max_count: int = MAX_STYLE_SAMPLES,
) -> list[EmailSample]:
    """
    Load and select email samples for a given investor and context type.

    Caches the full sample list after first load.

    Args:
        investor_key: Lowercase investor identifier (e.g., "ashley").
        context_type: Optional context_type string to prefer in selection.
        samples_file: Optional override path to samples markdown file.
        max_count: Maximum number of samples to return.

    Returns:
        List of selected EmailSample objects.
    """
    global _samples_cache

    if _samples_cache is None or samples_file is not None:
        _samples_cache = load_all_samples(samples_file)

    return select_samples(
        all_samples=_samples_cache,
        investor_key=investor_key,
        context_type=context_type,
        max_count=max_count,
    )

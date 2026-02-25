"""
Swarm API Client
=================

REST client for The Swarm profile intelligence API.

Endpoints implemented:
- POST /v2/profiles/search - Search profiles by LinkedIn slug or other criteria
- POST /v2/profiles/fetch - Fetch detailed profile data by IDs

Reference: https://docs.theswarm.com/

Usage:
    from core.clients import SwarmClient

    client = SwarmClient()
    profile = client.get_profile_by_linkedin("johndoe")
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import os
import time
import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Optional, TYPE_CHECKING
from urllib.parse import urlparse


def _run_async(coro):
    """
    Run an async coroutine from sync code, handling nested event loops.

    Works both in CLI (no event loop) and FastAPI (existing event loop).
    """
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        # No running loop - safe to use asyncio.run()
        return asyncio.run(coro)

    # There's a running loop (e.g., FastAPI) - run in a thread pool
    with concurrent.futures.ThreadPoolExecutor() as pool:
        future = pool.submit(asyncio.run, coro)
        return future.result()

import requests

# Optional async support - aiohttp is only needed for batch async methods
try:
    import aiohttp
    AIOHTTP_AVAILABLE = True
except ImportError:
    aiohttp = None  # type: ignore
    AIOHTTP_AVAILABLE = False

logger = logging.getLogger(__name__)

# =============================================================================
# CONFIGURATION
# =============================================================================

DEFAULT_BASE_URL = "https://bee.theswarm.com/v2"
DEFAULT_TIMEOUT = 30  # seconds
RATE_LIMIT_RPS = 5  # requests per second (conservative)
BATCH_SIZE = 50  # Maximum LinkedIn slugs per batch request


# =============================================================================
# DATA MODELS
# =============================================================================

@dataclass
class SwarmExperience:
    """Work experience from Swarm profile."""
    company_name: str
    title: str
    is_current: bool = False
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    description: Optional[str] = None
    location: Optional[str] = None
    company_website: Optional[str] = None
    company_industry: Optional[str] = None
    seniority: list[str] = field(default_factory=list)

    @classmethod
    def from_api_response(cls, data: dict) -> "SwarmExperience":
        """Parse experience from Swarm API response."""
        company = data.get("company", {}) or {}
        location_list = data.get("location", []) or []
        location = location_list[0] if location_list else None

        # Handle title - can be string or dict with 'name' key
        title_data = data.get("title", "")
        if isinstance(title_data, dict):
            title = title_data.get("name", "")
        else:
            title = title_data or ""

        return cls(
            company_name=company.get("name") or company.get("canonical_name") or "",
            title=title,
            is_current=data.get("is_current", False) or data.get("is_primary", False),
            start_date=data.get("start_date"),
            end_date=data.get("end_date"),
            description=data.get("description"),
            location=location,
            company_website=company.get("website"),
            company_industry=company.get("industry"),
            seniority=data.get("seniority", []) or [],
        )


@dataclass
class SwarmEducation:
    """Education from Swarm profile."""
    school_name: str
    degrees: list[str] = field(default_factory=list)
    majors: list[str] = field(default_factory=list)
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    location: Optional[str] = None

    @classmethod
    def from_api_response(cls, data: dict) -> "SwarmEducation":
        """Parse education from Swarm API response."""
        school = data.get("school", {}) or {}
        school_location = school.get("location", {}) or {}

        return cls(
            school_name=school.get("name", ""),
            degrees=data.get("degrees", []) or [],
            majors=data.get("majors", []) or [],
            start_date=data.get("start_date"),
            end_date=data.get("end_date"),
            location=school_location.get("name"),
        )


@dataclass
class SwarmProfile:
    """Parsed profile data from Swarm API."""
    id: str
    full_name: str
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    headline: Optional[str] = None
    about: Optional[str] = None
    current_title: Optional[str] = None
    current_company: Optional[str] = None
    current_location: Optional[str] = None
    linkedin_url: Optional[str] = None
    linkedin_slug: Optional[str] = None
    work_email: Optional[str] = None
    image_url: Optional[str] = None

    # Detailed data
    experience: list[SwarmExperience] = field(default_factory=list)
    education: list[SwarmEducation] = field(default_factory=list)
    skills: list[str] = field(default_factory=list)
    smart_tags: list[str] = field(default_factory=list)

    # Social media / sources
    social_media: list[dict] = field(default_factory=list)

    # Investor data (if applicable)
    investor_data: Optional[dict] = None

    # Raw data
    raw_data: dict = field(default_factory=dict)

    # Metadata
    fetched_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())

    @classmethod
    def from_api_response(cls, data: dict) -> "SwarmProfile":
        """Parse Swarm API response into SwarmProfile."""
        profile_info = data.get("profile_info", {}) or {}

        # Extract LinkedIn slug from social_media or linkedin_url
        linkedin_slug = None
        linkedin_url = profile_info.get("linkedin_url")

        # Check linkedin_usernames array
        linkedin_usernames = profile_info.get("linkedin_usernames", []) or []
        if linkedin_usernames:
            linkedin_slug = linkedin_usernames[0]
        elif linkedin_url:
            # Extract slug from URL
            if "linkedin.com/in/" in linkedin_url:
                linkedin_slug = linkedin_url.split("/in/")[-1].rstrip("/")

        # Parse experience
        experience = []
        for exp in profile_info.get("experience", []) or []:
            try:
                experience.append(SwarmExperience.from_api_response(exp))
            except Exception as e:
                logger.warning(f"Failed to parse experience: {e}")

        # Parse education
        education = []
        for edu in profile_info.get("education", []) or []:
            try:
                education.append(SwarmEducation.from_api_response(edu))
            except Exception as e:
                logger.warning(f"Failed to parse education: {e}")

        return cls(
            id=data.get("id") or profile_info.get("id") or "",
            full_name=profile_info.get("full_name") or "",
            first_name=profile_info.get("first_name"),
            last_name=profile_info.get("last_name"),
            headline=profile_info.get("headline"),
            about=profile_info.get("about"),
            current_title=profile_info.get("current_title"),
            current_company=profile_info.get("current_company_name"),
            current_location=profile_info.get("current_location"),
            linkedin_url=linkedin_url,
            linkedin_slug=linkedin_slug,
            work_email=profile_info.get("work_email"),
            image_url=profile_info.get("image_url"),
            experience=experience,
            education=education,
            skills=profile_info.get("skills", []) or [],
            smart_tags=profile_info.get("smart_tags", []) or [],
            social_media=profile_info.get("social_media", []) or [],
            investor_data=profile_info.get("investor_data"),
            raw_data=data,
        )

    def format_background(self) -> str:
        """
        Format profile data into a readable background summary.

        Focuses on PRIOR experience, education, and notable achievements.
        Skips current role since it's already shown in the founder's title.

        Returns:
            Formatted background text suitable for VC meeting prep.
        """
        lines = []

        # Smart tags first (most VC-relevant signals)
        notable_tags = [tag for tag in self.smart_tags if tag in (
            "priorBackedFounder", "serialEntrepreneur", "techFounder",
            "exitedFounder", "unicornAlum", "fangAlum", "yc", "USImmigrant",
            "forbesUnder30", "thielFellow",
        )]
        if notable_tags:
            formatted_tags = [tag.replace("priorBackedFounder", "Previously Backed Founder")
                               .replace("serialEntrepreneur", "Serial Entrepreneur")
                               .replace("techFounder", "Technical Founder")
                               .replace("exitedFounder", "Exited Founder")
                               .replace("unicornAlum", "Unicorn Alumni")
                               .replace("fangAlum", "FAANG Alumni")
                               .replace("yc", "Y Combinator")
                               .replace("USImmigrant", "US Immigrant")
                               .replace("forbesUnder30", "Forbes 30 Under 30")
                               .replace("thielFellow", "Thiel Fellow")
                             for tag in notable_tags]
            lines.append(f"Notable: {', '.join(formatted_tags)}")
            lines.append("")

        # Prior experience (skip current role - it's redundant)
        prior_roles = [exp for exp in self.experience if not exp.is_current]
        if prior_roles:
            lines.append("Prior experience:")
            for exp in prior_roles[:4]:
                date_range = ""
                if exp.start_date:
                    start_year = exp.start_date[:4] if exp.start_date else ""
                    end_year = exp.end_date[:4] if exp.end_date else ""
                    if start_year and end_year:
                        date_range = f" ({start_year}-{end_year})"
                    elif start_year:
                        date_range = f" ({start_year})"

                role_line = f"- {exp.title} at {exp.company_name}{date_range}"
                lines.append(role_line)

                # Add description if meaningful and not too long
                if exp.description and len(exp.description) > 30:
                    desc = exp.description[:150]
                    if len(exp.description) > 150:
                        desc = desc.rsplit(" ", 1)[0] + "..."
                    lines.append(f"  {desc}")
            lines.append("")

        # Education
        if self.education:
            lines.append("Education:")
            for edu in self.education[:2]:
                degree_str = ", ".join(edu.degrees) if edu.degrees else ""
                major_str = " in " + ", ".join(edu.majors) if edu.majors else ""
                if degree_str and edu.school_name:
                    lines.append(f"- {degree_str}{major_str} from {edu.school_name}")
                elif edu.school_name:
                    lines.append(f"- {edu.school_name}")
            lines.append("")

        # About/bio section (at the end, truncated)
        if self.about:
            about_text = self.about.strip()
            # Truncate long bios
            if len(about_text) > 200:
                about_text = about_text[:200].rsplit(" ", 1)[0] + "..."
            lines.append(f"Bio: {about_text}")

        # Remove trailing empty lines
        while lines and lines[-1] == "":
            lines.pop()

        return "\n".join(lines).strip()

    def format_background_verbose(self) -> str:
        """
        Format profile data with full details (for debugging/deep dive).
        """
        lines = []

        if self.about:
            lines.append(self.about.strip())
            lines.append("")

        if self.experience:
            lines.append("Full career history:")
            for exp in self.experience:
                date_range = ""
                if exp.start_date:
                    start_year = exp.start_date[:4] if exp.start_date else ""
                    end_year = exp.end_date[:4] if exp.end_date else "Present"
                    date_range = f" ({start_year}-{end_year})"
                lines.append(f"- {exp.title} at {exp.company_name}{date_range}")
                if exp.description:
                    lines.append(f"  {exp.description}")
            lines.append("")

        if self.education:
            lines.append("Education:")
            for edu in self.education:
                degree_str = ", ".join(edu.degrees) if edu.degrees else ""
                major_str = " in " + ", ".join(edu.majors) if edu.majors else ""
                lines.append(f"- {degree_str}{major_str} from {edu.school_name}")
            lines.append("")

        if self.skills:
            lines.append(f"Skills: {', '.join(self.skills)}")

        return "\n".join(lines).strip()

    def get_sources(self) -> list[dict]:
        """
        Extract source references from profile.

        Returns:
            List of source dicts with network, url, and id.
        """
        sources = []

        for sm in self.social_media:
            network = sm.get("network", "").lower()
            url = sm.get("url", "")

            # Skip if no useful data
            if not network or not url:
                continue

            # Normalize URL
            if url and not url.startswith("http"):
                url = "https://" + url

            sources.append({
                "network": network,
                "url": url,
                "id": sm.get("id"),
            })

        return sources

    def to_founder_profile(self) -> "FounderProfile":
        """Convert SwarmProfile to unified FounderProfile model."""
        return FounderProfile.from_swarm_profile(self)


# =============================================================================
# UNIFIED FOUNDER PROFILE MODEL
# =============================================================================

@dataclass
class FounderExperience:
    """
    Unified work experience entry.

    Bridges the rich experience data from Swarm with the database model.
    """
    company_name: str
    title: str
    is_current: bool = False
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    num_years: Optional[float] = None
    description: Optional[str] = None
    location: Optional[str] = None
    company_website: Optional[str] = None
    company_industry: Optional[str] = None
    company_linkedin: Optional[str] = None
    seniority: list[str] = field(default_factory=list)

    @classmethod
    def from_swarm_experience(cls, exp: SwarmExperience) -> "FounderExperience":
        """Convert from SwarmExperience."""
        num_years = None
        if exp.start_date:
            try:
                start_dt = datetime.strptime(exp.start_date, "%Y-%m-%d")
                if exp.end_date:
                    end_dt = datetime.strptime(exp.end_date, "%Y-%m-%d")
                else:
                    end_dt = datetime.utcnow()
                num_years = max(0.0, (end_dt - start_dt).days / 365.25)
            except ValueError:
                pass

        return cls(
            company_name=exp.company_name,
            title=exp.title,
            is_current=exp.is_current,
            start_date=exp.start_date,
            end_date=exp.end_date,
            num_years=num_years,
            description=exp.description,
            location=exp.location,
            company_website=exp.company_website,
            company_industry=exp.company_industry,
            seniority=exp.seniority,
        )

    def to_dict(self) -> dict:
        """Convert to dictionary."""
        return {
            "company_name": self.company_name,
            "title": self.title,
            "is_current": self.is_current,
            "start_date": self.start_date,
            "end_date": self.end_date,
            "num_years": self.num_years,
            "description": self.description,
            "location": self.location,
            "company_website": self.company_website,
            "company_industry": self.company_industry,
            "company_linkedin": self.company_linkedin,
            "seniority": self.seniority,
        }


@dataclass
class FounderEducation:
    """
    Unified education entry.

    Bridges education data from Swarm with potential tier mapping.
    """
    school_name: str
    degrees: list[str] = field(default_factory=list)
    majors: list[str] = field(default_factory=list)
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    location: Optional[str] = None
    education_years: Optional[float] = None

    @classmethod
    def from_swarm_education(cls, edu: SwarmEducation) -> "FounderEducation":
        """Convert from SwarmEducation."""
        education_years = None
        if edu.start_date and edu.end_date:
            try:
                start_dt = datetime.strptime(edu.start_date, "%Y-%m-%d")
                end_dt = datetime.strptime(edu.end_date, "%Y-%m-%d")
                education_years = max(0.0, (end_dt - start_dt).days / 365.25)
            except ValueError:
                pass

        return cls(
            school_name=edu.school_name,
            degrees=edu.degrees,
            majors=edu.majors,
            start_date=edu.start_date,
            end_date=edu.end_date,
            location=edu.location,
            education_years=education_years,
        )

    def to_dict(self) -> dict:
        """Convert to dictionary."""
        return {
            "school_name": self.school_name,
            "degrees": self.degrees,
            "majors": self.majors,
            "start_date": self.start_date,
            "end_date": self.end_date,
            "location": self.location,
            "education_years": self.education_years,
        }


@dataclass
class FounderProfile:
    """
    Unified founder profile model.

    This model bridges:
    - Rich Swarm profile data (experience, education, social)
    - Database Founder model (company_id, role_title, background)
    - Harmonic person data

    Used for:
    - Batch profile enrichment
    - Meeting briefing generation
    - Founder analysis workflows

    Note: This model intentionally excludes scores. Scoring logic
    should be implemented separately in analysis/evaluation code.
    """
    # Identity
    id: str
    name: str
    first_name: Optional[str] = None
    last_name: Optional[str] = None

    # Current position
    current_title: Optional[str] = None
    current_company: Optional[str] = None
    headline: Optional[str] = None

    # Contact & social
    linkedin_url: Optional[str] = None
    linkedin_slug: Optional[str] = None
    work_email: Optional[str] = None
    personal_emails: list[str] = field(default_factory=list)
    twitter_url: Optional[str] = None
    image_url: Optional[str] = None
    current_location: Optional[str] = None

    # Professional history
    experience: list[FounderExperience] = field(default_factory=list)
    education: list[FounderEducation] = field(default_factory=list)

    # Skills & tags
    skills: list[str] = field(default_factory=list)
    smart_tags: list[str] = field(default_factory=list)

    # Bio
    about: Optional[str] = None

    # Company context (set when used in company context)
    company_id: Optional[str] = None
    startup_company: Optional[str] = None

    # Metadata
    source: str = "swarm"  # "swarm", "harmonic", "manual"
    fetched_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    raw_data: dict = field(default_factory=dict)

    @classmethod
    def from_swarm_profile(cls, profile: SwarmProfile) -> "FounderProfile":
        """Create from SwarmProfile."""
        # Convert experience
        experience = [
            FounderExperience.from_swarm_experience(exp)
            for exp in profile.experience
        ]

        # Convert education
        education = [
            FounderEducation.from_swarm_education(edu)
            for edu in profile.education
        ]

        # Extract Twitter URL from social media
        twitter_url = None
        personal_emails = []
        for sm in profile.social_media:
            if sm.get("network", "").lower() == "twitter":
                twitter_url = sm.get("url")

        return cls(
            id=profile.id,
            name=profile.full_name,
            first_name=profile.first_name,
            last_name=profile.last_name,
            current_title=profile.current_title,
            current_company=profile.current_company,
            headline=profile.headline,
            linkedin_url=profile.linkedin_url,
            linkedin_slug=profile.linkedin_slug,
            work_email=profile.work_email,
            twitter_url=twitter_url,
            image_url=profile.image_url,
            current_location=profile.current_location,
            experience=experience,
            education=education,
            skills=profile.skills,
            smart_tags=profile.smart_tags,
            about=profile.about,
            source="swarm",
            fetched_at=profile.fetched_at,
            raw_data=profile.raw_data,
        )

    @classmethod
    def from_api_response(cls, data: dict) -> "FounderProfile":
        """
        Create directly from Swarm API response.

        This is the batch-friendly constructor that doesn't require
        intermediate SwarmProfile creation.
        """
        profile = SwarmProfile.from_api_response(data)
        return cls.from_swarm_profile(profile)

    def get_prior_experience(self, exclude_company: Optional[str] = None) -> list[FounderExperience]:
        """
        Get prior (non-current) experience.

        Args:
            exclude_company: Company name to exclude (e.g., current startup)
        """
        prior = [exp for exp in self.experience if not exp.is_current]
        if exclude_company:
            exclude_lower = exclude_company.lower().strip()
            prior = [
                exp for exp in prior
                if exp.company_name.lower().strip() != exclude_lower
            ]
        return prior

    def get_total_experience_years(self, exclude_company: Optional[str] = None) -> float:
        """Calculate total years of prior experience."""
        prior = self.get_prior_experience(exclude_company)
        return sum(exp.num_years or 0 for exp in prior)

    def format_background(self) -> str:
        """
        Format profile data into a readable background summary.

        Delegates to SwarmProfile.format_background() logic but works
        directly with FounderProfile data.
        """
        lines = []

        # Smart tags first (most VC-relevant signals)
        notable_tags = [tag for tag in self.smart_tags if tag in (
            "priorBackedFounder", "serialEntrepreneur", "techFounder",
            "exitedFounder", "unicornAlum", "fangAlum", "yc", "USImmigrant",
            "forbesUnder30", "thielFellow",
        )]
        if notable_tags:
            formatted_tags = [tag.replace("priorBackedFounder", "Previously Backed Founder")
                               .replace("serialEntrepreneur", "Serial Entrepreneur")
                               .replace("techFounder", "Technical Founder")
                               .replace("exitedFounder", "Exited Founder")
                               .replace("unicornAlum", "Unicorn Alumni")
                               .replace("fangAlum", "FAANG Alumni")
                               .replace("yc", "Y Combinator")
                               .replace("USImmigrant", "US Immigrant")
                               .replace("forbesUnder30", "Forbes 30 Under 30")
                               .replace("thielFellow", "Thiel Fellow")
                             for tag in notable_tags]
            lines.append(f"Notable: {', '.join(formatted_tags)}")
            lines.append("")

        # Prior experience (skip current role)
        prior_roles = self.get_prior_experience(self.startup_company)
        if prior_roles:
            lines.append("Prior experience:")
            for exp in prior_roles[:4]:
                date_range = ""
                if exp.start_date:
                    start_year = exp.start_date[:4] if exp.start_date else ""
                    end_year = exp.end_date[:4] if exp.end_date else ""
                    if start_year and end_year:
                        date_range = f" ({start_year}-{end_year})"
                    elif start_year:
                        date_range = f" ({start_year})"

                role_line = f"- {exp.title} at {exp.company_name}{date_range}"
                lines.append(role_line)

                if exp.description and len(exp.description) > 30:
                    desc = exp.description[:150]
                    if len(exp.description) > 150:
                        desc = desc.rsplit(" ", 1)[0] + "..."
                    lines.append(f"  {desc}")
            lines.append("")

        # Education
        if self.education:
            lines.append("Education:")
            for edu in self.education[:2]:
                degree_str = ", ".join(edu.degrees) if edu.degrees else ""
                major_str = " in " + ", ".join(edu.majors) if edu.majors else ""
                if degree_str and edu.school_name:
                    lines.append(f"- {degree_str}{major_str} from {edu.school_name}")
                elif edu.school_name:
                    lines.append(f"- {edu.school_name}")
            lines.append("")

        # About/bio section
        if self.about:
            about_text = self.about.strip()
            if len(about_text) > 200:
                about_text = about_text[:200].rsplit(" ", 1)[0] + "..."
            lines.append(f"Bio: {about_text}")

        while lines and lines[-1] == "":
            lines.pop()

        return "\n".join(lines).strip()

    def to_db_founder(self, company_id: str) -> dict:
        """
        Convert to database Founder dict for storage.

        Args:
            company_id: The company_id to associate this founder with
        """
        return {
            "company_id": company_id,
            "name": self.name,
            "role_title": self.current_title,
            "linkedin_url": self.linkedin_url,
            "background": self.format_background(),
            "observed_at": self.fetched_at,
            "source": self.source,
        }

    def to_dict(self) -> dict:
        """Convert to full dictionary representation."""
        return {
            "id": self.id,
            "name": self.name,
            "first_name": self.first_name,
            "last_name": self.last_name,
            "current_title": self.current_title,
            "current_company": self.current_company,
            "headline": self.headline,
            "linkedin_url": self.linkedin_url,
            "linkedin_slug": self.linkedin_slug,
            "work_email": self.work_email,
            "personal_emails": self.personal_emails,
            "twitter_url": self.twitter_url,
            "image_url": self.image_url,
            "current_location": self.current_location,
            "experience": [exp.to_dict() for exp in self.experience],
            "education": [edu.to_dict() for edu in self.education],
            "skills": self.skills,
            "smart_tags": self.smart_tags,
            "about": self.about,
            "company_id": self.company_id,
            "startup_company": self.startup_company,
            "source": self.source,
            "fetched_at": self.fetched_at,
        }


# =============================================================================
# SWARM API CLIENT
# =============================================================================

class SwarmAPIError(Exception):
    """Custom exception for Swarm API errors."""
    def __init__(self, message: str, status_code: Optional[int] = None, response: Optional[dict] = None):
        super().__init__(message)
        self.status_code = status_code
        self.response = response


class SwarmClient:
    """
    REST client for The Swarm API.

    Usage:
        client = SwarmClient(api_key="your_key")

        # Get profile by LinkedIn URL or slug
        profile = client.get_profile_by_linkedin("johndoe")

        # Get formatted background
        background = profile.format_background()
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: str = DEFAULT_BASE_URL,
        timeout: int = DEFAULT_TIMEOUT,
    ):
        """
        Initialize Swarm API client.

        Args:
            api_key: Swarm API key. Falls back to SWARM_API_KEY env var.
            base_url: API base URL (default: https://bee.theswarm.com/v2)
            timeout: Request timeout in seconds
        """
        self.api_key = api_key or os.getenv("SWARM_API_KEY")
        if not self.api_key:
            raise ValueError(
                "Swarm API key required. Set SWARM_API_KEY environment variable "
                "or pass api_key parameter."
            )

        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self._last_request_time = 0.0

        self.session = requests.Session()
        self.session.headers.update({
            "x-api-key": self.api_key,
            "Content-Type": "application/json",
            "Accept": "application/json",
        })

    def _rate_limit(self):
        """Enforce rate limiting between requests."""
        elapsed = time.time() - self._last_request_time
        min_interval = 1.0 / RATE_LIMIT_RPS
        if elapsed < min_interval:
            time.sleep(min_interval - elapsed)
        self._last_request_time = time.time()

    def _request(
        self,
        method: str,
        endpoint: str,
        json_data: Optional[dict] = None,
    ) -> dict:
        """Make an API request with error handling."""
        self._rate_limit()

        url = f"{self.base_url}/{endpoint.lstrip('/')}"

        try:
            response = self.session.request(
                method=method,
                url=url,
                json=json_data,
                timeout=self.timeout,
            )

            logger.debug(f"Swarm API {method} {url} -> {response.status_code}")

            if response.status_code == 401:
                raise SwarmAPIError("Invalid API key", status_code=401)
            elif response.status_code == 404:
                raise SwarmAPIError("Resource not found", status_code=404)
            elif response.status_code == 429:
                raise SwarmAPIError("Rate limit exceeded", status_code=429)
            elif response.status_code >= 400:
                error_data = response.json() if response.content else {}
                raise SwarmAPIError(
                    f"API error: {error_data.get('message', response.text)}",
                    status_code=response.status_code,
                    response=error_data,
                )

            return response.json() if response.content else {}

        except requests.exceptions.Timeout:
            raise SwarmAPIError(f"Request timed out after {self.timeout}s")
        except requests.exceptions.ConnectionError as e:
            raise SwarmAPIError(f"Connection error: {e}")

    # =========================================================================
    # PROFILE ENDPOINTS
    # =========================================================================

    def _extract_linkedin_slug(self, linkedin_input: str) -> str:
        """
        Extract LinkedIn slug from URL or return as-is if already a slug.

        Args:
            linkedin_input: LinkedIn URL or slug

        Returns:
            LinkedIn slug (username)
        """
        linkedin_input = linkedin_input.strip()

        # If it's a full URL, extract the slug
        if "linkedin.com" in linkedin_input:
            # Handle various URL formats
            # https://www.linkedin.com/in/johndoe
            # https://linkedin.com/in/johndoe/
            # linkedin.com/in/johndoe
            if "/in/" in linkedin_input:
                slug = linkedin_input.split("/in/")[-1].rstrip("/").split("?")[0]
                return slug

        # Already a slug
        return linkedin_input

    def search_profiles(
        self,
        query: dict,
        limit: int = 10,
        in_network_only: bool = False,
    ) -> list[str]:
        """
        Search profiles using OpenSearch DSL query.

        Args:
            query: OpenSearch DSL query dict
            limit: Maximum results to return
            in_network_only: Only return profiles in your network

        Returns:
            List of profile IDs matching the query
        """
        payload = {
            "query": query,
            "limit": limit,
        }
        if in_network_only:
            payload["inNetworkOnly"] = True

        try:
            data = self._request("POST", "/profiles/search", json_data=payload)

            # Response is a list of profile IDs or objects
            if isinstance(data, list):
                return [item if isinstance(item, str) else item.get("id") for item in data]
            elif isinstance(data, dict):
                # Handle paginated response
                return data.get("results", []) or data.get("ids", [])
            return []
        except SwarmAPIError as e:
            logger.error(f"Search failed: {e}")
            return []

    def fetch_profiles(self, profile_ids: list[str]) -> list[SwarmProfile]:
        """
        Fetch detailed profile data for multiple profile IDs.

        Args:
            profile_ids: List of Swarm profile IDs

        Returns:
            List of SwarmProfile objects
        """
        if not profile_ids:
            return []

        # Fetch endpoint accepts up to 1000 profiles
        payload = {"ids": profile_ids[:1000]}

        try:
            data = self._request("POST", "/profiles/fetch", json_data=payload)

            profiles = []
            results = data if isinstance(data, list) else data.get("results", [])

            for item in results:
                try:
                    profiles.append(SwarmProfile.from_api_response(item))
                except Exception as e:
                    logger.warning(f"Failed to parse profile: {e}")

            return profiles
        except SwarmAPIError as e:
            logger.error(f"Fetch failed: {e}")
            return []

    def get_profile_by_linkedin(self, linkedin_input: str) -> Optional[SwarmProfile]:
        """
        Get profile by LinkedIn URL or slug.

        This is the main method for founder background enrichment.

        Args:
            linkedin_input: LinkedIn URL (e.g., "https://linkedin.com/in/johndoe")
                           or slug (e.g., "johndoe")

        Returns:
            SwarmProfile if found, None otherwise
        """
        slug = self._extract_linkedin_slug(linkedin_input)

        if not slug:
            logger.warning(f"Could not extract LinkedIn slug from: {linkedin_input}")
            return None

        # Search for profile by LinkedIn username
        query = {
            "term": {
                "profile_info.linkedin_usernames": {
                    "value": slug.lower()
                }
            }
        }

        profile_ids = self.search_profiles(query, limit=1)

        if not profile_ids:
            logger.info(f"No profile found for LinkedIn slug: {slug}")
            return None

        profiles = self.fetch_profiles(profile_ids[:1])

        if profiles:
            return profiles[0]

        return None

    def search_by_name_and_company(
        self,
        name: str,
        company_name: Optional[str] = None,
    ) -> Optional[SwarmProfile]:
        """
        Search for a profile by name and optionally current company.

        Fallback method when LinkedIn URL is not available.

        Args:
            name: Full name of the person
            company_name: Current company name (optional but recommended)

        Returns:
            SwarmProfile if found, None otherwise
        """
        must_conditions = [
            {
                "match": {
                    "profile_info.full_name": {
                        "query": name,
                        "operator": "AND"
                    }
                }
            }
        ]

        if company_name:
            must_conditions.append({
                "match": {
                    "profile_info.current_company_name": {
                        "query": company_name
                    }
                }
            })

        query = {
            "bool": {
                "must": must_conditions
            }
        }

        profile_ids = self.search_profiles(query, limit=1)

        if not profile_ids:
            return None

        profiles = self.fetch_profiles(profile_ids[:1])

        if profiles:
            return profiles[0]

        return None

    # =========================================================================
    # BATCH ASYNC METHODS
    # =========================================================================

    async def _async_request(
        self,
        session: "aiohttp.ClientSession",
        method: str,
        endpoint: str,
        json_data: Optional[dict] = None,
    ) -> dict:
        """Make an async API request with error handling."""
        if not AIOHTTP_AVAILABLE:
            raise ImportError(
                "aiohttp is required for async methods. "
                "Install with: pip install aiohttp"
            )
        url = f"{self.base_url}/{endpoint.lstrip('/')}"
        headers = {
            "x-api-key": self.api_key,
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

        try:
            async with session.request(
                method=method,
                url=url,
                json=json_data,
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=self.timeout),
            ) as response:
                logger.debug(f"Swarm API {method} {url} -> {response.status}")

                if response.status == 401:
                    raise SwarmAPIError("Invalid API key", status_code=401)
                elif response.status == 404:
                    raise SwarmAPIError("Resource not found", status_code=404)
                elif response.status == 429:
                    raise SwarmAPIError("Rate limit exceeded", status_code=429)
                elif response.status >= 400:
                    text = await response.text()
                    raise SwarmAPIError(
                        f"API error: {text}",
                        status_code=response.status,
                    )

                return await response.json() if response.content_length else {}

        except asyncio.TimeoutError:
            raise SwarmAPIError(f"Request timed out after {self.timeout}s")
        except aiohttp.ClientError as e:
            raise SwarmAPIError(f"Connection error: {e}")

    async def fetch_profiles_by_linkedin_batch_async(
        self,
        linkedin_inputs: list[str],
        session: Optional["aiohttp.ClientSession"] = None,
    ) -> list["FounderProfile"]:
        """
        Fetch multiple profiles by LinkedIn URLs/slugs in a single batch.

        This is the most efficient way to enrich multiple founders at once.
        Reduces API calls from N to 2 (1 search + 1 fetch).

        Args:
            linkedin_inputs: List of LinkedIn URLs or slugs
            session: Optional aiohttp session (creates one if not provided)

        Returns:
            List of FounderProfile objects for found profiles

        Example:
            async with aiohttp.ClientSession() as session:
                profiles = await client.fetch_profiles_by_linkedin_batch_async(
                    ["johndoe", "janedoe", "https://linkedin.com/in/bobsmith"],
                    session=session
                )
        """
        if not AIOHTTP_AVAILABLE:
            raise ImportError(
                "aiohttp is required for async batch methods. "
                "Install with: pip install aiohttp"
            )

        if not linkedin_inputs:
            return []

        # Extract slugs from URLs
        slugs = []
        slug_to_input = {}  # Map slug back to original input for debugging
        for input_val in linkedin_inputs:
            slug = self._extract_linkedin_slug(input_val)
            if slug:
                slugs.append(slug.lower())
                slug_to_input[slug.lower()] = input_val

        if not slugs:
            logger.warning("No valid LinkedIn slugs found in input")
            return []

        logger.info(f"Batch fetching {len(slugs)} LinkedIn profiles")

        # Create session if not provided
        own_session = session is None
        if own_session:
            session = aiohttp.ClientSession()

        try:
            profiles = []

            # Process in batches to avoid API limits
            for i in range(0, len(slugs), BATCH_SIZE):
                batch_slugs = slugs[i:i + BATCH_SIZE]

                # Search for all profiles in batch
                query = {
                    "terms": {
                        "profile_info.linkedin_usernames": batch_slugs
                    }
                }

                search_payload = {
                    "query": query,
                    "limit": len(batch_slugs),
                }

                try:
                    search_data = await self._async_request(
                        session, "POST", "/profiles/search", json_data=search_payload
                    )

                    # Extract profile IDs from search results
                    if isinstance(search_data, list):
                        profile_ids = [
                            item if isinstance(item, str) else item.get("id")
                            for item in search_data
                        ]
                    elif isinstance(search_data, dict):
                        profile_ids = search_data.get("results", []) or search_data.get("ids", [])
                    else:
                        profile_ids = []

                    if not profile_ids:
                        logger.info(f"No profiles found for batch {i // BATCH_SIZE + 1}")
                        continue

                    # Fetch full profile data
                    fetch_payload = {"ids": profile_ids[:1000]}
                    fetch_data = await self._async_request(
                        session, "POST", "/profiles/fetch", json_data=fetch_payload
                    )

                    results = fetch_data if isinstance(fetch_data, list) else fetch_data.get("results", [])

                    for item in results:
                        try:
                            founder_profile = FounderProfile.from_api_response(item)
                            profiles.append(founder_profile)
                        except Exception as e:
                            logger.warning(f"Failed to parse profile: {e}")

                    logger.info(f"Batch {i // BATCH_SIZE + 1}: found {len(results)} profiles")

                    # Rate limit between batches
                    if i + BATCH_SIZE < len(slugs):
                        await asyncio.sleep(0.5)

                except SwarmAPIError as e:
                    logger.error(f"Batch search failed: {e}")
                    continue

            return profiles

        finally:
            if own_session and session:
                await session.close()

    async def fetch_company_founders_async(
        self,
        linkedin_urls: list[str],
        company_name: Optional[str] = None,
        session: Optional["aiohttp.ClientSession"] = None,
    ) -> list["FounderProfile"]:
        """
        Fetch all founder profiles for a company in one batch.

        This is the recommended method for enriching founders during
        meeting briefing preparation.

        Args:
            linkedin_urls: List of founder LinkedIn URLs
            company_name: Company name (used to set startup_company context)
            session: Optional aiohttp session

        Returns:
            List of FounderProfile objects with startup_company set

        Example:
            founders = await client.fetch_company_founders_async(
                ["https://linkedin.com/in/founder1", "https://linkedin.com/in/founder2"],
                company_name="Stripe"
            )
            for founder in founders:
                print(founder.format_background())
        """
        profiles = await self.fetch_profiles_by_linkedin_batch_async(
            linkedin_urls, session=session
        )

        # Set company context on each profile
        if company_name:
            for profile in profiles:
                profile.startup_company = company_name

        return profiles

    def fetch_profiles_by_linkedin_batch(
        self,
        linkedin_inputs: list[str],
    ) -> list["FounderProfile"]:
        """
        Synchronous wrapper for batch LinkedIn profile fetching.

        Use this when you can't use async/await.

        Args:
            linkedin_inputs: List of LinkedIn URLs or slugs

        Returns:
            List of FounderProfile objects
        """
        return _run_async(
            self.fetch_profiles_by_linkedin_batch_async(linkedin_inputs)
        )

    def fetch_company_founders(
        self,
        linkedin_urls: list[str],
        company_name: Optional[str] = None,
    ) -> list["FounderProfile"]:
        """
        Synchronous wrapper for company founder fetching.

        Args:
            linkedin_urls: List of founder LinkedIn URLs
            company_name: Company name for context

        Returns:
            List of FounderProfile objects
        """
        return _run_async(
            self.fetch_company_founders_async(linkedin_urls, company_name)
        )

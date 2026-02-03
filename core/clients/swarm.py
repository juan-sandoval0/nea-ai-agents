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

import os
import time
import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional
from urllib.parse import urlparse

import requests

logger = logging.getLogger(__name__)

# =============================================================================
# CONFIGURATION
# =============================================================================

DEFAULT_BASE_URL = "https://bee.theswarm.com/v2"
DEFAULT_TIMEOUT = 30  # seconds
RATE_LIMIT_RPS = 5  # requests per second (conservative)


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

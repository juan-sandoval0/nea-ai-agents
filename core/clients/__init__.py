"""External API clients for NEA AI Agents.

Available clients:
- HarmonicClient: Harmonic.ai company intelligence API
- TavilyClient: Tavily website intelligence API
- SwarmClient: The Swarm profile intelligence API
- NewsApiClient: EventRegistry news and event API
"""

from core.clients.harmonic import (
    HarmonicClient,
    HarmonicCompany,
    HarmonicPerson,
    HarmonicAPIError,
)
from core.clients.tavily import (
    TavilyClient,
    WebsiteIntelligence,
    TavilyAPIError,
)
from core.clients.swarm import (
    SwarmClient,
    SwarmProfile,
    SwarmExperience,
    SwarmEducation,
    SwarmAPIError,
)
from core.clients.newsapi import (
    NewsApiClient,
    NewsApiArticle,
    NewsApiEvent,
    NewsApiError,
)

__all__ = [
    "HarmonicClient",
    "HarmonicCompany",
    "HarmonicPerson",
    "HarmonicAPIError",
    "TavilyClient",
    "WebsiteIntelligence",
    "TavilyAPIError",
    "SwarmClient",
    "SwarmProfile",
    "SwarmExperience",
    "SwarmEducation",
    "SwarmAPIError",
    "NewsApiClient",
    "NewsApiArticle",
    "NewsApiEvent",
    "NewsApiError",
]

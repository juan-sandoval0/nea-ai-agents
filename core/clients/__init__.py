"""External API clients for NEA AI Agents.

Available clients:
- HarmonicClient: Harmonic.ai company intelligence API
- TavilyClient: Tavily website intelligence API
- SwarmClient: The Swarm profile intelligence API
- ParallelSearchClient: Parallel Search API for news research
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
from core.clients.parallel_search import (
    ParallelSearchClient,
    ParallelSearchResult,
    ParallelSearchError,
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
    "ParallelSearchClient",
    "ParallelSearchResult",
    "ParallelSearchError",
]

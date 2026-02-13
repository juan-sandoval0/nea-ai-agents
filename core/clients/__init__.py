"""External API clients for NEA AI Agents.

Available clients:
- HarmonicClient: Harmonic.ai company intelligence API
- TavilyClient: Tavily website intelligence API
- SwarmClient: The Swarm profile intelligence API
- ParallelSearchClient: Parallel Search API for news research
- HackerNewsClient: Hacker News Algolia API for community mentions
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
    # Unified founder models
    FounderProfile,
    FounderExperience,
    FounderEducation,
)
from core.clients.parallel_search import (
    ParallelSearchClient,
    ParallelSearchResult,
    ParallelSearchError,
)
from core.clients.hackernews import (
    HackerNewsClient,
    HNStory,
    HNSearchResult,
    HackerNewsAPIError,
)
from core.clients.supabase_client import (
    get_supabase,
    clear_supabase_cache,
    SupabaseConfigError,
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
    # Unified founder models
    "FounderProfile",
    "FounderExperience",
    "FounderEducation",
    "ParallelSearchClient",
    "ParallelSearchResult",
    "ParallelSearchError",
    "HackerNewsClient",
    "HNStory",
    "HNSearchResult",
    "HackerNewsAPIError",
    "get_supabase",
    "clear_supabase_cache",
    "SupabaseConfigError",
]

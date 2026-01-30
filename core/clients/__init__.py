"""External API clients for NEA AI Agents.

Available clients:
- HarmonicClient: Harmonic.ai company intelligence API
- TavilyClient: Tavily website intelligence API
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

__all__ = [
    "HarmonicClient",
    "HarmonicCompany",
    "HarmonicPerson",
    "HarmonicAPIError",
    "TavilyClient",
    "WebsiteIntelligence",
    "TavilyAPIError",
]

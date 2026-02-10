"""
Pydantic models for API request/response schemas.
"""

from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field


# =============================================================================
# REQUEST MODELS
# =============================================================================

class BriefingRequest(BaseModel):
    """Request to generate a new briefing."""
    url: str = Field(..., description="Company URL or domain (e.g., 'stripe.com')")


# =============================================================================
# RESPONSE MODELS
# =============================================================================

class CompanySnapshot(BaseModel):
    """Company core information."""
    company_name: str
    founded: Optional[str] = None
    hq: Optional[str] = None
    employees: Optional[int] = None
    products: Optional[str] = None
    customers: Optional[str] = None
    total_funding: Optional[float] = None
    last_round: Optional[str] = None


class FounderInfo(BaseModel):
    """Founder information."""
    name: str
    role: Optional[str] = None
    linkedin_url: Optional[str] = None
    background: Optional[str] = None


class Signal(BaseModel):
    """Key signal or indicator."""
    signal_type: str
    description: str
    source: str


class NewsItem(BaseModel):
    """News article."""
    headline: str
    outlet: Optional[str] = None
    url: Optional[str] = None
    published_date: Optional[str] = None
    takeaway: Optional[str] = None
    synopsis: Optional[str] = None  # 1-2 sentence VC-relevant summary
    sentiment: Optional[str] = None  # "positive", "negative", or "neutral"
    news_type: Optional[str] = None  # Signal type: funding, acquisition, executive_change, etc.


class BriefingResponse(BaseModel):
    """Full briefing response."""
    id: str = Field(..., description="Unique briefing ID")
    company_id: str = Field(..., description="Normalized company identifier")
    company_name: str
    created_at: datetime

    # Structured sections
    tldr: Optional[str] = None
    why_it_matters: Optional[list[str]] = None
    company_snapshot: Optional[CompanySnapshot] = None
    founders: list[FounderInfo] = []
    signals: list[Signal] = []
    news: list[NewsItem] = []
    meeting_prep: Optional[str] = None

    # Full markdown (for copy/export)
    markdown: str

    # Metadata
    success: bool
    error: Optional[str] = None
    data_sources: dict = {}


class BriefingListItem(BaseModel):
    """Summary item for briefing list view."""
    id: str
    company_id: str
    company_name: str
    created_at: datetime
    success: bool


class BriefingListResponse(BaseModel):
    """Response for listing briefings."""
    briefings: list[BriefingListItem]
    total: int


class ErrorResponse(BaseModel):
    """Error response."""
    error: str
    detail: Optional[str] = None

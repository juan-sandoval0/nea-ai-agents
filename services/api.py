"""
FastAPI backend for Meeting Briefing Agent.

Endpoints:
- POST /api/briefing - Generate a new briefing
- GET /api/briefings - List past briefings
- GET /api/briefings/{id} - Get a specific briefing
- DELETE /api/briefings/{id} - Delete a briefing
- GET /api/digest/weekly - Generate weekly signal digest

Run with:
    uvicorn services.api:app --reload --port 8000
"""

# Load environment variables (don't override existing env vars from Railway/production)
from dotenv import load_dotenv
load_dotenv(override=False)

from datetime import datetime
from typing import Optional
from uuid import uuid4
import logging
import re

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware

from services.models import (
    BriefingRequest,
    BriefingResponse,
    BriefingListItem,
    BriefingListResponse,
    CompanySnapshot,
    FounderInfo,
    Signal,
    NewsItem,
    ErrorResponse,
    WeeklyDigestResponse,
    DigestArticleResponse,
    SentimentRollup,
    IndustryHighlight,
    DigestStats,
)
from services.history import BriefingHistoryDB, BriefingRecord

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# =============================================================================
# FASTAPI APP
# =============================================================================

app = FastAPI(
    title="NEA Meeting Briefing API",
    description="API for generating company meeting briefings",
    version="1.0.0",
)

# CORS - allow Lovable frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Lovable preview domains vary; restrict in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Initialize history database
history_db = BriefingHistoryDB()


# =============================================================================
# HELPER FUNCTIONS
# =============================================================================

def parse_briefing_sections(markdown: str) -> dict:
    """
    Parse markdown briefing into structured sections.

    Extracts:
    - tldr: TL;DR section
    - why_it_matters: Why This Meeting Matters bullets
    - meeting_prep: For This Meeting section
    """
    sections = {}

    # Extract TL;DR
    tldr_match = re.search(
        r'### 1\) TL;DR\s*\n(.*?)(?=\n### |\Z)',
        markdown,
        re.DOTALL
    )
    if tldr_match:
        sections['tldr'] = tldr_match.group(1).strip()

    # Extract Why This Meeting Matters as bullet list
    why_match = re.search(
        r'### 2\) Why This Meeting Matters\s*\n(.*?)(?=\n### |\Z)',
        markdown,
        re.DOTALL
    )
    if why_match:
        bullets = re.findall(r'[-*]\s+(.+)', why_match.group(1))
        sections['why_it_matters'] = bullets if bullets else None

    # Extract For This Meeting
    meeting_match = re.search(
        r'### 7\) For This Meeting\s*\n(.*?)(?=\n### |\Z)',
        markdown,
        re.DOTALL
    )
    if meeting_match:
        sections['meeting_prep'] = meeting_match.group(1).strip()

    return sections


def build_response(
    briefing_id: str,
    result: dict,
    bundle: "CompanyBundle",
    created_at: datetime,
) -> BriefingResponse:
    """Build BriefingResponse from generate_briefing result and company bundle."""

    # Parse sections from markdown
    sections = {}
    if result.get('markdown'):
        sections = parse_briefing_sections(result['markdown'])

    # Build company snapshot
    company_snapshot = None
    if bundle.company_core:
        c = bundle.company_core
        last_round = None
        if c.last_round_date and c.last_round_funding:
            last_round = f"${c.last_round_funding:,.0f} ({c.last_round_date})"
        elif c.last_round_date:
            last_round = c.last_round_date

        company_snapshot = CompanySnapshot(
            company_name=c.company_name,
            founded=c.founding_date,
            hq=c.hq,
            employees=c.employee_count,
            products=c.products,
            customers=c.customers,
            total_funding=c.total_funding,
            last_round=last_round,
        )

    # Build founders list
    founders = [
        FounderInfo(
            name=f.name,
            role=f.role_title,
            linkedin_url=f.linkedin_url,
            background=f.background,
        )
        for f in bundle.founders
    ]

    # Build signals list
    signals = [
        Signal(
            signal_type=s.signal_type,
            description=s.description,
            source=s.source,
        )
        for s in bundle.key_signals
    ]

    # Build news list
    news = [
        NewsItem(
            headline=n.article_headline,
            outlet=n.outlet,
            url=n.url,
            published_date=n.published_date,
            takeaway=None,  # Takeaways are in the markdown, not parsed separately
        )
        for n in bundle.news
    ]

    return BriefingResponse(
        id=briefing_id,
        company_id=result['company_id'],
        company_name=result.get('company_name') or 'Unknown',
        created_at=created_at,
        tldr=sections.get('tldr'),
        why_it_matters=sections.get('why_it_matters'),
        company_snapshot=company_snapshot,
        founders=founders,
        signals=signals,
        news=news,
        meeting_prep=sections.get('meeting_prep'),
        markdown=result.get('markdown') or '',
        success=result.get('success', False),
        error=result.get('error'),
        data_sources=result.get('data_sources', {}),
    )


# =============================================================================
# ENDPOINTS
# =============================================================================

@app.get("/")
async def root():
    """Health check endpoint."""
    return {"status": "ok", "service": "NEA Meeting Briefing API"}


@app.post("/api/briefing", response_model=BriefingResponse)
async def create_briefing(request: BriefingRequest):
    """
    Generate a new meeting briefing for a company.

    1. Ingests company data from APIs (Harmonic, Swarm, etc.)
    2. Generates briefing using LLM
    3. Stores in history
    4. Returns structured response
    """
    # Import here to avoid circular imports and allow lazy loading
    from tools.company_tools import ingest_company, get_company_bundle, normalize_company_id
    from agents.meeting_briefing.briefing_generator import generate_briefing

    url = request.url.strip()
    logger.info(f"Generating briefing for: {url}")

    try:
        # Step 1: Ingest company data
        logger.info("Ingesting company data...")
        ingest_result = ingest_company(url)

        if not ingest_result.get('company_core'):
            errors = ingest_result.get('errors', [])
            error_msg = errors[0] if errors else 'Company not found'
            raise HTTPException(
                status_code=404,
                detail=f"Could not find company: {error_msg}"
            )

        # Step 2: Generate briefing
        logger.info("Generating briefing...")
        result = generate_briefing(url)

        if not result.get('success'):
            raise HTTPException(
                status_code=500,
                detail=f"Briefing generation failed: {result.get('error', 'Unknown error')}"
            )

        # Step 3: Get company bundle for structured data
        normalized_id = normalize_company_id(url)
        bundle = get_company_bundle(normalized_id)

        # Step 4: Build response
        briefing_id = str(uuid4())
        created_at = datetime.utcnow()

        response = build_response(briefing_id, result, bundle, created_at)

        # Step 5: Store in history
        history_db.save_briefing(BriefingRecord(
            id=briefing_id,
            company_id=response.company_id,
            company_name=response.company_name,
            created_at=created_at,
            markdown=response.markdown,
            success=response.success,
            error=response.error,
            data_sources=response.data_sources,
        ))

        logger.info(f"Briefing generated successfully: {response.company_name}")
        return response

    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Error generating briefing: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/briefings", response_model=BriefingListResponse)
async def list_briefings(
    search: Optional[str] = Query(None, description="Search by company name or URL"),
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
):
    """List past briefings with optional search."""
    briefings = history_db.list_briefings(search=search, limit=limit, offset=offset)
    total = history_db.count_briefings(search=search)

    items = [
        BriefingListItem(
            id=b.id,
            company_id=b.company_id,
            company_name=b.company_name,
            created_at=b.created_at,
            success=b.success,
        )
        for b in briefings
    ]

    return BriefingListResponse(briefings=items, total=total)


@app.get("/api/briefings/{briefing_id}", response_model=BriefingResponse)
async def get_briefing(briefing_id: str):
    """Get a specific briefing by ID."""
    from tools.company_tools import get_company_bundle

    record = history_db.get_briefing(briefing_id)
    if not record:
        raise HTTPException(status_code=404, detail="Briefing not found")

    # Get current company bundle for structured data
    bundle = get_company_bundle(record.company_id)

    # Reconstruct result dict
    result = {
        'company_id': record.company_id,
        'company_name': record.company_name,
        'markdown': record.markdown,
        'success': record.success,
        'error': record.error,
        'data_sources': record.data_sources,
    }

    return build_response(record.id, result, bundle, record.created_at)


@app.delete("/api/briefings/{briefing_id}")
async def delete_briefing(briefing_id: str):
    """Delete a briefing."""
    success = history_db.delete_briefing(briefing_id)
    if not success:
        raise HTTPException(status_code=404, detail="Briefing not found")
    return {"status": "deleted", "id": briefing_id}


# =============================================================================
# DIGEST ENDPOINTS
# =============================================================================

@app.get("/api/digest/weekly", response_model=WeeklyDigestResponse)
async def get_weekly_digest(
    days: int = Query(7, ge=1, le=30, description="Number of days to look back"),
    featured_count: int = Query(3, ge=1, le=5, description="Number of featured articles"),
    summary_count: int = Query(8, ge=1, le=15, description="Number of summary articles"),
    investor_id: Optional[str] = Query(None, description="Filter to specific investor"),
    include_markdown: bool = Query(True, description="Include markdown export"),
):
    """
    Generate a weekly digest of company signals.

    Returns a tiered article display:
    - Top 2-3 featured articles with full details
    - 7-8 summarized articles in condensed format
    - Sentiment rollup across all articles
    - Industry trend highlights
    """
    from agents.news_aggregator.digest import generate_weekly_digest

    try:
        logger.info(f"Generating weekly digest (days={days}, featured={featured_count}, summary={summary_count})")

        # Generate digest using the digest module
        digest = generate_weekly_digest(
            days=days,
            featured_count=featured_count,
            summary_count=summary_count,
            investor_id=investor_id,
            include_industry_highlights=True,
            use_llm_summaries=False,  # Can be enabled for enhanced summaries
        )

        # Convert featured articles
        featured = [
            DigestArticleResponse(
                headline=a.signal.headline,
                company=a.company_name,
                category=a.company_category,
                signal_type=a.signal.signal_type,
                source=a.signal.source_name,
                url=a.signal.source_url,
                published_date=a.signal.published_date,
                relevance_score=a.signal.relevance_score or 0,
                rank_score=a.rank_score,
                sentiment=a.signal.sentiment,
                synopsis=a.signal.synopsis or a.signal.description,
            )
            for a in digest.featured_articles
        ]

        # Convert summary articles
        summary = [
            DigestArticleResponse(
                headline=a.signal.headline,
                company=a.company_name,
                category=a.company_category,
                signal_type=a.signal.signal_type,
                source=a.signal.source_name,
                url=a.signal.source_url,
                published_date=a.signal.published_date,
                relevance_score=a.signal.relevance_score or 0,
                rank_score=a.rank_score,
                sentiment=a.signal.sentiment,
                synopsis=a.signal.synopsis,
            )
            for a in digest.summary_articles
        ]

        # Calculate sentiment rollup
        all_articles = digest.featured_articles + digest.summary_articles
        sentiment_counts = {"positive": 0, "negative": 0, "neutral": 0}
        for article in all_articles:
            sentiment = article.signal.sentiment or "neutral"
            if sentiment in sentiment_counts:
                sentiment_counts[sentiment] += 1
            else:
                sentiment_counts["neutral"] += 1

        sentiment_rollup = SentimentRollup(
            positive=sentiment_counts["positive"],
            negative=sentiment_counts["negative"],
            neutral=sentiment_counts["neutral"],
            total=len(all_articles),
        )

        # Convert industry highlights
        industry_highlights = [
            IndustryHighlight(
                industry=industry,
                total_signals=data.get("total_signals", 0),
                company_count=data.get("company_count", 0),
                top_types=data.get("top_types", {}),
            )
            for industry, data in digest.industry_highlights.items()
        ]

        # Build stats
        stats = DigestStats(
            total_signals=digest.stats.get("total_signals", 0),
            companies_covered=digest.stats.get("companies_covered", 0),
            portfolio_signals=digest.stats.get("portfolio_signals", 0),
            competitor_signals=digest.stats.get("competitor_signals", 0),
            featured_count=len(featured),
            summary_count=len(summary),
        )

        # Build response
        response = WeeklyDigestResponse(
            start_date=digest.start_date,
            end_date=digest.end_date,
            generated_at=datetime.fromisoformat(digest.generated_at),
            featured_articles=featured,
            summary_articles=summary,
            sentiment_rollup=sentiment_rollup,
            industry_highlights=industry_highlights,
            stats=stats,
            markdown=digest.to_markdown() if include_markdown else None,
        )

        logger.info(
            f"Digest generated: {len(featured)} featured, {len(summary)} summary, "
            f"sentiment: +{sentiment_rollup.positive}/-{sentiment_rollup.negative}"
        )

        return response

    except Exception as e:
        logger.exception(f"Error generating weekly digest: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# =============================================================================
# MAIN
# =============================================================================

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)

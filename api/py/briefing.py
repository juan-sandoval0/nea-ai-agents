"""
Vercel Python Function: briefing generation.

Mounted externally at /api/briefing via vercel.json rewrites.
Ports the POST /api/briefing handler out of services/api.py so the
briefing flow can run on Fluid Compute instead of Railway.
"""
from __future__ import annotations

import hmac
import logging
import os
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional
from uuid import uuid4

# Make repo root importable so we can reach core/, tools/, agents/, services/
_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from dotenv import load_dotenv
load_dotenv(override=False)

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from services.models import (
    BriefingRequest,
    BriefingResponse,
    CompanySnapshot,
    FounderInfo,
    Signal,
    NewsItem,
    CompetitorInfo,
)
from services.history import BriefingHistoryDB, BriefingRecord
from services.logging_setup import setup_logging, setup_langsmith, get_logger
from services.rate_limit import check_rate_limit, RateLimitExceeded
from services.auth import USE_CLERK_AUTH, verify_clerk_token

# Configure structured logging and LangSmith tracing
setup_logging(use_json=True)
setup_langsmith(project="nea-briefing")
logger = get_logger(__name__)

app = FastAPI(title="NEA Briefing Function", version="3.0.0")

_allowed_origins_env = os.getenv("ALLOWED_ORIGINS", "http://localhost:3000")
ALLOWED_ORIGINS = [o.strip() for o in _allowed_origins_env.split(",") if o.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=False,
    allow_methods=["POST", "OPTIONS"],
    allow_headers=["Content-Type", "X-NEA-Key", "Authorization"],
)

NEA_API_KEY = os.getenv("NEA_API_KEY")

# Rate limit: 10 briefings per minute per user/key
BRIEFING_RATE_LIMIT = 10
BRIEFING_RATE_WINDOW = 60  # seconds


@app.middleware("http")
async def auth_and_rate_limit(request: Request, call_next):
    """
    Phase 3.1: Dual-mode authentication + rate limiting.
    """
    if request.method == "POST":
        identifier = "anonymous"

        if USE_CLERK_AUTH:
            # Clerk JWT authentication
            auth_header = request.headers.get("Authorization", "")
            if not auth_header.startswith("Bearer "):
                return JSONResponse(status_code=401, content={"detail": "Missing Authorization header"})

            token = auth_header[7:]
            claims = verify_clerk_token(token)
            if not claims:
                return JSONResponse(status_code=401, content={"detail": "Invalid or expired token"})

            # Use user_id for rate limiting
            request.state.user_id = claims.get("sub")
            identifier = f"user:{request.state.user_id}"
        else:
            # Legacy X-NEA-Key authentication
            provided = request.headers.get("x-nea-key", "")
            if NEA_API_KEY and provided and not hmac.compare_digest(provided, NEA_API_KEY):
                return JSONResponse(status_code=401, content={"detail": "Invalid X-NEA-Key"})
            identifier = provided or "anonymous"

        # Check rate limit
        try:
            check_rate_limit(
                key="briefing",
                identifier=identifier,
                limit=BRIEFING_RATE_LIMIT,
                window=BRIEFING_RATE_WINDOW,
            )
        except RateLimitExceeded as e:
            logger.warning("Rate limit exceeded for briefing: %s", identifier)
            return JSONResponse(
                status_code=429,
                content={"detail": str(e)},
                headers={"Retry-After": str(e.retry_after)},
            )

    return await call_next(request)


history_db = BriefingHistoryDB()


def parse_briefing_sections(markdown: str) -> dict:
    """Parse markdown briefing into TL;DR / why_it_matters / meeting_prep."""
    sections: dict = {}

    tldr_match = re.search(r'### 1\) TL;DR\s*\n(.*?)(?=\n### |\Z)', markdown, re.DOTALL)
    if tldr_match:
        sections['tldr'] = tldr_match.group(1).strip()

    why_match = re.search(
        r'### 2\) Why This Meeting Matters\s*\n(.*?)(?=\n### |\Z)', markdown, re.DOTALL
    )
    if why_match:
        bullets = re.findall(r'[-*]\s+(.+)', why_match.group(1))
        sections['why_it_matters'] = bullets if bullets else None

    meeting_match = re.search(
        r'### [378]\) For This Meeting\s*\n(.*?)(?=\n### |\Z)', markdown, re.DOTALL
    )
    if meeting_match:
        sections['meeting_prep'] = meeting_match.group(1).strip()

    return sections


def build_response(briefing_id: str, result: dict, bundle, created_at: datetime) -> BriefingResponse:
    # Phase 3.4: Check for pre-parsed structured fields first (from with_structured_output)
    # If present, use them directly; otherwise fall back to regex parsing
    if result.get('tldr') is not None:
        # Structured output was used - fields are already parsed
        sections = {
            'tldr': result['tldr'],
            'why_it_matters': result.get('why_it_matters'),
            'meeting_prep': result.get('meeting_prep'),
        }
    elif result.get('markdown'):
        # Legacy path: parse sections from markdown using regex
        sections = parse_briefing_sections(result['markdown'])
    else:
        sections = {}

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

    founders = [
        FounderInfo(name=f.name, role=f.role_title, linkedin_url=f.linkedin_url, background=f.background)
        for f in bundle.founders
    ]
    signals = [
        Signal(signal_type=s.signal_type, description=s.description, source=s.source)
        for s in bundle.key_signals
    ]
    news = [
        NewsItem(
            headline=n.article_headline,
            outlet=n.outlet,
            url=n.url,
            published_date=n.published_date,
            synopsis=n.synopsis,
            takeaway=n.synopsis,
            sentiment=n.sentiment,
            news_type=n.news_type,
        )
        for n in bundle.news
    ]
    competitors = [
        CompetitorInfo(
            name=c.competitor_name,
            domain=c.competitor_domain,
            competitor_type=c.competitor_type,
            description=c.description,
            funding_total=c.funding_total,
            funding_stage=c.funding_stage,
            funding_last_amount=c.funding_last_amount,
            funding_last_date=c.funding_last_date,
            headcount=c.headcount,
            tags=c.tags,
        )
        for c in bundle.competitors
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
        competitors=competitors,
        meeting_prep=sections.get('meeting_prep'),
        markdown=result.get('markdown') or '',
        success=result.get('success', False),
        error=result.get('error'),
        data_sources=result.get('data_sources', {}),
    )


async def _generate_briefing(request: BriefingRequest) -> BriefingResponse:
    from tools.company_tools import ingest_company, get_company_bundle, normalize_company_id
    from agents.meeting_briefing.briefing_generator import generate_briefing

    url = request.url.strip()
    logger.info("Generating briefing for: %s", url)

    ingest_result = ingest_company(url)
    if not ingest_result.get('company_core'):
        errors = ingest_result.get('errors', [])
        error_msg = errors[0] if errors else 'Company not found'
        raise HTTPException(status_code=404, detail=f"Could not find company: {error_msg}")

    result = generate_briefing(url)
    if not result.get('success'):
        raise HTTPException(
            status_code=500,
            detail=f"Briefing generation failed: {result.get('error', 'Unknown error')}",
        )

    normalized_id = normalize_company_id(url)
    bundle = get_company_bundle(normalized_id)

    briefing_id = str(uuid4())
    created_at = datetime.utcnow()
    response = build_response(briefing_id, result, bundle, created_at)

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

    logger.info("Briefing generated successfully: %s", response.company_name)
    return response


# Vercel rewrites /api/briefing → this function; FastAPI sees the original path.
# Also register "/" so direct invocation at the function path works.
@app.post("/api/briefing", response_model=BriefingResponse)
async def create_briefing_rewritten(request: BriefingRequest):
    try:
        return await _generate_briefing(request)
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Error generating briefing: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))


@app.post("/", response_model=BriefingResponse)
async def create_briefing_root(request: BriefingRequest):
    try:
        return await _generate_briefing(request)
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Error generating briefing: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))

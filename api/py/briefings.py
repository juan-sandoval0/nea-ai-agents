"""
Vercel Python Function: briefing history read endpoints.

Serves GET /api/briefings (list) and GET /api/briefings/{id} (get by ID).
Ports the corresponding handlers out of services/api.py (Railway FastAPI),
so briefing history can be read without depending on Railway.

Mounted externally via vercel.json rewrites:
  /api/briefings           → /api/py/briefings
  /api/briefings/:id       → /api/py/briefings?briefing_id=:id

Vercel's Python runtime only serves the exact path the file is mounted at,
so the detail route routes the ID as a query param rather than a subpath.
"""
from __future__ import annotations

import hmac
import logging
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional

# Make repo root importable so we can reach core/, tools/, agents/, services/
_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from dotenv import load_dotenv
load_dotenv(override=False)

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from services.models import (
    BriefingResponse,
    BriefingListItem,
    BriefingListResponse,
    CompanySnapshot,
    FounderInfo,
    Signal,
    NewsItem,
    CompetitorInfo,
)
from services.history import BriefingHistoryDB
from services.logging_setup import setup_logging, get_logger
from services.auth import USE_CLERK_AUTH, verify_clerk_token

setup_logging(use_json=True)
logger = get_logger(__name__)

app = FastAPI(title="NEA Briefings Read Function", version="3.0.0")

_allowed_origins_env = os.getenv("ALLOWED_ORIGINS", "http://localhost:3000")
ALLOWED_ORIGINS = [o.strip() for o in _allowed_origins_env.split(",") if o.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=False,
    allow_methods=["GET", "OPTIONS"],
    allow_headers=["Content-Type", "X-NEA-Key", "Authorization"],
)

NEA_API_KEY = os.getenv("NEA_API_KEY")


@app.middleware("http")
async def auth_middleware(request: Request, call_next):
    """Dual-mode auth. Mirrors api/py/briefing.py, applied to all non-OPTIONS methods."""
    if request.method == "OPTIONS":
        return await call_next(request)

    if USE_CLERK_AUTH:
        auth_header = request.headers.get("Authorization", "")
        if not auth_header.startswith("Bearer "):
            return JSONResponse(status_code=401, content={"detail": "Missing Authorization header"})
        claims = verify_clerk_token(auth_header[7:])
        if not claims:
            return JSONResponse(status_code=401, content={"detail": "Invalid or expired token"})
        request.state.user_id = claims.get("sub")
    elif NEA_API_KEY:
        provided = request.headers.get("x-nea-key", "")
        if provided and not hmac.compare_digest(provided, NEA_API_KEY):
            return JSONResponse(status_code=401, content={"detail": "Invalid X-NEA-Key"})

    return await call_next(request)


history_db = BriefingHistoryDB()


def _build_briefing_response(record, bundle) -> BriefingResponse:
    """Reconstruct a full BriefingResponse from a stored record + fresh company bundle."""
    company_snapshot = None
    if bundle and bundle.company_core:
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

    founders = []
    signals = []
    news = []
    competitors = []
    if bundle:
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
        id=record.id,
        company_id=record.company_id,
        company_name=record.company_name,
        created_at=record.created_at,
        tldr=None,
        why_it_matters=None,
        company_snapshot=company_snapshot,
        founders=founders,
        signals=signals,
        news=news,
        competitors=competitors,
        meeting_prep=None,
        markdown=record.markdown or "",
        success=record.success,
        error=record.error,
        data_sources=record.data_sources or {},
    )


async def _list_briefings(search: Optional[str], limit: int, offset: int) -> BriefingListResponse:
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


async def _get_briefing(briefing_id: str) -> BriefingResponse:
    from tools.company_tools import get_company_bundle

    record = history_db.get_briefing(briefing_id)
    if not record:
        raise HTTPException(status_code=404, detail="Briefing not found")

    try:
        bundle = get_company_bundle(record.company_id)
    except Exception as exc:
        logger.warning("Failed to refetch bundle for %s: %s", record.company_id, exc)
        bundle = None

    return _build_briefing_response(record, bundle)


# Single dispatcher for list + get-by-id. Vercel's Python runtime only maps a
# single file to its exact path (/api/py/briefings), with no subpath forwarding,
# so we cannot use a path param. vercel.json rewrites both /api/briefings and
# /api/briefings/:id into this function, passing :id via ?briefing_id= when
# present. Registered on the rewrite target and on "/" so direct invocations work.
async def _dispatch(
    briefing_id: Optional[str],
    search: Optional[str],
    limit: int,
    offset: int,
):
    if briefing_id:
        try:
            return await _get_briefing(briefing_id)
        except HTTPException:
            raise
        except Exception as exc:
            logger.exception("Error fetching briefing %s: %s", briefing_id, exc)
            raise HTTPException(status_code=500, detail=str(exc))
    return await _list_briefings(search, limit, offset)


@app.get("/api/briefings")
async def briefings_rewritten(
    briefing_id: Optional[str] = Query(None),
    search: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
):
    return await _dispatch(briefing_id, search, limit, offset)


@app.get("/")
async def briefings_root(
    briefing_id: Optional[str] = Query(None),
    search: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
):
    return await _dispatch(briefing_id, search, limit, offset)


# Vercel's ASGI adapter appears to pass the original request path through
# to FastAPI (not the rewrite destination). So /api/briefings/:id reaches
# the function with that literal path. Handle it directly.
@app.get("/api/briefings/{briefing_id}")
async def briefings_detail_path(briefing_id: str):
    return await _dispatch(briefing_id, None, 50, 0)

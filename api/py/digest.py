"""
Vercel Python Function: weekly news digest.

Serves GET /api/digest/weekly. Ports the handler out of services/api.py
(Railway FastAPI) so the Digest page can load without a Railway dependency.

Mounted externally at /api/digest/weekly via vercel.json rewrites.
"""
from __future__ import annotations

import hmac
import logging
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from dotenv import load_dotenv
load_dotenv(override=False)

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from services.models import (
    WeeklyDigestResponse,
    DigestArticleResponse,
    SentimentRollup,
    IndustryHighlight,
    DigestStats,
)
from services.logging_setup import setup_logging, get_logger
from services.auth import USE_CLERK_AUTH, verify_clerk_token

setup_logging(use_json=True)
logger = get_logger(__name__)

app = FastAPI(title="NEA Digest Function", version="3.0.0")

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


async def _get_weekly_digest(
    days: int,
    featured_count: int,
    summary_count: int,
    investor_id: Optional[str],
    include_markdown: bool,
) -> WeeklyDigestResponse:
    from agents.news_aggregator.digest import generate_weekly_digest

    logger.info(
        "Generating weekly digest (days=%s, featured=%s, summary=%s)",
        days, featured_count, summary_count,
    )

    digest = generate_weekly_digest(
        days=days,
        featured_count=featured_count,
        summary_count=summary_count,
        investor_id=investor_id,
        include_industry_highlights=True,
        use_llm_summaries=False,
    )

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

    all_articles = digest.featured_articles + digest.summary_articles
    sentiment_counts = {"positive": 0, "negative": 0, "neutral": 0}
    for article in all_articles:
        s = article.signal.sentiment or "neutral"
        if s in sentiment_counts:
            sentiment_counts[s] += 1
        else:
            sentiment_counts["neutral"] += 1

    sentiment_rollup = SentimentRollup(
        positive=sentiment_counts["positive"],
        negative=sentiment_counts["negative"],
        neutral=sentiment_counts["neutral"],
        total=len(all_articles),
    )

    industry_highlights = [
        IndustryHighlight(
            industry=industry,
            total_signals=data.get("total_signals", 0),
            company_count=data.get("company_count", 0),
            top_types=data.get("top_types", {}),
        )
        for industry, data in digest.industry_highlights.items()
    ]

    stats = DigestStats(
        total_signals=digest.stats.get("total_signals", 0),
        companies_covered=digest.stats.get("companies_covered", 0),
        portfolio_signals=digest.stats.get("portfolio_signals", 0),
        competitor_signals=digest.stats.get("competitor_signals", 0),
        featured_count=len(featured),
        summary_count=len(summary),
    )

    return WeeklyDigestResponse(
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


@app.get("/api/digest/weekly", response_model=WeeklyDigestResponse)
async def weekly_digest_rewritten(
    days: int = Query(7, ge=1, le=30),
    featured_count: int = Query(3, ge=1, le=5),
    summary_count: int = Query(8, ge=1, le=15),
    investor_id: Optional[str] = Query(None),
    include_markdown: bool = Query(True),
):
    try:
        return await _get_weekly_digest(days, featured_count, summary_count, investor_id, include_markdown)
    except Exception as exc:
        logger.exception("Error generating weekly digest: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))


@app.get("/", response_model=WeeklyDigestResponse)
async def weekly_digest_root(
    days: int = Query(7, ge=1, le=30),
    featured_count: int = Query(3, ge=1, le=5),
    summary_count: int = Query(8, ge=1, le=15),
    investor_id: Optional[str] = Query(None),
    include_markdown: bool = Query(True),
):
    try:
        return await _get_weekly_digest(days, featured_count, summary_count, investor_id, include_markdown)
    except Exception as exc:
        logger.exception("Error generating weekly digest: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))

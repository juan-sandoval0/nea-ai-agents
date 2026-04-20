"""
Vercel Python Function: outreach generation.

Mounted externally at /api/outreach via vercel.json rewrites.
"""
from __future__ import annotations

import asyncio
import hmac
import logging
import os
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from dotenv import load_dotenv
load_dotenv(override=False)

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from services.models import OutreachRequest, OutreachResponse
from services.logging_setup import setup_logging, setup_langsmith, get_logger
from services.rate_limit import check_rate_limit, RateLimitExceeded

# Configure structured logging and LangSmith tracing
setup_logging(use_json=True)
setup_langsmith(project="nea-outreach")
logger = get_logger(__name__)

app = FastAPI(title="NEA Outreach Function", version="2.4.0")

_allowed_origins_env = os.getenv("ALLOWED_ORIGINS", "http://localhost:3000")
ALLOWED_ORIGINS = [o.strip() for o in _allowed_origins_env.split(",") if o.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=False,
    allow_methods=["POST", "OPTIONS"],
    allow_headers=["Content-Type", "X-NEA-Key"],
)

NEA_API_KEY = os.getenv("NEA_API_KEY")

# Rate limit: 5 outreach per minute per X-NEA-Key
OUTREACH_RATE_LIMIT = 5
OUTREACH_RATE_WINDOW = 60  # seconds


@app.middleware("http")
async def require_api_key_and_rate_limit(request: Request, call_next):
    if request.method == "POST":
        provided = request.headers.get("x-nea-key", "")

        # Check API key
        if NEA_API_KEY and provided and not hmac.compare_digest(provided, NEA_API_KEY):
            return JSONResponse(status_code=401, content={"detail": "Invalid X-NEA-Key"})

        # Check rate limit (use API key as identifier, fallback to "anonymous")
        identifier = provided or "anonymous"
        try:
            check_rate_limit(
                key="outreach",
                identifier=identifier,
                limit=OUTREACH_RATE_LIMIT,
                window=OUTREACH_RATE_WINDOW,
            )
        except RateLimitExceeded as e:
            logger.warning("Rate limit exceeded for outreach: %s", identifier)
            return JSONResponse(
                status_code=429,
                content={"detail": str(e)},
                headers={"Retry-After": str(e.retry_after)},
            )

    return await call_next(request)


async def _generate(request: OutreachRequest) -> OutreachResponse:
    from agents.outreach.generator import generate_outreach

    loop = asyncio.get_event_loop()
    try:
        result = await loop.run_in_executor(
            None,
            lambda: generate_outreach(
                company_id=request.company_id,
                output_format=request.output_format,
                contact_name=request.contact_name,
                investor_key=request.investor_key,
                skip_ingest=request.skip_ingest,
                context_type_override=request.context_type_override,
                outreach_goal=request.outreach_goal,
                has_event_context=request.has_event_context,
                event_details=request.event_details,
                has_prior_relationship=request.has_prior_relationship,
                prior_relationship_details=request.prior_relationship_details,
                stealth_mode=request.stealth_mode,
                founder_linkedin_url=request.founder_linkedin_url,
                founder_background_notes=request.founder_background_notes,
            ),
        )
    except Exception as exc:
        logger.error("Outreach generation error: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))

    if not result.get("success"):
        raise HTTPException(status_code=422, detail=result.get("error", "Outreach generation failed"))

    return OutreachResponse(
        company_id=result["company_id"],
        company_name=result.get("company_name"),
        contact_name=result.get("contact_name"),
        contact_title=result.get("contact_title"),
        contact_linkedin=result.get("contact_linkedin"),
        investor_key=result["investor_key"],
        output_format=result["output_format"],
        context_type=result.get("context_type"),
        subject=result.get("subject"),
        message=result.get("message"),
        generated_at=result["generated_at"],
        data_sources=result.get("data_sources", {}),
        success=result["success"],
        error=result.get("error"),
        stealth_mode=result.get("stealth_mode", False),
    )


@app.post("/api/outreach", response_model=OutreachResponse)
async def create_outreach_rewritten(request: OutreachRequest):
    return await _generate(request)


@app.post("/", response_model=OutreachResponse)
async def create_outreach_root(request: OutreachRequest):
    return await _generate(request)

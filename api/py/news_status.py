"""
Vercel Python Function: news job status read endpoints.

Serves:
  GET /api/news/status          — latest news_aggregator job
  GET /api/news/status/:job_id  — specific job by ID

Ports the handlers out of services/api.py (Railway FastAPI). The
POST /api/news/refresh trigger endpoint was removed in Phase 2.7 —
news refresh now runs on a GitHub Actions cron.

Mounted externally via vercel.json rewrites:
  /api/news/status           → /api/py/news_status
  /api/news/status/:job_id   → /api/py/news_status/:job_id
"""
from __future__ import annotations

import hmac
import logging
import os
import sys
from pathlib import Path
from typing import Optional

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from dotenv import load_dotenv
load_dotenv(override=False)

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from services.models import JobRunResponse
from services.logging_setup import setup_logging, get_logger
from services.auth import USE_CLERK_AUTH, verify_clerk_token

setup_logging(use_json=True)
logger = get_logger(__name__)

app = FastAPI(title="NEA News Status Function", version="3.0.0")

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


def _job_to_response(job) -> JobRunResponse:
    return JobRunResponse(
        id=job.id,
        agent_type=job.agent_type,
        status=job.status,
        created_at=job.created_at,
        started_at=job.started_at,
        completed_at=job.completed_at,
        error=job.error,
        result_summary=job.result_summary or {},
    )


async def _get_latest() -> JobRunResponse:
    from services.job_manager import get_job_manager

    job_manager = get_job_manager()
    job = job_manager.get_latest_job("news_aggregator")
    if not job:
        raise HTTPException(status_code=404, detail="No news jobs found")
    return _job_to_response(job)


async def _get_by_id(job_id: str) -> JobRunResponse:
    from services.job_manager import get_job_manager

    job_manager = get_job_manager()
    job = job_manager.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return _job_to_response(job)


# Rewritten paths (what the client hits)
@app.get("/api/news/status", response_model=JobRunResponse)
async def latest_status_rewritten():
    return await _get_latest()


@app.get("/api/news/status/{job_id}", response_model=JobRunResponse)
async def status_by_id_rewritten(job_id: str):
    return await _get_by_id(job_id)


# Native function paths — covers direct /api/py/news_status invocation
@app.get("/", response_model=JobRunResponse)
async def latest_status_root():
    return await _get_latest()


@app.get("/{job_id}", response_model=JobRunResponse)
async def status_by_id_root(job_id: str):
    return await _get_by_id(job_id)

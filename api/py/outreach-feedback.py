"""
Vercel Python Function: outreach feedback persistence.

Mounted externally at /api/outreach/feedback via vercel.json rewrites.
"""
from __future__ import annotations

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

from services.models import OutreachFeedbackRequest, OutreachFeedbackResponse

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="NEA Outreach Feedback Function", version="2.4.0")

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


@app.middleware("http")
async def require_api_key(request: Request, call_next):
    if NEA_API_KEY and request.method == "POST":
        provided = request.headers.get("x-nea-key", "")
        if not hmac.compare_digest(provided, NEA_API_KEY):
            return JSONResponse(status_code=401, content={"detail": "Missing or invalid X-NEA-Key"})
    return await call_next(request)


def _save(request: OutreachFeedbackRequest) -> OutreachFeedbackResponse:
    from services.feedback import save_feedback, FeedbackRecord, PROMOTABLE_STATUSES

    if request.approval_status == "edited" and not request.edited_message:
        raise HTTPException(
            status_code=422, detail="edited_message is required when approval_status is 'edited'"
        )

    record = FeedbackRecord(
        outreach_id=request.outreach_id,
        investor_key=request.investor_key,
        company_id=request.company_id,
        context_type=request.context_type,
        original_message=request.original_message,
        edited_message=request.edited_message,
        approval_status=request.approval_status,
        investor_notes=request.investor_notes,
    )

    try:
        record_id = save_feedback(record)
    except Exception as exc:
        logger.error("Failed to save outreach feedback: %s", exc)
        raise HTTPException(status_code=500, detail="Failed to save feedback")

    return OutreachFeedbackResponse(
        id=record_id,
        approval_status=request.approval_status,
        promoted=request.approval_status in PROMOTABLE_STATUSES,
    )


@app.post("/api/outreach/feedback", response_model=OutreachFeedbackResponse)
async def create_feedback_rewritten(request: OutreachFeedbackRequest):
    return _save(request)


@app.post("/", response_model=OutreachFeedbackResponse)
async def create_feedback_root(request: OutreachFeedbackRequest):
    return _save(request)

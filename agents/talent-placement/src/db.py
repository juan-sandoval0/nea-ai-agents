"""Supabase persistence layer — audit log and match storage."""
from __future__ import annotations

import json
import os

from dotenv import load_dotenv
from supabase import create_client, Client

from .models import Employee, Match

load_dotenv()

_client: Client | None = None


def _get() -> Client:
    global _client
    if _client is None:
        _client = create_client(
            os.environ["SUPABASE_URL"],
            os.environ["SUPABASE_SERVICE_KEY"],
        )
    return _client


def log_action(
    action: str,
    employee_name: str,
    company_name: str,
    details: dict,
) -> None:
    """Insert a row into talent_audit_log."""
    _get().table("talent_audit_log").insert({
        "action": action,
        "employee_name": employee_name,
        "company_name": company_name,
        "details": details,
    }).execute()


def save_match(employee: Employee, match: Match, status: str) -> None:
    """Insert a row into talent_matches."""
    _get().table("talent_matches").insert({
        "employee_id": employee.id,
        "employee_name": employee.name,
        "employee_title": employee.title,
        "employee_company": employee.company,
        "destination_id": match.destination.id,
        "destination_company": match.destination.company,
        "destination_role": match.destination.role,
        "score": match.score,
        "functional_skill": match.functional_skill,
        "seniority": match.seniority,
        "transition_pattern": match.transition_pattern,
        "stage_fit": match.stage_fit,
        "domain_overlap": match.domain_overlap,
        "reasoning": match.reasoning,
        "partner_notes": match.partner_notes,
        "status": status,
        "employee_json": json.loads(employee.model_dump_json()),
        "destination_json": json.loads(match.destination.model_dump_json()),
    }).execute()

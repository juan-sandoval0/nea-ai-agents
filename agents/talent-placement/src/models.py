from __future__ import annotations
from pydantic import BaseModel


class Employee(BaseModel):
    id: str
    name: str
    title: str | None = None
    company: str
    linkedin_url: str | None = None
    email: str | None = None
    is_founder: bool = False
    is_executive: bool = False
    start_date: str | None = None
    tenure_years: float | None = None


class Destination(BaseModel):
    id: str
    type: str  # "job_req" | "warm_network"
    company: str
    role: str
    description: str | None = None
    location: str | None = None
    url: str | None = None
    contact_name: str | None = None
    contact_email: str | None = None


class Match(BaseModel):
    employee: Employee
    destination: Destination
    score: float  # 0.0–1.0 composite
    reasoning: str
    functional_skill: int | None = None  # 0-100
    seniority: int | None = None         # 0-100
    stage_fit: int | None = None         # 0-100
    domain_overlap: int | None = None    # 0-100
    partner_notes: str | None = None
    approved: bool = False

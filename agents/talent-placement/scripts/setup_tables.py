"""Create talent_audit_log and talent_matches in Supabase.

If SUPABASE_ACCESS_TOKEN is set in .env, runs the DDL via the Supabase
Management API automatically. Otherwise prints the SQL so you can paste it
into the Supabase dashboard SQL editor (Database → SQL Editor → New query).
"""
from __future__ import annotations

import os
import sys

import requests
from dotenv import load_dotenv

load_dotenv()

TABLES_SQL = """
-- Talent placement agent: audit log
CREATE TABLE IF NOT EXISTS talent_audit_log (
    id          bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    created_at  timestamptz DEFAULT now(),
    action      text        NOT NULL,
    employee_name text      NOT NULL,
    company_name  text      NOT NULL,
    details     jsonb
);

-- Talent placement agent: partner-reviewed matches
CREATE TABLE IF NOT EXISTS talent_matches (
    id                  bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    created_at          timestamptz DEFAULT now(),
    employee_id         text        NOT NULL,
    employee_name       text        NOT NULL,
    employee_title      text,
    employee_company    text        NOT NULL,
    destination_id      text        NOT NULL,
    destination_company text        NOT NULL,
    destination_role    text        NOT NULL,
    score               float8      NOT NULL,
    functional_skill    int,
    seniority           int,
    transition_pattern  int,
    stage_fit           int,
    domain_overlap      int,
    reasoning           text,
    partner_notes       text,
    status              text        NOT NULL DEFAULT 'pending',
    employee_json       jsonb       NOT NULL,
    destination_json    jsonb       NOT NULL
);
""".strip()


def _run_via_management_api(token: str, supabase_url: str) -> None:
    # Extract project ref from https://<ref>.supabase.co
    ref = supabase_url.split("//")[1].split(".")[0]
    endpoint = f"https://api.supabase.com/v1/projects/{ref}/database/query"
    resp = requests.post(
        endpoint,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
        json={"query": TABLES_SQL},
        timeout=30,
    )
    if resp.ok:
        print("Tables created (or already exist).")
    else:
        print(f"Management API error {resp.status_code}: {resp.text}", file=sys.stderr)
        sys.exit(1)


def main() -> None:
    supabase_url = os.environ.get("SUPABASE_URL")
    if not supabase_url:
        print("SUPABASE_URL not set in .env", file=sys.stderr)
        sys.exit(1)

    token = os.environ.get("SUPABASE_ACCESS_TOKEN")
    if token:
        print(f"Running via Management API (project: {supabase_url.split('//')[1].split('.')[0]})...")
        _run_via_management_api(token, supabase_url)
    else:
        print("SUPABASE_ACCESS_TOKEN not set — paste the SQL below into the Supabase SQL editor.")
        print("(Dashboard → Database → SQL Editor → New query)\n")
        print(TABLES_SQL)


if __name__ == "__main__":
    main()

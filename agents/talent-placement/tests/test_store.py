"""Tests for store.init_db, log_match, get_approved_matches."""
import sqlite3
from pathlib import Path

from src.models import Employee, Destination, Match
from src.store import init_db, log_match, get_approved_matches


def _make_match(approved: bool = True, score: float = 0.9) -> Match:
    return Match(
        employee=Employee(id="emp-1", name="Alice", title="Engineer", company="OldCo"),
        destination=Destination(id="dest-1", type="job_req", company="NewCo", role="Senior Engineer"),
        score=score,
        reasoning="Strong fit.",
        approved=approved,
    )


def test_init_db_creates_table(tmp_path):
    db = tmp_path / "test.db"
    init_db(db)
    with sqlite3.connect(db) as conn:
        tables = conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    assert ("matches",) in tables


def test_init_db_idempotent(tmp_path):
    db = tmp_path / "test.db"
    init_db(db)
    init_db(db)  # should not raise


def test_log_match_inserts_row(tmp_path):
    db = tmp_path / "test.db"
    init_db(db)
    log_match(_make_match(), db_path=db)
    with sqlite3.connect(db) as conn:
        count = conn.execute("SELECT COUNT(*) FROM matches").fetchone()[0]
    assert count == 1


def test_log_match_stores_fields(tmp_path):
    db = tmp_path / "test.db"
    init_db(db)
    match = _make_match(score=0.75)
    match.partner_notes = "Great candidate"
    log_match(match, db_path=db)
    with sqlite3.connect(db) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT * FROM matches").fetchone()
    assert row["employee_name"] == "Alice"
    assert row["destination_company"] == "NewCo"
    assert row["score"] == 0.75
    assert row["partner_notes"] == "Great candidate"
    assert row["approved"] == 1


def test_get_approved_matches_returns_approved_only(tmp_path):
    db = tmp_path / "test.db"
    init_db(db)
    log_match(_make_match(approved=True), db_path=db)
    log_match(_make_match(approved=False), db_path=db)
    results = get_approved_matches(db_path=db)
    assert len(results) == 1
    assert results[0].approved is True


def test_get_approved_matches_returns_empty_when_no_db(tmp_path):
    db = tmp_path / "nonexistent.db"
    assert get_approved_matches(db_path=db) == []


def test_get_approved_matches_roundtrip(tmp_path):
    db = tmp_path / "test.db"
    init_db(db)
    original = _make_match()
    original.partner_notes = "Good fit"
    log_match(original, db_path=db)
    results = get_approved_matches(db_path=db)
    assert len(results) == 1
    assert results[0].employee.name == "Alice"
    assert results[0].destination.role == "Senior Engineer"
    assert results[0].partner_notes == "Good fit"

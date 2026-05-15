"""Tests for roster.load_job_reqs."""
import csv
from pathlib import Path

import pytest

from src.roster import load_job_reqs


def _write_csv(path: Path, rows: list[dict], fieldnames: list[str]) -> None:
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def test_happy_path(tmp_path):
    csv_file = tmp_path / "jobs.csv"
    _write_csv(csv_file, [
        {"company": "Acme", "title": "Engineer", "location": "NYC", "url": "https://acme.com/jobs/1"},
        {"company": "Beta", "title": "Designer", "location": "", "url": ""},
    ], ["company", "title", "location", "url"])

    results = load_job_reqs(csv_file)
    assert len(results) == 2
    assert results[0].company == "Acme"
    assert results[0].role == "Engineer"
    assert results[0].location == "NYC"
    assert results[0].url == "https://acme.com/jobs/1"
    assert results[1].location is None
    assert results[1].url is None


def test_strips_whitespace(tmp_path):
    csv_file = tmp_path / "jobs.csv"
    _write_csv(csv_file, [
        {"company": "  Acme  ", "title": "  Engineer  "},
    ], ["company", "title"])

    results = load_job_reqs(csv_file)
    assert results[0].company == "Acme"
    assert results[0].role == "Engineer"


def test_missing_required_column_skipped(tmp_path):
    csv_file = tmp_path / "jobs.csv"
    # Only has 'company', missing 'title'
    with open(csv_file, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["company"])
        writer.writeheader()
        writer.writerow({"company": "Acme"})

    results = load_job_reqs(csv_file)
    assert results == []


def test_empty_file(tmp_path):
    csv_file = tmp_path / "jobs.csv"
    _write_csv(csv_file, [], ["company", "title"])
    assert load_job_reqs(csv_file) == []


def test_missing_file_returns_empty():
    assert load_job_reqs(Path("/nonexistent/path.csv")) == []


def test_each_row_gets_unique_id(tmp_path):
    csv_file = tmp_path / "jobs.csv"
    _write_csv(csv_file, [
        {"company": "Acme", "title": "Engineer"},
        {"company": "Acme", "title": "Engineer"},
    ], ["company", "title"])

    results = load_job_reqs(csv_file)
    assert results[0].id != results[1].id


def test_destination_type_is_job_req(tmp_path):
    csv_file = tmp_path / "jobs.csv"
    _write_csv(csv_file, [{"company": "Acme", "title": "Engineer"}], ["company", "title"])
    results = load_job_reqs(csv_file)
    assert results[0].type == "job_req"

"""Tests for scraper.py — HTTP calls mocked via patch on fetch_page."""
from __future__ import annotations

import csv
from pathlib import Path
from unittest.mock import MagicMock, patch, call

from src.scraper import fetch_page, scrape, scrape_if_stale, OUTPUT


def _mock_response(data: dict, status: int = 200) -> MagicMock:
    resp = MagicMock()
    resp.status_code = status
    resp.json.return_value = data
    resp.raise_for_status = MagicMock()
    return resp


def _job(company: str, title: str, locations: list[str] = None, url: str = "") -> dict:
    return {"companyName": company, "title": title, "locations": locations or [], "url": url}


# ---------------------------------------------------------------------------
# fetch_page
# ---------------------------------------------------------------------------

def test_fetch_page_first_page_no_sequence():
    resp = _mock_response({"jobs": [], "meta": {}})
    session = MagicMock()
    session.post.return_value = resp
    fetch_page(session, None)
    body = session.post.call_args[1]["json"]
    assert "sequence" not in body["meta"]
    assert body["meta"]["size"] == 100


def test_fetch_page_with_sequence():
    resp = _mock_response({"jobs": [], "meta": {}})
    session = MagicMock()
    session.post.return_value = resp
    fetch_page(session, "tok-xyz")
    body = session.post.call_args[1]["json"]
    assert body["meta"]["sequence"] == "tok-xyz"


def test_fetch_page_raises_on_http_error():
    resp = MagicMock()
    resp.raise_for_status.side_effect = Exception("404")
    session = MagicMock()
    session.post.return_value = resp
    import pytest
    with pytest.raises(Exception):
        fetch_page(session, None)


# ---------------------------------------------------------------------------
# scrape
# ---------------------------------------------------------------------------

def test_scrape_writes_csv(tmp_path):
    jobs = [_job("Acme", "Engineer", ["New York"], "https://acme.com/jobs/1")]
    pages = [{"jobs": jobs, "meta": {}, "total": 1}]
    with patch("src.scraper.fetch_page", side_effect=pages), \
         patch("src.scraper.OUTPUT", tmp_path / "jobs.csv"):
        scrape()
    rows = list(csv.DictReader((tmp_path / "jobs.csv").open()))
    assert len(rows) == 1
    assert rows[0]["company"] == "Acme"
    assert rows[0]["title"] == "Engineer"
    assert rows[0]["location"] == "New York"
    assert rows[0]["url"] == "https://acme.com/jobs/1"


def test_scrape_paginates(tmp_path):
    page1 = {"jobs": [_job("Co1", "Role1")], "meta": {"sequence": "tok2"}, "total": 2}
    page2 = {"jobs": [_job("Co2", "Role2")], "meta": {}, "total": 2}
    with patch("src.scraper.fetch_page", side_effect=[page1, page2]), \
         patch("src.scraper.OUTPUT", tmp_path / "jobs.csv"):
        scrape()
    rows = list(csv.DictReader((tmp_path / "jobs.csv").open()))
    assert len(rows) == 2


def test_scrape_stops_on_empty_jobs(tmp_path):
    page1 = {"jobs": [_job("Co1", "Role1")], "meta": {"sequence": "tok2"}, "total": 99}
    page2 = {"jobs": [], "meta": {}, "total": 99}
    with patch("src.scraper.fetch_page", side_effect=[page1, page2]), \
         patch("src.scraper.OUTPUT", tmp_path / "jobs.csv"):
        scrape()
    rows = list(csv.DictReader((tmp_path / "jobs.csv").open()))
    assert len(rows) == 1


def test_scrape_multiple_locations_joined(tmp_path):
    jobs = [_job("Co", "Role", ["NYC", "SF", "Remote"])]
    with patch("src.scraper.fetch_page", return_value={"jobs": jobs, "meta": {}, "total": 1}), \
         patch("src.scraper.OUTPUT", tmp_path / "jobs.csv"):
        scrape()
    rows = list(csv.DictReader((tmp_path / "jobs.csv").open()))
    assert rows[0]["location"] == "NYC; SF; Remote"


def test_scrape_creates_output_directory(tmp_path):
    nested = tmp_path / "a" / "b" / "jobs.csv"
    jobs = [_job("Co", "Role")]
    with patch("src.scraper.fetch_page", return_value={"jobs": jobs, "meta": {}, "total": 1}), \
         patch("src.scraper.OUTPUT", nested):
        scrape()
    assert nested.exists()


# ---------------------------------------------------------------------------
# scrape_if_stale
# ---------------------------------------------------------------------------

def test_scrape_if_stale_skips_when_fresh(tmp_path):
    csv_file = tmp_path / "jobs.csv"
    csv_file.write_text("company,title,location,url\n")
    # mtime is now — well within 7-day window
    with patch("src.scraper.OUTPUT", csv_file), \
         patch("src.scraper.scrape") as mock_scrape:
        scrape_if_stale(max_age_days=7)
    mock_scrape.assert_not_called()


def test_scrape_if_stale_runs_when_old(tmp_path):
    csv_file = tmp_path / "jobs.csv"
    csv_file.write_text("company,title,location,url\n")
    import os, time as _time
    stale_mtime = _time.time() - 8 * 86400  # 8 days ago
    os.utime(csv_file, (stale_mtime, stale_mtime))
    with patch("src.scraper.OUTPUT", csv_file), \
         patch("src.scraper.scrape") as mock_scrape:
        scrape_if_stale(max_age_days=7)
    mock_scrape.assert_called_once()


def test_scrape_if_stale_runs_when_missing(tmp_path):
    csv_file = tmp_path / "jobs.csv"  # does not exist
    with patch("src.scraper.OUTPUT", csv_file), \
         patch("src.scraper.scrape") as mock_scrape:
        scrape_if_stale(max_age_days=7)
    mock_scrape.assert_called_once()

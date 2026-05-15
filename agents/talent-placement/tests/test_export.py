"""Tests for export.export_match."""
import json
from pathlib import Path
from unittest.mock import patch

from src.models import Employee, Destination, Match
from src.export import export_match


def _make_match() -> Match:
    return Match(
        employee=Employee(id="emp-1", name="Bob Smith", title="CTO", company="OldCo"),
        destination=Destination(id="dest-1", type="job_req", company="NewCo", role="VP Engineering"),
        score=0.88,
        reasoning="Excellent fit.",
        approved=True,
    )


def test_export_creates_file(tmp_path):
    match = _make_match()
    with patch("src.export._EXPORT_DIR", tmp_path):
        path = export_match(match)
    assert path.exists()


def test_export_file_is_valid_json(tmp_path):
    match = _make_match()
    with patch("src.export._EXPORT_DIR", tmp_path):
        path = export_match(match)
    data = json.loads(path.read_text())
    assert data["score"] == 0.88
    assert data["employee"]["name"] == "Bob Smith"
    assert data["destination"]["role"] == "VP Engineering"


def test_export_filename_contains_name_and_role(tmp_path):
    match = _make_match()
    with patch("src.export._EXPORT_DIR", tmp_path):
        path = export_match(match)
    assert "bob_smith" in path.name
    assert "vp_engineering" in path.name


def test_export_creates_directory_if_missing(tmp_path):
    match = _make_match()
    nested = tmp_path / "a" / "b" / "c"
    with patch("src.export._EXPORT_DIR", nested):
        path = export_match(match)
    assert path.exists()

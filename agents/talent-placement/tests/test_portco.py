"""Tests for portco.load_portcos."""
import csv
from pathlib import Path

from src.portco import load_portcos


def _write_portco_csv(path: Path, rows: list[dict]) -> None:
    fieldnames = ["Company Name", "Company ID", "Website URL", "Stage", "Headcount"]
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def test_happy_path(tmp_path):
    csv_file = tmp_path / "portcos.csv"
    _write_portco_csv(csv_file, [
        {"Company Name": "Stripe", "Company ID": "123", "Website URL": "https://stripe.com", "Stage": "series_d", "Headcount": "1000"},
    ])
    results = load_portcos(csv_file)
    assert len(results) == 1
    assert results[0].name == "Stripe"
    assert results[0].harmonic_id == "123"
    assert results[0].domain == "stripe.com"
    assert results[0].stage == "series_d"
    assert results[0].headcount == "1000"


def test_domain_stripping(tmp_path):
    csv_file = tmp_path / "portcos.csv"
    _write_portco_csv(csv_file, [
        {"Company Name": "A", "Company ID": "1", "Website URL": "https://www.a.com/", "Stage": "", "Headcount": ""},
        {"Company Name": "B", "Company ID": "2", "Website URL": "http://b.com", "Stage": "", "Headcount": ""},
        {"Company Name": "C", "Company ID": "3", "Website URL": "www.c.com", "Stage": "", "Headcount": ""},
    ])
    results = load_portcos(csv_file)
    domains = {r.name: r.domain for r in results}
    assert domains["A"] == "a.com"
    assert domains["B"] == "b.com"
    assert domains["C"] == "c.com"


def test_skips_rows_missing_name_or_id(tmp_path):
    csv_file = tmp_path / "portcos.csv"
    _write_portco_csv(csv_file, [
        {"Company Name": "", "Company ID": "1", "Website URL": "", "Stage": "", "Headcount": ""},
        {"Company Name": "Acme", "Company ID": "", "Website URL": "", "Stage": "", "Headcount": ""},
        {"Company Name": "Good", "Company ID": "3", "Website URL": "", "Stage": "", "Headcount": ""},
    ])
    results = load_portcos(csv_file)
    assert len(results) == 1
    assert results[0].name == "Good"


def test_sorted_alphabetically(tmp_path):
    csv_file = tmp_path / "portcos.csv"
    _write_portco_csv(csv_file, [
        {"Company Name": "Zebra", "Company ID": "1", "Website URL": "", "Stage": "", "Headcount": ""},
        {"Company Name": "acme", "Company ID": "2", "Website URL": "", "Stage": "", "Headcount": ""},
        {"Company Name": "Beta", "Company ID": "3", "Website URL": "", "Stage": "", "Headcount": ""},
    ])
    results = load_portcos(csv_file)
    names = [r.name for r in results]
    assert names == ["acme", "Beta", "Zebra"]


def test_bom_encoding(tmp_path):
    csv_file = tmp_path / "portcos.csv"
    fieldnames = ["Company Name", "Company ID", "Website URL", "Stage", "Headcount"]
    with open(csv_file, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerow({"Company Name": "Stripe", "Company ID": "999", "Website URL": "", "Stage": "", "Headcount": ""})
    results = load_portcos(csv_file)
    assert len(results) == 1
    assert results[0].name == "Stripe"

"""Tests for harmonic.py — all HTTP calls are mocked via patch('src.harmonic._get')."""
from __future__ import annotations

from datetime import date
from unittest.mock import MagicMock, patch, call

import pytest

from src.harmonic import (
    _compute_tenure_years,
    _parse_person,
    _parse_destination_person,
    find_company_id,
    get_company_employees,
    get_person_by_linkedin,
    find_destinations,
)
from src.models import Employee


# ---------------------------------------------------------------------------
# _compute_tenure_years
# ---------------------------------------------------------------------------

def test_tenure_none_when_no_start_date():
    assert _compute_tenure_years(None) is None


def test_tenure_returns_float_for_valid_date():
    with patch("src.harmonic.date") as mock_date:
        mock_date.today.return_value = date(2026, 1, 1)
        mock_date.side_effect = lambda *a, **k: date(*a, **k)
        result = _compute_tenure_years("2024-01")
    assert isinstance(result, float)
    assert result == pytest.approx(2.0, abs=0.1)


def test_tenure_year_only():
    with patch("src.harmonic.date") as mock_date:
        mock_date.today.return_value = date(2026, 1, 1)
        mock_date.side_effect = lambda *a, **k: date(*a, **k)
        result = _compute_tenure_years("2021")
    assert isinstance(result, float)
    assert result > 0


def test_tenure_returns_none_for_malformed():
    assert _compute_tenure_years("not-a-date") is None


# ---------------------------------------------------------------------------
# _parse_person
# ---------------------------------------------------------------------------

def _person_payload(
    name="Alice Smith",
    title="CTO",
    role_type="EXECUTIVE",
    is_current=True,
    linkedin_url="https://linkedin.com/in/alice",
    person_id="42",
    start_date="2022-06",
) -> dict:
    return {
        "id": person_id,
        "full_name": name,
        "socials": {"LINKEDIN": {"url": linkedin_url}},
        "experience": [
            {
                "title": title,
                "role_type": role_type,
                "is_current_position": is_current,
                "start_date": start_date,
            }
        ],
    }


def test_parse_person_basic():
    emp = _parse_person(_person_payload(), "Acme")
    assert emp.name == "Alice Smith"
    assert emp.title == "CTO"
    assert emp.company == "Acme"
    assert emp.linkedin_url == "https://linkedin.com/in/alice"
    assert emp.id == "42"


def test_parse_person_founder_flag():
    emp = _parse_person(_person_payload(role_type="FOUNDER"), "Acme")
    assert emp.is_founder is True
    assert emp.is_executive is True


def test_parse_person_executive_flag():
    emp = _parse_person(_person_payload(role_type="EXECUTIVE"), "Acme")
    assert emp.is_founder is False
    assert emp.is_executive is True


def test_parse_person_regular_employee():
    emp = _parse_person(_person_payload(role_type="EMPLOYEE"), "Acme")
    assert emp.is_founder is False
    assert emp.is_executive is False


def test_parse_person_no_current_position():
    payload = {
        "id": "1",
        "full_name": "Bob",
        "socials": {},
        "experience": [{"title": "Old Role", "role_type": "EMPLOYEE", "is_current_position": False}],
    }
    emp = _parse_person(payload, "Acme")
    assert emp.title is None
    assert emp.is_founder is False


def test_parse_person_falls_back_to_entity_urn():
    payload = {
        "full_name": "Carol",
        "entity_urn": "urn:harmonic:person:99",
        "socials": {},
        "experience": [],
    }
    emp = _parse_person(payload, "Acme")
    assert emp.id == "99"


def test_parse_person_no_linkedin():
    payload = _person_payload()
    payload["socials"] = {}
    emp = _parse_person(payload, "Acme")
    assert emp.linkedin_url is None


# ---------------------------------------------------------------------------
# _parse_destination_person
# ---------------------------------------------------------------------------

def test_parse_destination_person_happy_path():
    payload = {
        "full_name": "Dave",
        "socials": {"LINKEDIN": {"url": "https://linkedin.com/in/dave"}},
        "experience": [
            {"is_current_position": True, "company": {"name": "NewCo"}, "title": "VP Eng"},
        ],
    }
    result = _parse_destination_person(payload)
    assert result["name"] == "Dave"
    assert result["current_company"] == "NewCo"
    assert result["title"] == "VP Eng"
    assert result["linkedin_url"] == "https://linkedin.com/in/dave"


def test_parse_destination_person_company_as_string():
    payload = {
        "full_name": "Eve",
        "socials": {},
        "experience": [
            {"is_current_position": True, "company": None, "company_name": "SomeCo", "title": "Lead"},
        ],
    }
    result = _parse_destination_person(payload)
    assert result["current_company"] == "SomeCo"


def test_parse_destination_person_no_experience():
    payload = {"full_name": "Frank", "socials": {}, "experience": []}
    result = _parse_destination_person(payload)
    assert result["name"] == "Frank"
    assert result["current_company"] is None
    assert result["title"] is None


# ---------------------------------------------------------------------------
# find_company_id
# ---------------------------------------------------------------------------

def test_find_company_id_returns_id():
    mock_data = {"results": [{"type": "COMPANY", "entity_urn": "urn:harmonic:company:123"}]}
    with patch("src.harmonic._get", return_value=mock_data):
        result = find_company_id("Stripe")
    assert result == "123"


def test_find_company_id_skips_non_company():
    mock_data = {"results": [{"type": "PERSON", "entity_urn": "urn:harmonic:person:99"}]}
    with patch("src.harmonic._get", return_value=mock_data):
        result = find_company_id("someone")
    assert result is None


def test_find_company_id_empty_results():
    with patch("src.harmonic._get", return_value={"results": []}):
        assert find_company_id("Unknown") is None


def test_find_company_id_api_error():
    with patch("src.harmonic._get", side_effect=Exception("network error")):
        assert find_company_id("Stripe") is None


# ---------------------------------------------------------------------------
# get_company_employees
# ---------------------------------------------------------------------------

def _company_payload(people: list[dict], name: str = "Acme") -> dict:
    return {"name": name, "people": people}


def _person_record(person_id: str, role_type: str = "EMPLOYEE", is_current: bool = True) -> dict:
    return {
        "person": f"urn:harmonic:person:{person_id}",
        "role_type": role_type,
        "is_current_position": is_current,
    }


def test_get_company_employees_numeric_id_skips_lookup():
    company_data = _company_payload([_person_record("1")])
    person_data = _person_payload(person_id="1")
    with patch("src.harmonic._get", side_effect=[company_data, person_data]) as mock_get:
        result = get_company_employees("99999")
    # First call should be /companies/99999, not typeahead
    assert "/companies/99999" in mock_get.call_args_list[0][0][0]


def test_get_company_employees_filters_non_current():
    people = [
        _person_record("1", is_current=True),
        _person_record("2", is_current=False),
    ]
    company_data = _company_payload(people)
    person_data = _person_payload(person_id="1")
    with patch("src.harmonic._get", side_effect=[company_data, person_data]):
        result = get_company_employees("111")
    assert len(result) == 1


def test_get_company_employees_founders_sorted_first():
    people = [
        _person_record("1", role_type="EMPLOYEE"),
        _person_record("2", role_type="FOUNDER"),
        _person_record("3", role_type="EXECUTIVE"),
    ]
    company_data = _company_payload(people)
    founder_data = _person_payload(person_id="2", role_type="FOUNDER", name="Founder")
    exec_data = _person_payload(person_id="3", role_type="EXECUTIVE", name="Exec")
    emp_data = _person_payload(person_id="1", role_type="EMPLOYEE", name="Employee")
    with patch("src.harmonic._get", side_effect=[company_data, founder_data, exec_data, emp_data]):
        result = get_company_employees("111")
    assert result[0].is_founder is True
    assert result[1].is_executive is True


def test_get_company_employees_deduplicates():
    people = [_person_record("1"), _person_record("1")]  # same ID twice
    company_data = _company_payload(people)
    person_data = _person_payload(person_id="1")
    with patch("src.harmonic._get", side_effect=[company_data, person_data]):
        result = get_company_employees("111")
    assert len(result) == 1


def test_get_company_employees_respects_limit():
    people = [_person_record(str(i)) for i in range(10)]
    company_data = _company_payload(people)
    person_payloads = [_person_payload(person_id=str(i), name=f"Person {i}") for i in range(10)]
    with patch("src.harmonic._get", side_effect=[company_data] + person_payloads):
        result = get_company_employees("111", limit=3)
    assert len(result) == 3


def test_get_company_employees_returns_empty_on_company_fetch_error():
    with patch("src.harmonic._get", side_effect=Exception("404")):
        result = get_company_employees("111")
    assert result == []


# ---------------------------------------------------------------------------
# get_person_by_linkedin
# ---------------------------------------------------------------------------

def test_get_person_by_linkedin_happy_path():
    typeahead = {"results": [{"type": "PERSON", "entity_urn": "urn:harmonic:person:77"}]}
    person_data = _person_payload(person_id="77", name="Grace")
    person_data["experience"][0]["company"] = {"name": "TechCo"}
    with patch("src.harmonic._get", side_effect=[typeahead, person_data]):
        result = get_person_by_linkedin("https://linkedin.com/in/grace")
    assert result is not None
    assert result.name == "Grace"


def test_get_person_by_linkedin_no_match():
    typeahead = {"results": [{"type": "COMPANY", "entity_urn": "urn:harmonic:company:1"}]}
    with patch("src.harmonic._get", return_value=typeahead):
        result = get_person_by_linkedin("https://linkedin.com/in/nobody")
    assert result is None


def test_get_person_by_linkedin_api_error():
    with patch("src.harmonic._get", side_effect=Exception("timeout")):
        result = get_person_by_linkedin("https://linkedin.com/in/someone")
    assert result is None


# ---------------------------------------------------------------------------
# find_destinations
# ---------------------------------------------------------------------------

def _make_employee(emp_id: str = "10", title: str = "CTO", company: str = "OldCo") -> Employee:
    return Employee(id=emp_id, name="Alice", title=title, company=company)


def test_find_destinations_similar_endpoint_success():
    similar_data = {
        "results": [
            {"full_name": "Bob", "socials": {}, "experience": [
                {"is_current_position": True, "company": {"name": "NewCo"}, "title": "CTO"}
            ]}
        ]
    }
    with patch("src.harmonic._get", return_value=similar_data):
        results = find_destinations(_make_employee())
    assert len(results) == 1
    assert results[0]["name"] == "Bob"


def test_find_destinations_falls_back_to_typeahead():
    typeahead = {"results": [{"type": "PERSON", "entity_urn": "urn:harmonic:person:55"}]}
    person_data = {
        "full_name": "Carol",
        "socials": {},
        "experience": [{"is_current_position": True, "company": {"name": "DiffCo"}, "title": "VP"}],
    }
    with patch("src.harmonic._get", side_effect=[Exception("404"), typeahead, person_data]):
        results = find_destinations(_make_employee())
    assert len(results) == 1
    assert results[0]["name"] == "Carol"


def _typeahead_with_ids(*person_ids: str) -> dict:
    return {
        "results": [
            {"type": "PERSON", "entity_urn": f"urn:harmonic:person:{pid}"}
            for pid in person_ids
        ]
    }


def _person_dict(name: str, company: str, title: str, linkedin: str | None = None) -> dict:
    return {
        "full_name": name,
        "socials": {"LINKEDIN": {"url": linkedin}} if linkedin else {},
        "experience": [{"is_current_position": True, "company": {"name": company}, "title": title}],
    }


def test_find_destinations_filters_same_company():
    # Filtering only applies in the typeahead fallback path
    with patch("src.harmonic._get", side_effect=[
        Exception("404"),                                          # similar endpoint fails
        _typeahead_with_ids("1"),                                  # typeahead returns one person
        _person_dict("Dave", "OldCo", "CTO"),                     # person is at same company
    ]):
        results = find_destinations(_make_employee(company="OldCo"))
    assert results == []


def test_find_destinations_filters_placeholder_names():
    with patch("src.harmonic._get", side_effect=[
        Exception("404"),
        _typeahead_with_ids("1", "2", "3"),
        _person_dict("Co-Founder", "SomeCo", "Founder"),           # placeholder name → filtered
        _person_dict("Manager", "AnotherCo", "Manager"),           # placeholder name → filtered
        _person_dict("Alice Real", "RealCo", "Lead"),              # real name → kept
    ]):
        results = find_destinations(_make_employee())
    assert len(results) == 1
    assert results[0]["name"] == "Alice Real"


def test_find_destinations_dedupes_by_linkedin():
    with patch("src.harmonic._get", side_effect=[
        Exception("404"),
        _typeahead_with_ids("1", "2"),
        _person_dict("Bob One", "Co1", "CTO", "https://li.com/bob"),
        _person_dict("Bob Two", "Co2", "CTO", "https://li.com/bob"),  # same LinkedIn → dedupe
    ]):
        results = find_destinations(_make_employee())
    assert len(results) == 1


def test_find_destinations_no_title_returns_empty_without_crash():
    emp = Employee(id="1", name="Alice", title=None, company="OldCo")
    similar_response = {"results": []}
    with patch("src.harmonic._get", side_effect=[similar_response]):
        results = find_destinations(emp)
    assert results == []

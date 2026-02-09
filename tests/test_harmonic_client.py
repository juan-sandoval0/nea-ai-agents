"""
Unit Tests for Harmonic API Client
==================================
Tests for response parsing, error handling, and edge cases.

Run with:
    pytest tests/test_harmonic_client.py -v
"""

import pytest
from unittest.mock import Mock, patch, MagicMock
import requests

from core.clients.harmonic import (
    HarmonicClient,
    HarmonicCompany,
    HarmonicPerson,
    HarmonicAPIError,
)


# =============================================================================
# FIXTURES
# =============================================================================

@pytest.fixture
def mock_api_key():
    """Provide a mock API key."""
    return "test_api_key_12345"


@pytest.fixture
def harmonic_client(mock_api_key):
    """Create a HarmonicClient with mocked API key."""
    with patch.dict("os.environ", {"HARMONIC_API_KEY": mock_api_key}):
        return HarmonicClient(api_key=mock_api_key)


# =============================================================================
# HARMONIC COMPANY PARSING TESTS
# =============================================================================

class TestHarmonicCompanyParsing:
    """Tests for HarmonicCompany.from_api_response."""

    def test_name_null_becomes_unknown(self):
        """When API returns name: null, it should become 'Unknown'."""
        data = {
            "id": "12345",
            "name": None,  # null in API response
            "description": "A test company",
        }
        company = HarmonicCompany.from_api_response(data)
        assert company.name == "Unknown"

    def test_name_empty_string_becomes_unknown(self):
        """When API returns empty string name, it should become 'Unknown'."""
        data = {
            "id": "12345",
            "name": "",
            "description": "A test company",
        }
        company = HarmonicCompany.from_api_response(data)
        assert company.name == "Unknown"

    def test_valid_name_preserved(self):
        """Valid company names should be preserved."""
        data = {
            "id": "12345",
            "name": "Stripe",
            "description": "Payments infrastructure",
        }
        company = HarmonicCompany.from_api_response(data)
        assert company.name == "Stripe"

    def test_missing_optional_fields_use_defaults(self):
        """Missing optional fields should use safe defaults."""
        data = {
            "id": "12345",
            "name": "TestCo",
        }
        company = HarmonicCompany.from_api_response(data)

        assert company.description is None
        assert company.domain is None
        assert company.headcount is None
        assert company.funding_total is None
        assert company.founded_year is None
        assert company.investors == []
        assert company.tags == []

    def test_nested_website_parsing(self):
        """Website nested object should be parsed correctly."""
        data = {
            "id": "12345",
            "name": "TestCo",
            "website": {
                "domain": "testco.com",
                "url": "https://testco.com",
            }
        }
        company = HarmonicCompany.from_api_response(data)
        assert company.domain == "testco.com"
        assert company.website_url == "https://testco.com"

    def test_website_null_handled(self):
        """Null website object should be handled safely."""
        data = {
            "id": "12345",
            "name": "TestCo",
            "website": None,
        }
        company = HarmonicCompany.from_api_response(data)
        assert company.domain is None
        assert company.website_url is None

    def test_funding_parsing(self):
        """Funding information should be parsed correctly."""
        data = {
            "id": "12345",
            "name": "TestCo",
            "funding": {
                "funding_total": 50000000,
                "funding_stage": "Series B",
                "last_funding_at": "2024-01-15",
                "last_funding_total": 20000000,
                "investors": [
                    {"name": "Sequoia Capital"},
                    {"name": "Andreessen Horowitz"},
                ],
                "funding_rounds": [
                    {
                        "date": "2024-01-15",
                        "amount": 20000000,
                        "investors": [{"name": "Sequoia Capital"}],
                    }
                ],
            }
        }
        company = HarmonicCompany.from_api_response(data)

        assert company.funding_total == 50000000
        assert company.funding_stage == "Series B"
        assert company.funding_last_date == "2024-01-15"
        assert company.funding_last_amount == 20000000
        assert "Sequoia Capital" in company.investors
        assert "Andreessen Horowitz" in company.investors

    def test_traction_metrics_parsing(self):
        """Traction metrics should be parsed correctly."""
        data = {
            "id": "12345",
            "name": "TestCo",
            "headcount": 500,
            "web_traffic": 1000000,
            "traction_metrics": {
                "headcount": {
                    "90d_ago": {
                        "percent_change": 15.5,
                    }
                },
                "web_traffic": {
                    "30d_ago": {
                        "percent_change": -5.2,
                    }
                }
            }
        }
        company = HarmonicCompany.from_api_response(data)

        assert company.headcount == 500
        assert company.headcount_change_90d == 15.5
        assert company.web_traffic_change_30d == -5.2

    def test_location_parsing(self):
        """Location should be parsed correctly."""
        data = {
            "id": "12345",
            "name": "TestCo",
            "location": {
                "city": "San Francisco",
                "state": "California",
                "country": "United States",
            }
        }
        company = HarmonicCompany.from_api_response(data)

        assert company.city == "San Francisco"
        assert company.state == "California"
        assert company.country == "United States"

    def test_tags_parsing(self):
        """Tags should be parsed from tags_v2 array."""
        data = {
            "id": "12345",
            "name": "TestCo",
            "tags_v2": [
                {"display_value": "FinTech"},
                {"display_value": "Payments"},
                {"display_value": "B2B"},
            ]
        }
        company = HarmonicCompany.from_api_response(data)

        assert "FinTech" in company.tags
        assert "Payments" in company.tags
        assert "B2B" in company.tags

    def test_entity_urn_id_extraction(self):
        """Company ID should be extracted from entity_urn if id is missing."""
        data = {
            "entity_urn": "urn:li:company:12345",
            "name": "TestCo",
        }
        company = HarmonicCompany.from_api_response(data)
        assert company.id == "12345"

    def test_linkedin_url_from_socials(self):
        """LinkedIn URL should be extracted from socials."""
        data = {
            "id": "12345",
            "name": "TestCo",
            "socials": {
                "LINKEDIN": {
                    "url": "https://linkedin.com/company/testco",
                }
            }
        }
        company = HarmonicCompany.from_api_response(data)
        assert company.linkedin_url == "https://linkedin.com/company/testco"


# =============================================================================
# HARMONIC PERSON PARSING TESTS
# =============================================================================

class TestHarmonicPersonParsing:
    """Tests for HarmonicPerson.from_api_response."""

    def test_name_parsing(self):
        """Person name should be parsed correctly."""
        data = {
            "id": "person123",
            "full_name": "John Doe",
        }
        person = HarmonicPerson.from_api_response(data)
        assert person.name == "John Doe"

    def test_name_fallback(self):
        """Name should fall back to 'name' field if full_name missing."""
        data = {
            "id": "person123",
            "name": "Jane Smith",
        }
        person = HarmonicPerson.from_api_response(data)
        assert person.name == "Jane Smith"

    def test_name_unknown_fallback(self):
        """Name should be 'Unknown' if no name fields present."""
        data = {
            "id": "person123",
        }
        person = HarmonicPerson.from_api_response(data)
        assert person.name == "Unknown"

    def test_current_position_parsing(self):
        """Current position should be extracted from experience."""
        data = {
            "id": "person123",
            "full_name": "John Doe",
            "experience": [
                {
                    "is_current_position": True,
                    "title": "CEO",
                    "company_name": "TestCo",
                    "role_type": "FOUNDER",
                    "start_date": "2020-01-01",
                },
                {
                    "is_current_position": False,
                    "title": "Engineer",
                    "company_name": "OldCo",
                },
            ]
        }
        person = HarmonicPerson.from_api_response(data)

        assert person.title == "CEO"
        assert person.current_company == "TestCo"
        assert person.is_founder is True
        assert person.is_executive is True
        assert person.start_date == "2020-01-01"


# =============================================================================
# HARMONIC CLIENT ERROR HANDLING TESTS
# =============================================================================

class TestHarmonicClientErrors:
    """Tests for error handling in HarmonicClient."""

    def test_missing_api_key_raises_error(self):
        """Creating client without API key should raise ValueError."""
        with patch.dict("os.environ", {}, clear=True):
            # Remove HARMONIC_API_KEY if present
            import os
            os.environ.pop("HARMONIC_API_KEY", None)

            with pytest.raises(ValueError, match="Harmonic API key required"):
                HarmonicClient()

    def test_401_unauthorized_error(self, harmonic_client):
        """401 response should raise HarmonicAPIError."""
        with patch.object(harmonic_client.session, "request") as mock_request:
            mock_response = Mock()
            mock_response.status_code = 401
            mock_response.headers = {}  # Required by resilience handler
            mock_request.return_value = mock_response

            with pytest.raises(HarmonicAPIError, match="Invalid API key"):
                harmonic_client._request("GET", "/test")

    def test_404_returns_empty_dict(self, harmonic_client):
        """404 response should return empty dict (not found is not an error)."""
        with patch.object(harmonic_client.session, "request") as mock_request:
            mock_response = Mock()
            mock_response.status_code = 404
            mock_response.headers = {}  # Required by resilience handler
            mock_request.return_value = mock_response

            result = harmonic_client._request("GET", "/test")
            assert result == {}

    def test_429_rate_limit_error(self, harmonic_client):
        """429 response should raise HarmonicAPIError after retries."""
        with patch.object(harmonic_client.session, "request") as mock_request, \
             patch("time.sleep"):  # Skip retry delays
            mock_response = Mock()
            mock_response.status_code = 429
            mock_response.headers = {"Retry-After": "60"}  # Required by resilience handler
            mock_request.return_value = mock_response

            with pytest.raises(HarmonicAPIError, match="Rate limit exceeded"):
                harmonic_client._request("GET", "/test")

    def test_timeout_error(self, harmonic_client):
        """Timeout should raise HarmonicAPIError after retries."""
        # Reset circuit breaker from previous tests
        harmonic_client._circuit_breaker.reset()
        with patch.object(harmonic_client.session, "request") as mock_request, \
             patch("time.sleep"):  # Skip retry delays
            mock_request.side_effect = requests.exceptions.Timeout()

            with pytest.raises(HarmonicAPIError, match="timed out"):
                harmonic_client._request("GET", "/test")

    def test_connection_error(self, harmonic_client):
        """Connection error should raise HarmonicAPIError after retries."""
        # Reset circuit breaker from previous tests
        harmonic_client._circuit_breaker.reset()
        with patch.object(harmonic_client.session, "request") as mock_request, \
             patch("time.sleep"):  # Skip retry delays
            mock_request.side_effect = requests.exceptions.ConnectionError("Network error")

            with pytest.raises(HarmonicAPIError, match="Connection error"):
                harmonic_client._request("GET", "/test")

    def test_lookup_company_returns_none_on_404(self, harmonic_client):
        """lookup_company should return None for 404 (company not found)."""
        with patch.object(harmonic_client, "_request") as mock_request:
            mock_request.side_effect = HarmonicAPIError("Not found", status_code=404)

            result = harmonic_client.lookup_company(domain="nonexistent.com")
            assert result is None

    def test_get_company_returns_none_on_404(self, harmonic_client):
        """get_company should return None for 404."""
        with patch.object(harmonic_client, "_request") as mock_request:
            mock_request.side_effect = HarmonicAPIError("Not found", status_code=404)

            result = harmonic_client.get_company("nonexistent_id")
            assert result is None


# =============================================================================
# HARMONIC CLIENT FUNCTIONAL TESTS
# =============================================================================

class TestHarmonicClientFunctions:
    """Tests for HarmonicClient methods."""

    def test_lookup_company_success(self, harmonic_client):
        """lookup_company should return HarmonicCompany on success."""
        typeahead_response = {
            "results": [
                {
                    "type": "COMPANY",
                    "entity_urn": "urn:li:company:12345",
                    "text": "TestCo",
                }
            ]
        }
        company_response = {
            "id": "12345",
            "name": "TestCo",
            "description": "A test company",
        }

        with patch.object(harmonic_client, "_request") as mock_request:
            mock_request.side_effect = [typeahead_response, company_response]

            result = harmonic_client.lookup_company(domain="testco.com")

            assert result is not None
            assert isinstance(result, HarmonicCompany)
            assert result.name == "TestCo"

    def test_lookup_company_no_results(self, harmonic_client):
        """lookup_company should return None when no results."""
        with patch.object(harmonic_client, "_request") as mock_request:
            mock_request.return_value = {"results": []}

            result = harmonic_client.lookup_company(domain="nonexistent.com")
            assert result is None

    def test_lookup_company_requires_domain_or_linkedin(self, harmonic_client):
        """lookup_company should require domain or linkedin_url."""
        with pytest.raises(ValueError, match="Either domain or linkedin_url required"):
            harmonic_client.lookup_company()

    def test_get_company_employees_returns_list(self, harmonic_client):
        """get_company_employees should return list of HarmonicPerson."""
        employees_response = {
            "results": [
                {
                    "id": "person1",
                    "full_name": "John Doe",
                    "experience": [
                        {
                            "is_current_position": True,
                            "title": "CEO",
                            "role_type": "FOUNDER",
                        }
                    ]
                }
            ]
        }

        with patch.object(harmonic_client, "_request") as mock_request:
            mock_request.return_value = employees_response

            # Mock get_person to return the person directly
            with patch.object(harmonic_client, "get_person") as mock_get_person:
                mock_get_person.return_value = None  # Skip detail fetch

                results = harmonic_client.get_company_employees(
                    "12345",
                    employee_type="founders",
                    fetch_details=False
                )

                assert isinstance(results, list)

    def test_search_companies_returns_list(self, harmonic_client):
        """search_companies should return list of HarmonicCompany."""
        search_response = {
            "results": [
                {"id": "1", "name": "Company A"},
                {"id": "2", "name": "Company B"},
            ]
        }

        with patch.object(harmonic_client, "_request") as mock_request:
            mock_request.return_value = search_response

            results = harmonic_client.search_companies("AI startups")

            assert isinstance(results, list)
            assert len(results) == 2
            assert all(isinstance(c, HarmonicCompany) for c in results)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

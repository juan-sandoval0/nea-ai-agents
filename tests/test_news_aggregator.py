"""
Unit Tests for News Aggregator Agent
====================================
Tests for multi-investor support, competitor discovery, and database operations.

Run with:
    pytest tests/test_news_aggregator.py -v
"""

import pytest
import os
import tempfile
from pathlib import Path
from unittest.mock import Mock, patch, MagicMock
from datetime import datetime, timedelta

# We need to patch DB_PATH before importing the database module
@pytest.fixture(autouse=True)
def use_temp_database():
    """Use a temporary database for each test."""
    with tempfile.TemporaryDirectory() as tmpdir:
        temp_db = Path(tmpdir) / "test_news_aggregator.db"
        with patch("agents.news_aggregator.database.DB_PATH", temp_db):
            # Re-initialize the database with the new path
            from agents.news_aggregator import database
            database.DB_PATH = temp_db
            database.init_db()
            yield temp_db


# =============================================================================
# INVESTOR TESTS
# =============================================================================

class TestInvestorOperations:
    """Tests for investor CRUD operations."""

    def test_add_investor(self, use_temp_database):
        """Test adding a new investor."""
        from agents.news_aggregator.database import add_investor, get_investor

        investor = add_investor(name="John Doe", email="john@example.com")

        assert investor.id is not None
        assert investor.name == "John Doe"
        assert investor.email == "john@example.com"
        assert investor.is_active is True

        # Verify we can retrieve it
        retrieved = get_investor(investor_id=investor.id)
        assert retrieved.name == "John Doe"

    def test_get_investor_by_name(self, use_temp_database):
        """Test retrieving investor by name."""
        from agents.news_aggregator.database import add_investor, get_investor

        add_investor(name="Jane Smith")

        retrieved = get_investor(name="Jane Smith")
        assert retrieved is not None
        assert retrieved.name == "Jane Smith"

    def test_get_or_create_default_investor(self, use_temp_database):
        """Test default investor creation."""
        from agents.news_aggregator.database import get_or_create_default_investor, get_investor

        # First call creates
        default1 = get_or_create_default_investor()
        assert default1.name == "default"

        # Second call returns same
        default2 = get_or_create_default_investor()
        assert default2.id == default1.id

    def test_get_investors_list(self, use_temp_database):
        """Test listing all investors."""
        from agents.news_aggregator.database import add_investor, get_investors

        add_investor(name="Investor 1")
        add_investor(name="Investor 2")
        add_investor(name="Investor 3")

        investors = get_investors()
        assert len(investors) == 3


# =============================================================================
# COMPANY TESTS
# =============================================================================

class TestCompanyOperations:
    """Tests for company CRUD operations."""

    def test_add_company(self, use_temp_database):
        """Test adding a new company."""
        from agents.news_aggregator.database import add_company, get_company_by_domain

        company = add_company(
            company_id="stripe.com",
            company_name="Stripe",
            category="portfolio"
        )

        assert company.id is not None
        assert company.company_id == "stripe.com"
        assert company.company_name == "Stripe"
        assert company.category == "portfolio"

        # Verify we can retrieve it
        retrieved = get_company_by_domain("stripe.com")
        assert retrieved.company_name == "Stripe"

    def test_add_company_returns_existing(self, use_temp_database):
        """Test that adding duplicate company returns existing."""
        from agents.news_aggregator.database import add_company

        company1 = add_company(
            company_id="stripe.com",
            company_name="Stripe",
            category="portfolio"
        )

        company2 = add_company(
            company_id="stripe.com",
            company_name="Stripe Inc",  # Different name
            category="competitor"  # Different category
        )

        # Should return existing, not create new
        assert company1.id == company2.id
        assert company2.company_name == "Stripe"  # Original name preserved
        assert company2.category == "portfolio"  # Original category preserved

    def test_add_competitor_with_parent(self, use_temp_database):
        """Test adding a competitor linked to a portfolio company."""
        from agents.news_aggregator.database import add_company, get_competitors_for_company

        portfolio = add_company(
            company_id="stripe.com",
            company_name="Stripe",
            category="portfolio"
        )

        competitor = add_company(
            company_id="braintree.com",
            company_name="Braintree",
            category="competitor",
            parent_company_id=portfolio.id
        )

        assert competitor.parent_company_id == portfolio.id

        # Verify competitor retrieval
        competitors = get_competitors_for_company(portfolio.id)
        assert len(competitors) == 1
        assert competitors[0].company_name == "Braintree"

    def test_get_portfolio_companies(self, use_temp_database):
        """Test filtering portfolio companies only."""
        from agents.news_aggregator.database import add_company, get_portfolio_companies

        add_company("stripe.com", "Stripe", "portfolio")
        add_company("adyen.com", "Adyen", "portfolio")
        add_company("braintree.com", "Braintree", "competitor")

        portfolio = get_portfolio_companies()
        assert len(portfolio) == 2
        names = {c.company_name for c in portfolio}
        assert names == {"Stripe", "Adyen"}


# =============================================================================
# INVESTOR-COMPANY LINKING TESTS
# =============================================================================

class TestInvestorCompanyLinking:
    """Tests for many-to-many investor-company relationships."""

    def test_link_investor_to_company(self, use_temp_database):
        """Test linking an investor to a company."""
        from agents.news_aggregator.database import (
            add_investor, add_company, link_investor_to_company, get_companies
        )

        investor = add_investor(name="John Doe")
        company = add_company("stripe.com", "Stripe", "portfolio")

        link = link_investor_to_company(investor.id, company.id)

        assert link.investor_id == investor.id
        assert link.company_id == company.id

        # Verify company appears for investor
        companies = get_companies(investor_id=investor.id)
        assert len(companies) == 1
        assert companies[0].company_name == "Stripe"

    def test_investor_company_deduplication(self, use_temp_database):
        """Test that linking same investor-company twice returns existing link."""
        from agents.news_aggregator.database import (
            add_investor, add_company, link_investor_to_company
        )

        investor = add_investor(name="John Doe")
        company = add_company("stripe.com", "Stripe", "portfolio")

        link1 = link_investor_to_company(investor.id, company.id)
        link2 = link_investor_to_company(investor.id, company.id)

        assert link1.id == link2.id

    def test_multiple_investors_same_company(self, use_temp_database):
        """Test multiple investors can track the same company."""
        from agents.news_aggregator.database import (
            add_investor, add_company, link_investor_to_company, get_companies
        )

        investor1 = add_investor(name="Investor 1")
        investor2 = add_investor(name="Investor 2")
        company = add_company("stripe.com", "Stripe", "portfolio")

        link_investor_to_company(investor1.id, company.id)
        link_investor_to_company(investor2.id, company.id)

        # Both investors should see the company
        companies1 = get_companies(investor_id=investor1.id)
        companies2 = get_companies(investor_id=investor2.id)

        assert len(companies1) == 1
        assert len(companies2) == 1
        assert companies1[0].id == companies2[0].id

    def test_unlink_investor_from_company(self, use_temp_database):
        """Test removing an investor-company link."""
        from agents.news_aggregator.database import (
            add_investor, add_company, link_investor_to_company,
            unlink_investor_from_company, get_companies
        )

        investor = add_investor(name="John Doe")
        company = add_company("stripe.com", "Stripe", "portfolio")

        link_investor_to_company(investor.id, company.id)
        assert len(get_companies(investor_id=investor.id)) == 1

        unlink_investor_from_company(investor.id, company.id)
        assert len(get_companies(investor_id=investor.id)) == 0


# =============================================================================
# COMPETITOR REFRESH TESTS
# =============================================================================

class TestCompetitorRefresh:
    """Tests for competitor refresh tracking."""

    def test_competitors_need_refresh_new_company(self, use_temp_database):
        """Test that new portfolio companies need competitor refresh."""
        from agents.news_aggregator.database import add_company

        company = add_company("stripe.com", "Stripe", "portfolio")

        assert company.competitors_need_refresh() is True

    def test_competitors_need_refresh_after_update(self, use_temp_database):
        """Test that refreshed companies don't need refresh."""
        from agents.news_aggregator.database import (
            add_company, update_competitors_refreshed, get_company_by_domain
        )

        company = add_company("stripe.com", "Stripe", "portfolio")
        update_competitors_refreshed(company.id)

        # Re-fetch to get updated timestamp
        company = get_company_by_domain("stripe.com")
        assert company.competitors_need_refresh() is False

    def test_competitors_need_refresh_competitor_category(self, use_temp_database):
        """Test that competitors never need competitor refresh."""
        from agents.news_aggregator.database import add_company

        company = add_company("braintree.com", "Braintree", "competitor")

        # Competitors don't have their own competitors
        assert company.competitors_need_refresh() is False


# =============================================================================
# REMOVE COMPANY TESTS
# =============================================================================

class TestRemoveCompany:
    """Tests for removing companies."""

    def test_deactivate_company(self, use_temp_database):
        """Test soft-deleting a company."""
        from agents.news_aggregator.database import (
            add_company, deactivate_company, get_companies
        )

        company = add_company("stripe.com", "Stripe", "portfolio")
        assert len(get_companies()) == 1

        deactivate_company(company.id)
        assert len(get_companies(active_only=True)) == 0
        assert len(get_companies(active_only=False)) == 1

    def test_hard_delete_company(self, use_temp_database):
        """Test permanently deleting a company."""
        from agents.news_aggregator.database import (
            add_company, remove_company, get_companies
        )

        company = add_company("stripe.com", "Stripe", "portfolio")
        assert len(get_companies()) == 1

        remove_company(company.id, hard_delete=True)
        assert len(get_companies(active_only=False)) == 0


# =============================================================================
# SIGNAL DETECTOR TESTS
# =============================================================================

class TestSignalDetector:
    """Tests for the SignalDetector class."""

    def test_discover_competitors_no_harmonic(self, use_temp_database):
        """Test competitor discovery without Harmonic client."""
        from agents.news_aggregator.database import add_company
        from agents.news_aggregator.detector import SignalDetector

        company = add_company("stripe.com", "Stripe", "portfolio")
        detector = SignalDetector(harmonic_client=None)

        # Should return empty list when no Harmonic client
        competitors = detector.discover_competitors(company)
        assert competitors == []

    def test_discover_competitors_with_mock_harmonic(self, use_temp_database):
        """Test competitor discovery with mocked Harmonic client."""
        from agents.news_aggregator.database import (
            add_company, get_competitors_for_company, get_company_by_domain
        )
        from agents.news_aggregator.detector import SignalDetector

        company = add_company("stripe.com", "Stripe", "portfolio")

        # Mock Harmonic client
        mock_harmonic = Mock()
        mock_harmonic.lookup_company.return_value = Mock(id="harmonic_123")
        mock_harmonic.get_company.return_value = {
            "similar_companies": [
                {"domain": "braintree.com", "name": "Braintree", "id": "harmonic_456"},
                {"domain": "adyen.com", "name": "Adyen", "id": "harmonic_789"},
                {"domain": "square.com", "name": "Square", "id": "harmonic_012"},  # Extra, should be ignored
            ]
        }

        detector = SignalDetector(harmonic_client=mock_harmonic)
        competitors = detector.discover_competitors(company, max_competitors=2)

        assert len(competitors) == 2
        domains = {c.company_id for c in competitors}
        assert "braintree.com" in domains
        assert "adyen.com" in domains

        # Verify competitors are linked
        linked = get_competitors_for_company(company.id)
        assert len(linked) == 2

        # Verify competitors_refreshed_at was updated
        updated_company = get_company_by_domain("stripe.com")
        assert updated_company.competitors_refreshed_at is not None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

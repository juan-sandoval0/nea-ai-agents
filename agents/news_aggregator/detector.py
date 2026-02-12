"""Multi-source signal detection for companies."""

import uuid
import json
from typing import List, Optional
from dataclasses import dataclass

from .database import (
    WatchedCompany, CompanySignal, save_signal, signal_exists,
    get_latest_employee_snapshot, save_employee_snapshot, update_company_harmonic_id,
    add_company, link_investor_to_company, update_competitors_refreshed,
    get_competitors_for_company, update_company_industries
)
from .scorer import score_signal, format_score_breakdown, detect_seniority

# Use existing clients from core
from core.clients.harmonic import HarmonicClient
from core.clients.parallel_search import ParallelSearchClient, _analyze_sentiment, get_sentiment_label_simple


@dataclass
class DetectionResult:
    signals: List[CompanySignal]
    errors: List[str]


class SignalDetector:
    """Detects signals from multiple sources."""

    def __init__(self, harmonic_client: HarmonicClient = None, parallel_client: ParallelSearchClient = None):
        self.harmonic = harmonic_client
        self.parallel = parallel_client

    def discover_competitors(self, portfolio_company: WatchedCompany, investor_id: str = None, max_competitors: int = 2) -> List[WatchedCompany]:
        """
        Discover competitors for a portfolio company using Harmonic API.

        Uses Harmonic's similar_companies endpoint to find companies similar
        to the portfolio company based on industry, tags, and other signals.

        Args:
            portfolio_company: The portfolio company to find competitors for
            investor_id: Optional investor ID to link competitors to
            max_competitors: Maximum number of competitors to discover (default: 2)

        Returns:
            List of newly created competitor WatchedCompany objects
        """
        if not self.harmonic:
            return []

        created_competitors = []

        # Get Harmonic company ID if not present
        harmonic_id = portfolio_company.harmonic_id
        if not harmonic_id:
            harmonic_company = self.harmonic.lookup_company(domain=portfolio_company.company_id)
            if harmonic_company:
                update_company_harmonic_id(portfolio_company.id, harmonic_company.id)
                harmonic_id = harmonic_company.id
            else:
                # Mark as refreshed even if we couldn't find the company
                update_competitors_refreshed(portfolio_company.id)
                return []

        # Get existing competitors to avoid duplicates
        existing_competitors = get_competitors_for_company(portfolio_company.id)
        existing_domains = {c.company_id for c in existing_competitors}

        # Use Harmonic's similar_companies endpoint
        # Returns URNs like 'urn:harmonic:company:1858'
        try:
            similar_response = self.harmonic._request(
                'GET',
                f'/search/similar_companies/{harmonic_id}',
                params={'page_size': max_competitors * 3}  # Fetch extra to account for filtering
            )
            similar_urns = similar_response.get('results', [])
        except Exception:
            similar_urns = []

        for urn in similar_urns:
            if len(created_competitors) >= max_competitors:
                break

            # Extract company ID from URN (e.g., 'urn:harmonic:company:1858' -> '1858')
            if isinstance(urn, str) and ':' in urn:
                comp_harmonic_id = urn.split(':')[-1]
            else:
                continue

            # Fetch full company details
            try:
                comp_data = self.harmonic.get_company(comp_harmonic_id)
                if not comp_data:
                    continue
            except Exception:
                continue

            comp_domain = comp_data.domain
            comp_name = comp_data.name or 'Unknown'

            if not comp_domain or comp_domain in existing_domains:
                continue

            # Skip if same as portfolio company
            if comp_domain == portfolio_company.company_id:
                continue

            # Create competitor entry
            competitor = add_company(
                company_id=comp_domain,
                company_name=comp_name,
                category="competitor",
                parent_company_id=portfolio_company.id
            )

            if competitor:
                # Update Harmonic ID
                update_company_harmonic_id(competitor.id, comp_harmonic_id)

                # Link to investor if provided
                if investor_id:
                    link_investor_to_company(investor_id, competitor.id)

                created_competitors.append(competitor)
                existing_domains.add(comp_domain)

        # Update the portfolio company's competitors_refreshed_at timestamp
        update_competitors_refreshed(portfolio_company.id)

        return created_competitors

    def detect_all_signals(self, company: WatchedCompany) -> DetectionResult:
        """Detect all signals for a company from all sources."""
        signals = []
        errors = []

        # Harmonic signals (employees, funding)
        if self.harmonic:
            try:
                harmonic_signals = self._detect_harmonic_signals(company)
                signals.extend(harmonic_signals)
            except Exception as e:
                errors.append(f"Harmonic error for {company.company_name}: {str(e)}")

        # Parallel Search signals (news)
        if self.parallel:
            try:
                parallel_signals = self._detect_parallel_signals(company)
                signals.extend(parallel_signals)
            except Exception as e:
                errors.append(f"Parallel error for {company.company_name}: {str(e)}")

        return DetectionResult(signals=signals, errors=errors)

    def refresh_industry_tags(self, company: WatchedCompany) -> List[str]:
        """
        Refresh industry tags for a company from Harmonic API.

        Args:
            company: The company to refresh tags for

        Returns:
            List of industry tags assigned to the company
        """
        if not self.harmonic:
            return []

        # Get Harmonic company data
        harmonic_company = None
        if company.harmonic_id:
            harmonic_company = self.harmonic.get_company(company.harmonic_id)
        else:
            harmonic_company = self.harmonic.lookup_company(domain=company.company_id)
            if harmonic_company:
                update_company_harmonic_id(company.id, harmonic_company.id)

        if not harmonic_company or not harmonic_company.tags:
            return []

        # Update industry tags in database
        update_company_industries(company.id, harmonic_company.tags)
        return harmonic_company.tags

    def _detect_harmonic_signals(self, company: WatchedCompany) -> List[CompanySignal]:
        """Detect signals from Harmonic (employee changes, funding)."""
        signals = []

        # Get or update Harmonic company ID and industry tags
        if not company.harmonic_id:
            harmonic_company = self.harmonic.lookup_company(domain=company.company_id)
            if harmonic_company:
                update_company_harmonic_id(company.id, harmonic_company.id)
                company.harmonic_id = harmonic_company.id
                # Also update industry tags if available
                if harmonic_company.tags:
                    update_company_industries(company.id, harmonic_company.tags)
            else:
                return signals

        # Get current employees (executives)
        current_employees = self.harmonic.get_company_employees(
            company.harmonic_id,
            employee_type="executives",
            fetch_details=False
        )
        if not current_employees:
            return signals

        # Convert HarmonicPerson objects to dicts for storage
        employees_data = []
        for emp in current_employees:
            employees_data.append({
                "id": emp.id,
                "name": emp.name,
                "title": emp.title,
                "linkedin_url": emp.linkedin_url,
                "is_founder": emp.is_founder,
                "is_executive": emp.is_executive,
            })

        # Compare with previous snapshot
        prev_snapshot = get_latest_employee_snapshot(company.id)
        if prev_snapshot:
            new_hires = self._find_new_employees(prev_snapshot.employees, employees_data)
            for hire in new_hires:
                signal = self._create_team_change_signal(company, hire)
                if signal and not signal_exists(company.id, signal.signal_type, signal.headline):
                    save_signal(signal)
                    signals.append(signal)

        # Save current snapshot
        save_employee_snapshot(company.id, employees_data)

        return signals

    def _find_new_employees(self, old_employees: List[dict], new_employees: List[dict]) -> List[dict]:
        """Find employees that are in new but not in old."""
        old_ids = {e.get("id") for e in old_employees}
        new_hires = [e for e in new_employees if e.get("id") not in old_ids]
        return new_hires

    def _create_team_change_signal(self, company: WatchedCompany, employee: dict) -> Optional[CompanySignal]:
        """Create a team change signal for a new hire."""
        name = employee.get("name", "Unknown")
        title = employee.get("title", "Unknown role")
        seniority = detect_seniority(title)

        # Only track senior hires
        if seniority not in ["c_suite", "vp", "director"]:
            return None

        headline = f"{name} joins {company.company_name} as {title}"
        raw_data = {
            "person_name": name,
            "title": title,
            "seniority": seniority,
            "linkedin_url": employee.get("linkedin_url"),
        }

        score, breakdown = score_signal(company.category, "team_change", raw_data)

        return CompanySignal(
            id=str(uuid.uuid4()),
            company_id=company.id,
            signal_type="team_change",
            headline=headline,
            description=f"New {seniority.replace('_', ' ')} hire at {company.company_name}",
            source_name="Harmonic",
            relevance_score=score,
            score_breakdown=format_score_breakdown(breakdown),
            raw_data=json.dumps(raw_data)
        )

    def _detect_parallel_signals(self, company: WatchedCompany, days: int = 7) -> List[CompanySignal]:
        """
        Detect signals from Parallel Search (news).

        Filters applied:
        1. Only articles from the last N days
        2. Excludes homepage/non-article URLs
        3. Company name must appear in title or excerpts
        """
        signals = []

        results = self.parallel.search_company_news(company.company_name)

        for result in results:
            url = result.url or ""

            # Filter: Skip homepage/non-article URLs
            if self._is_homepage_url(url):
                continue

            # Filter: Skip articles older than N days
            if not self._is_within_date_range(result.publish_date, days=days):
                continue

            title = result.title or ""
            excerpts = result.excerpts or []

            # Filter: Company name must appear in title or excerpts
            if not self._mentions_company(company.company_name, title, excerpts):
                continue
            summary = " ".join(excerpts)[:500] if excerpts else ""
            source = result.source_domain or "Web"
            published = result.publish_date
            signal_type = self.parallel.classify_result(result)

            # Analyze sentiment using weighted keyword matching
            sentiment_score = _analyze_sentiment(title, excerpts)
            sentiment = get_sentiment_label_simple(sentiment_score)

            headline = title[:200] if len(title) > 200 else title

            if signal_exists(company.id, signal_type, headline):
                continue

            raw_data = {
                "original_title": title,
                "summary": summary
            }

            score, breakdown = score_signal(company.category, signal_type, raw_data)

            signal = CompanySignal(
                id=str(uuid.uuid4()),
                company_id=company.id,
                signal_type=signal_type,
                headline=headline,
                description=summary,
                source_url=url,
                source_name=source,
                published_date=published,
                relevance_score=score,
                score_breakdown=format_score_breakdown(breakdown),
                raw_data=json.dumps(raw_data),
                sentiment=sentiment,
            )
            save_signal(signal)
            signals.append(signal)

        return signals

    def _is_homepage_url(self, url: str) -> bool:
        """Check if URL is a homepage or non-article page."""
        if not url:
            return True

        import re
        from urllib.parse import urlparse

        # Homepage patterns
        homepage_patterns = [
            r'^https?://[^/]+/?$',  # Just domain
            r'^https?://[^/]+/(?:category|tag|topic|author|page)/[^/]*/?$',
            r'^https?://[^/]+/(?:ai|tech|business|news|blog)/?$',
        ]

        for pattern in homepage_patterns:
            if re.match(pattern, url, re.IGNORECASE):
                return True

        try:
            parsed = urlparse(url)
            path = parsed.path.strip('/')
            if not path:
                return True
            # Short path without numbers = likely not an article
            if len(path) < 20 and not re.search(r'\d', path) and path.count('/') == 0:
                return True
        except Exception:
            pass

        return False

    def _is_within_date_range(self, publish_date: str, days: int = 7) -> bool:
        """Check if publish date is within range."""
        if not publish_date:
            return True  # Permissive if no date

        from datetime import datetime, timedelta, timezone

        try:
            date_str = publish_date.replace('Z', '+00:00')
            if 'T' not in date_str:
                date_str = f"{date_str}T00:00:00+00:00"
            pub_date = datetime.fromisoformat(date_str)
            cutoff = datetime.now(timezone.utc) - timedelta(days=days)
            return pub_date >= cutoff
        except (ValueError, TypeError):
            return True

    def _mentions_company(self, company_name: str, title: str, excerpts: List[str]) -> bool:
        """
        Check if the company name is mentioned in the article.

        This prevents misattribution when search APIs return articles about
        similar companies in the same industry.
        """
        if not company_name:
            return True  # Permissive if no company name

        # Normalize company name for matching
        company_lower = company_name.lower().strip()

        # Check title
        if company_lower in title.lower():
            return True

        # Check excerpts
        combined_excerpts = " ".join(excerpts).lower()
        if company_lower in combined_excerpts:
            return True

        # Handle multi-word company names - check if all significant words appear
        # e.g., "Eleven Labs" should match "ElevenLabs"
        words = [w for w in company_lower.split() if len(w) > 2]
        if len(words) > 1:
            all_text = f"{title} {combined_excerpts}".lower()
            # Check if concatenated version appears (ElevenLabs vs Eleven Labs)
            no_space = company_lower.replace(" ", "")
            if no_space in all_text.replace(" ", ""):
                return True

        return False

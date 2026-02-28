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

    def _get_harmonic_data(self, company: WatchedCompany):
        """
        Fetch Harmonic company data for enhanced search.

        Returns HarmonicCompany object if available, None otherwise.
        Uses cached harmonic_id when available to avoid lookup.
        """
        if not self.harmonic:
            return None

        try:
            # Use cached Harmonic ID if available
            if company.harmonic_id:
                harmonic_company = self.harmonic.get_company(str(company.harmonic_id))
                if harmonic_company:
                    return harmonic_company

            # Fallback: lookup by domain
            domain = company.company_id.replace("https://", "").replace("http://", "").rstrip("/")
            harmonic_company = self.harmonic.lookup_company(domain=domain)

            # Cache the Harmonic ID for future use
            if harmonic_company and harmonic_company.id:
                update_company_harmonic_id(company.id, int(harmonic_company.id))

            return harmonic_company

        except Exception as e:
            import logging
            logging.getLogger(__name__).warning(
                f"Failed to fetch Harmonic data for {company.company_name}: {e}"
            )
            return None

    def _detect_parallel_signals(self, company: WatchedCompany, days: int = 7) -> List[CompanySignal]:
        """
        Detect signals from Parallel Search (news).

        Uses Harmonic company data when available for enhanced search queries
        that work better for smaller/niche companies.

        Filters applied:
        1. Only articles from the last N days
        2. Excludes homepage/non-article URLs
        3. Company name must appear in title or excerpts
        4. Context validation to filter false positives for generic names
        """
        signals = []

        # Extract clean domain (e.g., "namespace.so" from "https://namespace.so")
        domain = company.company_id.replace("https://", "").replace("http://", "").rstrip("/")

        # Check if company name is potentially ambiguous (common words/short names)
        needs_disambiguation = self._is_ambiguous_name(company.company_name)

        # Try to get Harmonic data for enhanced search
        harmonic_data = self._get_harmonic_data(company)

        if harmonic_data:
            # Use Harmonic-enhanced search for better results
            results = self.parallel.search_company_news_enhanced(
                company_name=harmonic_data.name,  # Use exact name from Harmonic
                domain=harmonic_data.domain or domain,
                description=harmonic_data.description,
                investors=harmonic_data.investors,
                tags=harmonic_data.tags,
            )
        elif needs_disambiguation:
            # Fallback: Use domain-enhanced search for ambiguous names
            results = self._search_with_domain_context(company.company_name, domain)
        else:
            # Standard search for non-ambiguous names
            results = self.parallel.search_company_news(company.company_name)

        for result in results:
            url = result.url or ""

            # Check if this is from the company's own domain
            is_company_domain = domain in url.lower()

            # Filter: Skip homepage/non-article URLs
            # Exception: Allow company's own domain (their blog, changelog, docs are valuable)
            if not is_company_domain and self._is_homepage_url(url):
                continue

            # For company's own domain, only skip the actual homepage
            if is_company_domain:
                from urllib.parse import urlparse
                path = urlparse(url).path.strip('/')
                if not path:  # Actual homepage with no path
                    continue

            # Filter: Skip articles older than N days
            # Exception: Company's own content is always relevant
            if not is_company_domain:
                if not self._is_within_date_range(result.publish_date, days=days):
                    continue

            title = result.title or ""
            excerpts = result.excerpts or []

            # Filter: Company name must appear in title or excerpts
            # Exception: Company's own domain doesn't need name mention
            if not is_company_domain:
                if not self._mentions_company(company.company_name, title, excerpts):
                    continue

            # Additional filter for ambiguous names: validate context
            # Exception: Company's own domain is always valid
            if needs_disambiguation and not is_company_domain:
                if not self._validate_company_context(company, title, excerpts, url):
                    continue

            # Filter: Skip technical tutorials that just mention the term
            # (e.g., "Docker namespaces explained" is not about the company)
            if self._is_technical_tutorial(title, url):
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

    # =========================================================================
    # DISAMBIGUATION HELPERS FOR GENERIC COMPANY NAMES
    # =========================================================================

    # Common programming/tech terms that could be company names
    AMBIGUOUS_TERMS = {
        'namespace', 'api', 'cloud', 'data', 'ai', 'ml', 'io', 'hub', 'lab',
        'labs', 'studio', 'stack', 'base', 'kit', 'box', 'app', 'flow', 'sync',
        'link', 'net', 'node', 'core', 'code', 'dev', 'ops', 'bit', 'byte',
        'grid', 'mesh', 'matrix', 'vector', 'tensor', 'graph', 'edge', 'pipe',
        'stream', 'queue', 'cache', 'store', 'vault', 'key', 'gate', 'port',
        'helm', 'dock', 'pod', 'container', 'cluster', 'scale', 'load', 'test',
    }

    def _is_ambiguous_name(self, company_name: str) -> bool:
        """
        Check if a company name is potentially ambiguous (common tech term).

        Returns True if the name could easily be confused with:
        - Programming concepts (namespace, api, etc.)
        - Generic tech terms (cloud, data, ai, etc.)
        - Very short names (< 4 chars)
        """
        if not company_name:
            return False

        name_lower = company_name.lower().strip()

        # Very short names are ambiguous
        if len(name_lower) <= 3:
            return True

        # Single-word names that match common tech terms
        words = name_lower.split()
        if len(words) == 1 and name_lower in self.AMBIGUOUS_TERMS:
            return True

        # Names that start with common prefixes and are short
        if len(name_lower) <= 10:
            for term in self.AMBIGUOUS_TERMS:
                if name_lower == term or name_lower.startswith(term):
                    return True

        return False

    def _search_with_domain_context(self, company_name: str, domain: str) -> list:
        """
        Search with domain context for better disambiguation.

        For companies with generic names, adds domain-based queries to find
        more relevant results.
        """
        from core.clients.parallel_search import ParallelSearchResult

        # Try domain-specific search first
        domain_base = domain.split('.')[0] if '.' in domain else domain

        # Build enhanced search queries
        search_queries = [
            f'"{company_name}" startup',
            f'"{company_name}" company funding',
            f'site:{domain}',
            f'"{domain_base}" startup OR company OR raises OR launches',
        ]

        # Add industry context if available
        # (industry_tags could be used here for even better results)

        try:
            # Use the parallel client's internal search method
            response = self.parallel._client.beta.search(
                objective=(
                    f"Find news articles about the company {company_name} "
                    f"(website: {domain}). Focus on company news, funding, "
                    f"product launches, and business developments. Exclude "
                    f"technical documentation or generic references."
                ),
                search_queries=search_queries,
                max_results=10,
                excerpts={"max_chars_per_result": 5000},
            )

            results = []
            for item in response.results or []:
                url = getattr(item, "url", "") or ""
                result = ParallelSearchResult(
                    url=url,
                    title=getattr(item, "title", "") or "",
                    publish_date=getattr(item, "publish_date", None),
                    excerpts=getattr(item, "excerpts", []) or [],
                    source_domain=self._extract_domain(url),
                )
                results.append(result)

            return results

        except Exception as e:
            # Fall back to standard search on error
            import logging
            logging.getLogger(__name__).warning(
                f"Domain-enhanced search failed for {company_name}: {e}, "
                f"falling back to standard search"
            )
            return self.parallel.search_company_news(company_name)

    def _extract_domain(self, url: str) -> str:
        """Extract domain from URL."""
        from urllib.parse import urlparse
        try:
            return urlparse(url).netloc.replace("www.", "")
        except Exception:
            return ""

    # Domains/patterns that indicate technical documentation, not company news
    TECHNICAL_DOC_PATTERNS = [
        'learn.microsoft.com', 'docs.microsoft.com', 'developer.mozilla.org',
        'docs.python.org', 'docs.oracle.com', 'docs.aws.amazon.com',
        'cloud.google.com/docs', 'kubernetes.io/docs', 'docs.docker.com',
        'stackoverflow.com', 'github.com/docs', 'gitlab.com/docs',
        'elastic.co/guide', 'wikipedia.org', 'w3schools.com',
        'geeksforgeeks.org', 'tutorialspoint.com', 'medium.com',
    ]

    # Keywords that indicate technical documentation, not news
    TECHNICAL_DOC_KEYWORDS = [
        'documentation', 'reference', 'guide', 'tutorial', 'how to',
        'api reference', 'syntax', 'examples', 'code sample',
        'developer guide', 'user manual', 'specification',
    ]

    # Common words that have non-tech meanings and need stricter validation
    # Maps word -> list of keywords that indicate non-company usage
    COMMON_WORD_EXCLUSIONS = {
        'port': [
            'shipping', 'maritime', 'harbor', 'harbour', 'dock', 'cargo',
            'container ship', 'freight', 'sea-intelligence', 'vessel',
            'cruise', 'royal caribbean', 'maersk', 'hapag', 'zim',
            'norfolk southern', 'union pacific', 'railroad', 'rail',
            'port of', 'seaport', 'airport', 'sports', '$ports',
        ],
        'cloud': [
            'weather', 'cloudy', 'rain', 'storm', 'meteorology',
        ],
        'stream': [
            'river', 'creek', 'brook', 'fishing', 'salmon', 'trout',
        ],
        'base': [
            'military', 'air force', 'army', 'naval base', 'baseball',
            'home base', 'base camp', 'base of',
        ],
        'hub': [
            'airport hub', 'transit hub', 'bicycle hub', 'wheel hub',
        ],
        'grid': [
            'power grid', 'electrical grid', 'national grid', 'grid operator',
        ],
        'edge': [
            'cutting edge', 'on the edge', 'edge of',
        ],
        'gate': [
            'airport gate', 'gate agent', 'boarding gate', 'golden gate',
        ],
        'key': [
            'florida keys', 'key west', 'key largo', 'piano key',
        ],
        'scale': [
            'fish scale', 'musical scale', 'weighing scale', 'scale model',
        ],
        'core': [
            'apple core', 'core workout', 'core strength', "earth's core",
        ],
    }

    def _validate_company_context(
        self,
        company: WatchedCompany,
        title: str,
        excerpts: List[str],
        url: str
    ) -> bool:
        """
        Validate that an article is actually about the company, not just
        mentioning a generic term.

        For ambiguous company names, checks for contextual signals that
        indicate this is about the actual company:
        - Domain mentioned in text
        - Company-related keywords (startup, company, raises, CEO, etc.)
        - Industry context matches
        - NOT technical documentation
        """
        combined_text = f"{title} {' '.join(excerpts)}".lower()
        url_lower = url.lower()

        # FIRST: Exclude technical documentation sites
        for pattern in self.TECHNICAL_DOC_PATTERNS:
            if pattern in url_lower:
                return False

        # Exclude articles that look like technical documentation
        title_lower = title.lower()
        for keyword in self.TECHNICAL_DOC_KEYWORDS:
            if keyword in title_lower:
                return False

        # Check for common word exclusions (e.g., "port" in shipping context)
        company_name_lower = company.company_name.lower().strip()
        if company_name_lower in self.COMMON_WORD_EXCLUSIONS:
            exclusion_keywords = self.COMMON_WORD_EXCLUSIONS[company_name_lower]
            for exclusion in exclusion_keywords:
                if exclusion in combined_text:
                    # Found a non-company usage indicator
                    # Only allow if company's domain is explicitly mentioned
                    domain = company.company_id.replace("https://", "").replace("http://", "").rstrip("/")
                    if domain not in combined_text and domain not in url_lower:
                        return False

        # Check if another company is the primary subject of the article
        # (e.g., "Guardant Health Announces..." - Guardant is the subject, not NameSpace)
        company_name_lower = company.company_name.lower()
        if not self._is_primary_subject(company_name_lower, title_lower):
            return False

        # Extract domain for matching (e.g., "namespace.so" -> "namespace.so")
        domain = company.company_id.replace("https://", "").replace("http://", "").rstrip("/")
        domain_base = domain.split('.')[0] if '.' in domain else domain

        # Check if domain is mentioned
        if domain in combined_text or f"{domain_base}.so" in combined_text or f"{domain_base}.io" in combined_text:
            return True

        # Check if URL is from company's own domain
        if domain in url:
            return True

        # Look for company-context keywords near the company name
        company_context_keywords = [
            'startup', 'company', 'raises', 'raised', 'funding', 'series',
            'ceo', 'founder', 'founded', 'announces', 'launches', 'launched',
            'headquartered', 'based in', 'employees', 'valuation', 'investors',
            'venture', 'backed', 'seed', 'round', 'investment', 'profile',
            'crunchbase', 'pitchbook', 'techcrunch', 'acquisition',
        ]

        company_name_lower = company.company_name.lower()
        name_pos = combined_text.find(company_name_lower)

        if name_pos != -1:
            # Check surrounding context (100 chars before and after)
            context_start = max(0, name_pos - 100)
            context_end = min(len(combined_text), name_pos + len(company_name_lower) + 100)
            context = combined_text[context_start:context_end]

            for keyword in company_context_keywords:
                if keyword in context:
                    return True

        # Check if the full company name + "Labs" or similar suffix appears
        # (e.g., "Namespace Labs" for company "NameSpace")
        common_suffixes = ['labs', 'inc', 'corp', 'co', 'technologies', 'tech', 'ai', 'io']
        for suffix in common_suffixes:
            full_name = f"{company_name_lower} {suffix}"
            if full_name in combined_text:
                return True

        # Check for industry tag matches (if available)
        if company.industry_tags:
            for tag in company.industry_tags:
                tag_lower = tag.lower()
                # Check for key industry words
                tag_words = [w for w in tag_lower.split() if len(w) > 3]
                for word in tag_words[:2]:  # Check first 2 significant words
                    if word in combined_text:
                        return True

        # If we get here, the article likely isn't about the company
        return False

    def _is_primary_subject(self, company_name: str, title: str) -> bool:
        """
        Check if the company appears to be the primary subject of the article.

        Returns False if another entity clearly appears as the main subject.
        This helps filter out articles like "Guardant Health Announces...
        Namespace Group" where NameSpace is mentioned but not the subject.
        """
        # If company name appears at the very start of the title, it's the subject
        if title.startswith(company_name):
            return True

        # Check if company name appears in title at all
        company_pos = title.find(company_name)
        if company_pos == -1:
            # Company name not in title - check excerpts later
            return True  # Be permissive, let other checks handle it

        # Look for patterns where another entity is the subject
        # Pattern: "[Other Company] announces/launches/raises... [our company name]"
        announcement_verbs = [
            'announces', 'announced', 'launches', 'launched', 'raises',
            'raised', 'acquires', 'acquired', 'partners', 'partnered',
            'joins', 'joined', 'releases', 'released',
        ]

        for verb in announcement_verbs:
            verb_pos = title.find(verb)
            if verb_pos != -1 and verb_pos < company_pos:
                # Something announced something about our company
                # Check if there's another proper noun before the verb
                text_before_verb = title[:verb_pos].strip()
                # If text before verb is substantial (> 3 words), likely another company
                words_before = [w for w in text_before_verb.split() if len(w) > 2]
                if len(words_before) >= 2:
                    # Check if this looks like a company name (capitalized words)
                    # In lowercase title, we can't check capitalization, but
                    # substantial text before the verb suggests another subject
                    return False

        # Company appears in title and no clear indication of being secondary
        return True

    def _is_technical_tutorial(self, title: str, url: str) -> bool:
        """
        Check if an article is a technical tutorial about a concept
        rather than news about a company.

        Filters out articles like "Docker namespaces explained" or
        "Understanding Linux namespaces" which use the term technically.
        """
        title_lower = title.lower()
        url_lower = url.lower()

        # Tutorial site patterns
        tutorial_sites = [
            'dev.to', 'medium.com', 'towardsdatascience.com',
            'freecodecamp.org', 'hackernoon.com', 'dzone.com',
            'baeldung.com', 'tutorialspoint.com', 'geeksforgeeks.org',
        ]
        if any(site in url_lower for site in tutorial_sites):
            # Check if it's educational content vs company news
            tutorial_indicators = [
                'how to', 'tutorial', 'explained', 'understanding',
                'introduction to', 'guide to', 'learn', 'basics',
                'what is', 'what are', 'deep dive', 'under the hood',
                'build your own', 'from scratch', 'step by step',
            ]
            if any(indicator in title_lower for indicator in tutorial_indicators):
                return True

        # Technical documentation sites
        doc_sites = [
            'developer.', 'docs.', 'documentation.',
            'learn.microsoft', 'cloud.google', 'aws.amazon',
        ]
        if any(site in url_lower for site in doc_sites):
            return True

        return False

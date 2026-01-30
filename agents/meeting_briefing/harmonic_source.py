"""
Harmonic Data Source
=====================

DataSource implementation using Harmonic.ai API with ChromaDB caching
for historical tracking.

Features:
- Company profile enrichment
- Founder/team information
- Hiring/headcount changes tracking
- Web traffic monitoring
- Timestamp-based historical data

Usage:
    from agents.meeting_briefing.harmonic_source import HarmonicDataSource

    source = HarmonicDataSource()
    agent = MeetingBriefingAgent(data_source=source)
"""

from __future__ import annotations

import hashlib
import json
import os
import logging
from dataclasses import asdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

import chromadb
from chromadb.config import Settings

from .harmonic_client import HarmonicClient, HarmonicCompany, HarmonicPerson, HarmonicAPIError
from .data_corrections import get_corrected_founders

# Import from agent.py for type compatibility
from .agent import RetrievalResult, Source, DEFAULT_NEWS_DAYS

logger = logging.getLogger(__name__)

# =============================================================================
# CONFIGURATION
# =============================================================================

DEFAULT_CACHE_DIR = str(Path(__file__).parent / "harmonic_cache")
DEFAULT_COLLECTION_NAME = "harmonic_data"
CACHE_TTL_HOURS = 24  # How long to cache company data before refresh


# =============================================================================
# HARMONIC DATA SOURCE
# =============================================================================

class HarmonicDataSource:
    """
    DataSource implementation using Harmonic.ai API.

    Implements the DataSource Protocol for MeetingBriefingAgent with:
    - Real-time company data from Harmonic API
    - ChromaDB caching with timestamp tracking
    - Historical change detection (headcount, traffic, etc.)

    Usage:
        # Basic usage
        source = HarmonicDataSource()

        # With custom cache directory
        source = HarmonicDataSource(cache_dir="./my_cache")

        # Use with agent
        agent = MeetingBriefingAgent(data_source=source)
        result = agent.prepare_briefing("Stripe")
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        cache_dir: Optional[str] = None,
        collection_name: str = DEFAULT_COLLECTION_NAME,
        cache_ttl_hours: int = CACHE_TTL_HOURS,
    ):
        """
        Initialize Harmonic data source.

        Args:
            api_key: Harmonic API key (falls back to HARMONIC_API_KEY env var)
            cache_dir: Directory for ChromaDB cache
            collection_name: Name for the ChromaDB collection
            cache_ttl_hours: Hours before cached data is refreshed
        """
        self.api_key = api_key or os.getenv("HARMONIC_API_KEY")
        self.cache_dir = cache_dir or DEFAULT_CACHE_DIR
        self.collection_name = collection_name
        self.cache_ttl = timedelta(hours=cache_ttl_hours)

        # Initialize Harmonic client
        self.client = HarmonicClient(api_key=self.api_key)

        # Initialize ChromaDB for caching
        self._init_cache()

        # Track known companies (domain -> company_id mapping)
        self._company_cache: dict[str, str] = {}

    def _init_cache(self):
        """Initialize ChromaDB cache for historical tracking."""
        Path(self.cache_dir).mkdir(parents=True, exist_ok=True)

        self.chroma_client = chromadb.PersistentClient(
            path=self.cache_dir,
            settings=Settings(anonymized_telemetry=False),
        )

        # Main collection for company data snapshots
        self.collection = self.chroma_client.get_or_create_collection(
            name=self.collection_name,
            metadata={"description": "Harmonic company data with timestamp tracking"},
        )

        # Separate collection for tracking changes over time
        self.changes_collection = self.chroma_client.get_or_create_collection(
            name=f"{self.collection_name}_changes",
            metadata={"description": "Historical changes in company metrics"},
        )

    def _generate_doc_id(self, company_id: str, doc_type: str, timestamp: str) -> str:
        """Generate unique document ID."""
        hash_input = f"{company_id}|{doc_type}|{timestamp}"
        return hashlib.md5(hash_input.encode()).hexdigest()[:16]

    def _get_cached_company(self, company_id: str) -> Optional[dict]:
        """Get cached company data if not expired."""
        try:
            results = self.collection.get(
                where={"company_id": {"$eq": company_id}},
                include=["documents", "metadatas"],
            )

            if not results["documents"]:
                return None

            # Check if cache is still valid
            metadata = results["metadatas"][0] if results["metadatas"] else {}
            cached_at = metadata.get("cached_at")
            if cached_at:
                cached_time = datetime.fromisoformat(cached_at)
                if datetime.utcnow() - cached_time < self.cache_ttl:
                    return json.loads(results["documents"][0])

            return None
        except Exception as e:
            logger.warning(f"Cache lookup failed: {e}")
            return None

    def _cache_company_data(
        self,
        company: HarmonicCompany,
        founders: list[HarmonicPerson],
    ):
        """Cache company data with timestamp for historical tracking."""
        now = datetime.utcnow()
        timestamp = now.isoformat()

        # Build document for caching
        doc = {
            "company": asdict(company),
            "founders": [asdict(f) for f in founders],
            "cached_at": timestamp,
        }

        doc_id = self._generate_doc_id(company.id, "company_snapshot", timestamp[:10])

        # Store in main collection
        self.collection.upsert(
            ids=[doc_id],
            documents=[json.dumps(doc)],
            metadatas=[{
                "company_id": company.id,
                "company_name": company.name,
                "domain": company.domain or "",
                "document_type": "company_snapshot",
                "cached_at": timestamp,
                "headcount": company.headcount or 0,
                "web_traffic": company.web_traffic or 0,
                "funding_total": company.funding_total or 0,
            }],
        )

        # Track changes for historical analysis
        self._track_changes(company)

    def _track_changes(self, company: HarmonicCompany):
        """Track metric changes over time."""
        now = datetime.utcnow()
        date_key = now.strftime("%Y-%m-%d")

        # Get previous snapshot if exists
        try:
            prev_results = self.changes_collection.get(
                where={
                    "$and": [
                        {"company_id": {"$eq": company.id}},
                        {"metric_date": {"$lt": date_key}},
                    ]
                },
                include=["metadatas"],
            )
        except Exception:
            prev_results = {"metadatas": []}

        prev_metrics = prev_results["metadatas"][-1] if prev_results.get("metadatas") else {}

        # Calculate deltas
        headcount_delta = None
        if company.headcount and prev_metrics.get("headcount"):
            headcount_delta = company.headcount - prev_metrics["headcount"]

        traffic_delta = None
        if company.web_traffic and prev_metrics.get("web_traffic"):
            traffic_delta = company.web_traffic - prev_metrics["web_traffic"]

        # Store daily snapshot
        change_id = self._generate_doc_id(company.id, "daily_metrics", date_key)

        change_doc = {
            "company_id": company.id,
            "company_name": company.name,
            "date": date_key,
            "headcount": company.headcount,
            "headcount_delta": headcount_delta,
            "headcount_change_90d_pct": company.headcount_change_90d,
            "web_traffic": company.web_traffic,
            "web_traffic_delta": traffic_delta,
            "web_traffic_change_30d_pct": company.web_traffic_change_30d,
            "funding_total": company.funding_total,
            "funding_stage": company.funding_stage,
        }

        self.changes_collection.upsert(
            ids=[change_id],
            documents=[json.dumps(change_doc)],
            metadatas={
                "company_id": company.id,
                "company_name": company.name,
                "metric_date": date_key,
                "headcount": company.headcount or 0,
                "web_traffic": company.web_traffic or 0,
            },
        )

    def _parse_url(self, url: str) -> tuple[str, Optional[str]]:
        """
        Parse URL to determine type and extract domain/LinkedIn URL.

        Args:
            url: Company website URL, LinkedIn company URL, or LinkedIn person URL

        Returns:
            Tuple of (url_type, normalized_url) where url_type is one of:
            - "company_domain": Company website (e.g., stripe.com)
            - "company_linkedin": Company LinkedIn URL
            - "person_linkedin": Person LinkedIn URL
        """
        from urllib.parse import urlparse

        url = url.strip()

        # Add https if no scheme provided
        if not url.startswith(("http://", "https://")):
            url = "https://" + url

        parsed = urlparse(url)
        host = parsed.netloc.lower().replace("www.", "")
        path = parsed.path.rstrip("/")

        # Check if it's a LinkedIn URL
        if "linkedin.com" in host:
            # Company LinkedIn: linkedin.com/company/stripe
            if "/company/" in path:
                return ("company_linkedin", url)
            # Person LinkedIn: linkedin.com/in/johndoe
            elif "/in/" in path:
                return ("person_linkedin", url)
            else:
                # Unknown LinkedIn URL type
                return ("company_linkedin", url)
        else:
            # Regular company website - extract domain
            domain = host
            return ("company_domain", domain)

    def _lookup_by_url(self, url: str) -> Optional[HarmonicCompany]:
        """
        Look up company in Harmonic by URL (exact match).

        Args:
            url: Company website URL or LinkedIn URL

        Returns:
            HarmonicCompany if found, None otherwise

        Raises:
            ValueError: If URL format is invalid or unsupported
        """
        url_type, normalized = self._parse_url(url)

        if url_type == "company_domain":
            return self.client.lookup_company(domain=normalized)
        elif url_type == "company_linkedin":
            return self.client.lookup_company(linkedin_url=normalized)
        elif url_type == "person_linkedin":
            # For person URLs, we need to look up the person first,
            # then get their current company
            person = self.client.lookup_person(normalized)
            if person and person.raw_data:
                # Get company from person's current experience
                experience = person.raw_data.get("experience", []) or []
                for exp in experience:
                    if exp.get("is_current_position"):
                        company_urn = exp.get("company_urn")
                        if company_urn and "company:" in company_urn:
                            company_id = company_urn.split("company:")[-1]
                            return self.client.get_company(company_id)
            return None
        else:
            raise ValueError(f"Unsupported URL type: {url}")

    def _format_company_profile(
        self,
        company: HarmonicCompany,
        founders: list[HarmonicPerson],
    ) -> str:
        """Format company data as readable profile text."""
        lines = [
            f"# {company.name}",
            "",
        ]

        if company.description:
            lines.extend([company.description, ""])

        # Basic info
        lines.append("## Company Overview")
        if company.domain:
            lines.append(f"- **Website:** {company.website_url or company.domain}")
        if company.founded_year:
            lines.append(f"- **Founded:** {company.founded_year}")
        if company.customer_type:
            lines.append(f"- **Type:** {company.customer_type}")
        if company.tags:
            lines.append(f"- **Tags:** {', '.join(company.tags[:5])}")
        lines.append("")

        # Metrics
        lines.append("## Key Metrics")
        if company.headcount:
            change_str = ""
            if company.headcount_change_90d:
                sign = "+" if company.headcount_change_90d > 0 else ""
                change_str = f" ({sign}{company.headcount_change_90d:.1f}% 90d)"
            lines.append(f"- **Headcount:** {company.headcount:,}{change_str}")

        if company.web_traffic:
            change_str = ""
            if company.web_traffic_change_30d:
                sign = "+" if company.web_traffic_change_30d > 0 else ""
                change_str = f" ({sign}{company.web_traffic_change_30d:.1f}% 30d)"
            lines.append(f"- **Web Traffic:** {company.web_traffic:,}{change_str}")
        lines.append("")

        # Funding
        if company.funding_total or company.funding_stage:
            lines.append("## Funding")
            if company.funding_total:
                lines.append(f"- **Total Raised:** ${company.funding_total:,.0f}")
            if company.funding_stage:
                lines.append(f"- **Stage:** {company.funding_stage}")
            if company.funding_last_amount and company.funding_last_date:
                lines.append(f"- **Last Round:** ${company.funding_last_amount:,.0f} ({company.funding_last_date})")
            if company.investors:
                lines.append(f"- **Investors:** {', '.join(company.investors[:5])}")
            lines.append("")

        # Founders
        if founders:
            lines.append("## Founders & Leadership")
            for person in founders[:5]:
                title = f" - {person.title}" if person.title else ""
                lines.append(f"- **{person.name}**{title}")
            lines.append("")

        return "\n".join(lines)

    def _format_signals(self, company: HarmonicCompany) -> str:
        """Format company signals as readable text."""
        lines = [f"# Signals for {company.name}", ""]

        # Hiring signals
        lines.append("## Hiring & Team Changes")
        if company.headcount_change_90d:
            if company.headcount_change_90d > 10:
                lines.append(f"🚀 **Rapid Growth:** Headcount up {company.headcount_change_90d:.1f}% in 90 days")
            elif company.headcount_change_90d > 0:
                lines.append(f"📈 **Growing:** Headcount up {company.headcount_change_90d:.1f}% in 90 days")
            elif company.headcount_change_90d < -10:
                lines.append(f"⚠️ **Contraction:** Headcount down {abs(company.headcount_change_90d):.1f}% in 90 days")
            else:
                lines.append(f"Headcount change: {company.headcount_change_90d:.1f}% in 90 days")
        else:
            lines.append("No headcount change data available")
        lines.append("")

        # Web traffic signals
        lines.append("## Web Traffic & Traction")
        if company.web_traffic_change_30d:
            if company.web_traffic_change_30d > 20:
                lines.append(f"🔥 **Traffic Surge:** Web traffic up {company.web_traffic_change_30d:.1f}% in 30 days")
            elif company.web_traffic_change_30d > 0:
                lines.append(f"📈 **Traffic Growing:** Up {company.web_traffic_change_30d:.1f}% in 30 days")
            elif company.web_traffic_change_30d < -20:
                lines.append(f"⚠️ **Traffic Decline:** Down {abs(company.web_traffic_change_30d):.1f}% in 30 days")
            else:
                lines.append(f"Traffic change: {company.web_traffic_change_30d:.1f}% in 30 days")
        else:
            lines.append("No web traffic change data available")
        lines.append("")

        # Funding signals
        lines.append("## Funding Signals")
        if company.funding_last_date:
            lines.append(f"- Last funding: {company.funding_last_date}")
        if company.funding_stage:
            lines.append(f"- Current stage: {company.funding_stage}")
        if not company.funding_last_date and not company.funding_stage:
            lines.append("No recent funding activity tracked")

        return "\n".join(lines)

    # =========================================================================
    # DATA SOURCE PROTOCOL IMPLEMENTATION
    # =========================================================================

    def get_company_profile(self, url: str) -> RetrievalResult:
        """
        Retrieve company profile from Harmonic API by URL.

        Args:
            url: Company website URL or LinkedIn URL (company or person)

        Implements DataSource Protocol.
        """
        try:
            # Look up company by URL (exact match)
            company = self._lookup_by_url(url)
            if not company:
                return RetrievalResult(
                    content=f"Company not found in Harmonic for URL: {url}",
                    sources=[],
                    raw_results=[],
                )

            # Extract key people from company contact info (faster than API calls)
            founders = []
            contact = company.raw_data.get("contact", {}) or {}
            primary_email = contact.get("primary_email")
            primary_person_id = contact.get("primary_email_person_id")

            # Fetch primary contact if available (usually a founder/exec)
            if primary_person_id:
                try:
                    person = self.client.get_person(str(primary_person_id))
                    if person:
                        founders.append(person)
                except HarmonicAPIError:
                    pass

            # Check for manual corrections first
            if company.domain:
                corrected = get_corrected_founders(company.domain)
                if corrected:
                    # Convert corrections to HarmonicPerson-like objects
                    founders = [
                        HarmonicPerson(
                            id=f"correction_{i}",
                            name=f["name"],
                            title=f.get("title"),
                            linkedin_url=f.get("linkedin_url"),
                            email=None,
                            raw_data={},
                            fetched_at=datetime.utcnow().isoformat(),
                        )
                        for i, f in enumerate(corrected)
                    ]

            # Cache for historical tracking
            self._cache_company_data(company, founders)

            # Format content
            content = self._format_company_profile(company, founders)

            # Build source for citations
            source = Source(
                id=f"harmonic_{company.id}",
                title=f"{company.name} Company Profile",
                document_type="company_profile",
                description=company.description[:150] if company.description else "",
                date=company.fetched_at[:10],
                url=f"https://console.harmonic.ai/companies/{company.id}",
            )

            return RetrievalResult(
                content=content,
                sources=[source],
                raw_results=[asdict(company)],
            )

        except HarmonicAPIError as e:
            return RetrievalResult(
                content=f"Error fetching company profile from Harmonic: {e}",
                sources=[],
                raw_results=[],
            )

    def get_recent_news(
        self,
        url: str,
        days: int = DEFAULT_NEWS_DAYS,
    ) -> RetrievalResult:
        """
        Retrieve recent updates/changes for company by URL.

        Args:
            url: Company website URL or LinkedIn URL

        Note: Harmonic doesn't have a dedicated news endpoint.
        This returns recent changes in metrics as "news".
        """
        try:
            company = self._lookup_by_url(url)
            if not company:
                return RetrievalResult(
                    content=f"Company not found in Harmonic for URL: {url}",
                    sources=[],
                    raw_results=[],
                )

            # Query historical changes from cache
            try:
                cutoff = (datetime.utcnow() - timedelta(days=days)).strftime("%Y-%m-%d")
                results = self.changes_collection.get(
                    where={
                        "$and": [
                            {"company_id": {"$eq": company.id}},
                            {"metric_date": {"$gte": cutoff}},
                        ]
                    },
                    include=["documents", "metadatas"],
                )
            except Exception:
                results = {"documents": [], "metadatas": []}

            lines = [f"# Recent Updates for {company.name}", ""]

            if results["documents"]:
                lines.append("## Tracked Changes (Last 30 Days)")
                for doc, meta in zip(results["documents"], results["metadatas"]):
                    data = json.loads(doc)
                    date = data.get("date", "")
                    lines.append(f"\n### {date}")
                    if data.get("headcount_delta"):
                        lines.append(f"- Headcount: {data['headcount_delta']:+d}")
                    if data.get("web_traffic_delta"):
                        lines.append(f"- Web Traffic: {data['web_traffic_delta']:+d}")
            else:
                lines.append("No historical change data available yet.")
                lines.append("Data will be tracked from first retrieval.")

            # Add current metrics as recent "news"
            lines.extend([
                "",
                "## Current Snapshot",
            ])
            if company.headcount_change_90d:
                lines.append(f"- Headcount trend (90d): {company.headcount_change_90d:+.1f}%")
            if company.web_traffic_change_30d:
                lines.append(f"- Traffic trend (30d): {company.web_traffic_change_30d:+.1f}%")

            source = Source(
                id=f"harmonic_{company.id}_updates",
                title=f"{company.name} Recent Updates",
                document_type="news_article",
                description="Company metric changes from Harmonic",
                date=datetime.utcnow().strftime("%Y-%m-%d"),
                url=f"https://console.harmonic.ai/companies/{company.id}",
            )

            return RetrievalResult(
                content="\n".join(lines),
                sources=[source],
                raw_results=results.get("documents", []),
            )

        except HarmonicAPIError as e:
            return RetrievalResult(
                content=f"Error fetching updates from Harmonic: {e}",
                sources=[],
                raw_results=[],
            )

    def get_key_signals(self, url: str) -> RetrievalResult:
        """
        Retrieve key signals (hiring, traffic, funding) from Harmonic by URL.

        Args:
            url: Company website URL or LinkedIn URL

        Implements DataSource Protocol.
        """
        try:
            company = self._lookup_by_url(url)
            if not company:
                return RetrievalResult(
                    content=f"Company not found in Harmonic for URL: {url}",
                    sources=[],
                    raw_results=[],
                )

            content = self._format_signals(company)

            source = Source(
                id=f"harmonic_{company.id}_signals",
                title=f"{company.name} Key Signals",
                document_type="signal_report",
                description="Hiring, traffic, and funding signals from Harmonic",
                date=datetime.utcnow().strftime("%Y-%m-%d"),
                url=f"https://console.harmonic.ai/companies/{company.id}",
                signal_type="composite",
            )

            return RetrievalResult(
                content=content,
                sources=[source],
                raw_results=[asdict(company)],
            )

        except HarmonicAPIError as e:
            return RetrievalResult(
                content=f"Error fetching signals from Harmonic: {e}",
                sources=[],
                raw_results=[],
            )

    def list_companies(self) -> list[str]:
        """
        List companies tracked in cache.

        Note: Harmonic supports dynamic lookup of any company.
        Returns cached companies plus "*" marker for dynamic lookup.
        """
        try:
            results = self.collection.get(
                include=["metadatas"],
            )

            companies = set()
            for meta in results.get("metadatas", []):
                if meta.get("company_name"):
                    companies.add(meta["company_name"])

            # Always include "*" to indicate dynamic lookup is supported
            company_list = sorted(companies)
            company_list.append("*")  # Harmonic can look up any company
            return company_list
        except Exception:
            return ["*"]  # Indicates any company can be looked up

    # =========================================================================
    # ADDITIONAL METHODS
    # =========================================================================

    def search_companies(self, query: str, limit: int = 10) -> list[HarmonicCompany]:
        """
        Search for companies using natural language.

        Args:
            query: Search query (e.g., "AI startups in healthcare")
            limit: Maximum results

        Returns:
            List of HarmonicCompany objects
        """
        return self.client.search_companies(query, limit=limit)

    def get_historical_metrics(
        self,
        company_name: str,
        days: int = 90,
    ) -> list[dict]:
        """
        Get historical metrics for a company.

        Args:
            company_name: Company to look up
            days: Number of days of history

        Returns:
            List of daily metric snapshots
        """
        company = self._lookup_company_by_name(company_name)
        if not company:
            return []

        cutoff = (datetime.utcnow() - timedelta(days=days)).strftime("%Y-%m-%d")

        try:
            results = self.changes_collection.get(
                where={
                    "$and": [
                        {"company_id": {"$eq": company.id}},
                        {"metric_date": {"$gte": cutoff}},
                    ]
                },
                include=["documents"],
            )

            return [json.loads(doc) for doc in results.get("documents", [])]
        except Exception:
            return []

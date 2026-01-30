"""
Meeting Briefing Agent - LangGraph Implementation
=================================================

A LangGraph-based agent that generates comprehensive meeting briefings
for venture capital investors by retrieving and synthesizing company data.

Architecture:
- Uses Protocol pattern for data source abstraction (easy API integration)
- LangGraph StateGraph for deterministic workflow
- Inline citations with clickable references
- Full LangSmith tracing support

Workflow: validate → profile → news → signals → synthesize
"""

from __future__ import annotations

import time
import hashlib
from abc import ABC, abstractmethod
from pathlib import Path
from dataclasses import dataclass, field
from datetime import datetime
from typing import (
    Annotated,
    Any,
    Literal,
    Optional,
    Protocol,
    TypedDict,
    runtime_checkable,
)
from uuid import uuid4

# Guarded imports for optional dependencies
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

import chromadb
from langgraph.graph import StateGraph, START, END
from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage, SystemMessage

from tools.meeting_briefing_tools import MeetingBriefingTools
from observability.langsmith import (
    tracing_enabled,
    TracingContext,
    trace_step,
)

# =============================================================================
# CONFIGURATION
# =============================================================================

DEFAULT_NEWS_DAYS = 30
DEFAULT_LLM_MODEL = "gpt-4o-mini"

# =============================================================================
# DATA MODELS
# =============================================================================

@dataclass
class Source:
    """
    Represents a citation source from retrieval.

    This is the atomic unit for citation tracking. Each piece of retrieved
    content should have an associated Source for proper attribution.
    """
    id: str
    title: str
    document_type: str  # "company_profile", "news_article", "signal_report"
    description: str
    date: Optional[str] = None
    url: Optional[str] = None  # For future API sources
    signal_type: Optional[str] = None  # For signal reports
    similarity_score: Optional[float] = None

    def to_reference(self, index: int) -> str:
        """Format as a markdown reference entry."""
        parts = [f"[{index}]"]

        if self.title:
            parts.append(f"**{self.title}**")

        if self.date:
            parts.append(f"({self.date})")

        if self.document_type:
            type_label = self.document_type.replace("_", " ").title()
            parts.append(f"- {type_label}")

        if self.signal_type:
            parts.append(f"[{self.signal_type}]")

        if self.url:
            # Make clickable if URL available
            return f"[{' '.join(parts)}]({self.url})"

        if self.description:
            parts.append(f"- {self.description[:100]}...")

        return " ".join(parts)


@dataclass
class RetrievalResult:
    """
    Result from a data source retrieval operation.

    Contains both the content for synthesis and source metadata
    for citation tracking.
    """
    content: str
    sources: list[Source] = field(default_factory=list)
    raw_results: list[dict] = field(default_factory=list)  # Original API response

    @property
    def source_count(self) -> int:
        return len(self.sources)

    @property
    def source_ids(self) -> list[str]:
        return [s.id for s in self.sources]


class BriefingState(TypedDict, total=False):
    """
    LangGraph state for the meeting briefing workflow.

    This state flows through each node, accumulating retrieval results
    and citation sources until final synthesis.
    """
    # Input
    url: str  # Company website or LinkedIn URL
    run_id: str

    # Derived from lookup (set by validate node)
    company_name: str  # Resolved company name from Harmonic

    # Retrieval results (populated by retriever nodes)
    profile_result: Optional[RetrievalResult]
    news_result: Optional[RetrievalResult]
    signals_result: Optional[RetrievalResult]

    # All sources for citation (accumulated across retrievals)
    all_sources: list[Source]

    # Output
    briefing_markdown: Optional[str]

    # Metadata & observability
    error: Optional[str]
    step_timings_ms: dict[str, int]
    tracing_context: Optional[TracingContext]

    # Timing
    start_time: Optional[float]
    total_elapsed_ms: Optional[int]

    # Injected data source for retrieval nodes
    _data_source: Optional[Any]


# =============================================================================
# DATA SOURCE PROTOCOL (Abstract Interface for API Integration)
# =============================================================================

@runtime_checkable
class DataSource(Protocol):
    """
    Protocol defining the interface for meeting briefing data sources.

    All methods accept a URL (company website or LinkedIn URL) for exact matching.
    This prevents hallucinations from ambiguous company names.

    Example:
        class HarmonicDataSource:
            def __init__(self, api_key: str):
                self.client = HarmonicClient(api_key)

            def get_company_profile(self, url: str) -> RetrievalResult:
                company = self.client.lookup_company(domain=url)
                return RetrievalResult(...)

        # Use it:
        agent = MeetingBriefingAgent(data_source=HarmonicDataSource(api_key))
        result = agent.prepare_briefing("https://stripe.com")
    """

    def get_company_profile(self, url: str) -> RetrievalResult:
        """
        Retrieve company profile/overview information.

        Args:
            url: Company website URL or LinkedIn URL

        Returns:
            RetrievalResult with company overview content and sources
        """
        ...

    def get_recent_news(
        self,
        url: str,
        days: int = DEFAULT_NEWS_DAYS
    ) -> RetrievalResult:
        """
        Retrieve recent news articles about the company.

        Args:
            url: Company website URL or LinkedIn URL
            days: Number of days to look back

        Returns:
            RetrievalResult with news content and sources
        """
        ...

    def get_key_signals(self, url: str) -> RetrievalResult:
        """
        Retrieve strategic signals and indicators.

        Args:
            url: Company website URL or LinkedIn URL

        Returns:
            RetrievalResult with signal content and sources
        """
        ...

    def list_companies(self) -> list[str]:
        """
        List all companies available in this data source.

        Returns:
            List of company names or "*" for dynamic lookup
        """
        ...


# =============================================================================
# LANGCHAIN TOOLS DATA SOURCE (Uses MeetingBriefingTools)
# =============================================================================

class LangChainToolsDataSource:
    """
    DataSource implementation that uses MeetingBriefingTools for ChromaDB retrieval.

    This bridges the LangChain tools with the LangGraph workflow by wrapping
    MeetingBriefingTools and converting results to RetrievalResult format.

    Usage:
        # With default settings
        source = LangChainToolsDataSource()

        # With custom ChromaDB path
        source = LangChainToolsDataSource(persist_directory="./my_chroma_db")

        # Use with agent
        agent = MeetingBriefingAgent(data_source=source)
    """

    # Default paths matching ingestion.py
    DEFAULT_PERSIST_DIR = str(Path(__file__).parent / "chroma_db")
    DEFAULT_COLLECTION = "meeting_briefing_docs"

    def __init__(
        self,
        chroma_client: Optional[chromadb.Client] = None,
        collection_name: Optional[str] = None,
        persist_directory: Optional[str] = None,
    ):
        """
        Initialize the LangChain tools data source.

        Args:
            chroma_client: Existing ChromaDB client (optional)
            collection_name: Name of the ChromaDB collection (default: meeting_briefing_docs)
            persist_directory: Path to persist ChromaDB data (default: agents/meeting_briefing/chroma_db)
        """
        # Use defaults matching ingestion.py
        collection_name = collection_name or self.DEFAULT_COLLECTION
        persist_directory = persist_directory or self.DEFAULT_PERSIST_DIR

        # Use MeetingBriefingTools which now has OpenAI embeddings configured
        self.tools = MeetingBriefingTools(
            chroma_client=chroma_client,
            collection_name=collection_name,
            persist_directory=persist_directory,
        )
        # Access the underlying collection for raw queries
        self.collection = self.tools.collection

    def _generate_source_id(self, content: str, metadata: dict) -> str:
        """Generate stable ID from content hash."""
        hash_input = f"{content[:200]}|{metadata.get('company_name', '')}|{metadata.get('document_type', '')}"
        return hashlib.md5(hash_input.encode()).hexdigest()[:12]

    def _query_to_retrieval_result(
        self,
        results: dict,
        document_type: str,
        max_results: int = 5,
    ) -> RetrievalResult:
        """Convert ChromaDB query results to RetrievalResult."""
        if not results or not results.get("documents") or not results["documents"][0]:
            return RetrievalResult(content="", sources=[], raw_results=[])

        documents = results["documents"][0][:max_results]
        metadatas = results["metadatas"][0][:max_results] if results.get("metadatas") else []
        distances = results["distances"][0][:max_results] if results.get("distances") else []

        sources = []
        content_parts = []
        raw_results = []

        for idx, doc in enumerate(documents):
            metadata = metadatas[idx] if idx < len(metadatas) else {}
            distance = distances[idx] if idx < len(distances) else None
            similarity = 1 - distance if distance is not None else None

            # Create source
            source_id = metadata.get("id") or self._generate_source_id(doc, metadata)

            source = Source(
                id=source_id,
                title=metadata.get("title", f"{metadata.get('company_name', 'Unknown')} {document_type}"),
                document_type=document_type,
                description=doc[:150] if doc else "",
                date=metadata.get("date"),
                signal_type=metadata.get("signal_type"),
                similarity_score=similarity,
            )
            sources.append(source)

            # Format content
            score_str = f"[Score: {similarity:.2f}]" if similarity else ""
            if document_type == "news_article":
                date = metadata.get("date", "Unknown date")
                content_parts.append(f"[{date}] {score_str}\n{doc}")
            elif document_type == "signal_report":
                signal_type = metadata.get("signal_type", "general")
                content_parts.append(f"[Signal: {signal_type}] {score_str}\n{doc}")
            else:
                content_parts.append(f"{score_str}\n{doc}")

            raw_results.append({
                "content": doc,
                "metadata": metadata,
                "similarity_score": similarity,
            })

        return RetrievalResult(
            content="\n\n---\n\n".join(content_parts) if content_parts else "",
            sources=sources,
            raw_results=raw_results,
        )

    def _extract_company_from_url(self, url: str) -> str:
        """Extract company name/domain from URL for ChromaDB queries."""
        from urllib.parse import urlparse
        url = url.strip()
        if not url.startswith(("http://", "https://")):
            url = "https://" + url
        parsed = urlparse(url)
        # Use domain as the search term
        domain = parsed.netloc.replace("www.", "")
        # Remove TLD for better matching
        company = domain.split(".")[0] if domain else url
        return company.title()

    def get_company_profile(self, url: str) -> RetrievalResult:
        """
        Retrieve company profile using MeetingBriefingTools.

        Args:
            url: Company URL (domain extracted for ChromaDB query)
        """
        company_name = self._extract_company_from_url(url)
        try:
            results = self.collection.query(
                query_texts=[f"company profile overview for {company_name}"],
                n_results=5,
                where={"document_type": {"$eq": "company_profile"}},
                include=["documents", "metadatas", "distances"],
            )
            return self._query_to_retrieval_result(results, "company_profile", max_results=5)
        except Exception as e:
            return RetrievalResult(
                content=f"Error retrieving company profile: {str(e)}",
                sources=[],
                raw_results=[],
            )

    def get_recent_news(
        self,
        url: str,
        days: int = DEFAULT_NEWS_DAYS,
    ) -> RetrievalResult:
        """
        Retrieve recent news using MeetingBriefingTools.

        Args:
            url: Company URL (domain extracted for ChromaDB query)
        """
        company_name = self._extract_company_from_url(url)
        try:
            results = self.collection.query(
                query_texts=[f"recent news about {company_name}"],
                n_results=10,
                where={"document_type": {"$eq": "news_article"}},
                include=["documents", "metadatas", "distances"],
            )
            return self._query_to_retrieval_result(results, "news_article", max_results=10)
        except Exception as e:
            return RetrievalResult(
                content=f"Error retrieving news: {str(e)}",
                sources=[],
                raw_results=[],
            )

    def get_key_signals(self, url: str) -> RetrievalResult:
        """
        Retrieve key signals using MeetingBriefingTools.

        Args:
            url: Company URL (domain extracted for ChromaDB query)
        """
        company_name = self._extract_company_from_url(url)
        try:
            results = self.collection.query(
                query_texts=[f"key signals and strategic insights for {company_name}"],
                n_results=7,
                where={"document_type": {"$eq": "signal_report"}},
                include=["documents", "metadatas", "distances"],
            )
            return self._query_to_retrieval_result(results, "signal_report", max_results=7)
        except Exception as e:
            return RetrievalResult(
                content=f"Error retrieving signals: {str(e)}",
                sources=[],
                raw_results=[],
            )

    def list_companies(self) -> list[str]:
        """
        List available companies from ChromaDB collection.

        Queries the collection metadata for unique company names.
        Returns ["*"] to indicate dynamic lookup is supported if no
        companies are found.
        """
        try:
            results = self.collection.get(include=["metadatas"])
            companies = set()
            for meta in results.get("metadatas", []):
                if meta.get("company_name"):
                    companies.add(meta["company_name"])
            if companies:
                return sorted(companies)
            return ["*"]  # Indicates dynamic lookup supported
        except Exception:
            return ["*"]

    def get_langchain_tools(self):
        """
        Get the underlying LangChain tools for direct use if needed.

        Returns:
            List of LangChain Tool objects
        """
        return self.tools.get_langchain_tools()


# =============================================================================
# HARMONIC DATA SOURCE (Real API Integration)
# =============================================================================

# Import HarmonicDataSource from dedicated module
# This provides real Harmonic.ai API integration with ChromaDB caching
try:
    from .harmonic_source import HarmonicDataSource
except ImportError:
    # Fallback placeholder if harmonic_source not available
    class HarmonicDataSource:
        """
        Harmonic API data source for company intelligence.

        Requires: HARMONIC_API_KEY environment variable

        Usage:
            source = HarmonicDataSource()
            agent = MeetingBriefingAgent(data_source=source)
        """

        def __init__(self, api_key: Optional[str] = None):
            raise ImportError(
                "HarmonicDataSource requires harmonic_source module. "
                "Ensure harmonic_client.py and harmonic_source.py are present."
            )


class NewsDataSource:
    """
    News API data source for web search and news retrieval.

    IMPLEMENTATION GUIDE:
    ---------------------
    1. Install the appropriate news API SDK
    2. Set env: NEWS_API_KEY
    3. Use for news retrieval, combine with other sources for profiles

    Best used as a NEWS SOURCE in combination with other profile sources.
    """

    def __init__(self, api_key: Optional[str] = None):
        import os
        self.api_key = api_key or os.getenv("NEWS_API_KEY")
        if not self.api_key:
            raise ValueError("NEWS_API_KEY required")
        # TODO: Initialize news API client
        # self.client = NewsClient(api_key=self.api_key)
        raise NotImplementedError("NewsDataSource not yet implemented")

    def get_company_profile(self, company_name: str) -> RetrievalResult:
        # News APIs are better for news - consider using a different source for profiles
        raise NotImplementedError

    def get_recent_news(self, company_name: str, days: int = 30) -> RetrievalResult:
        # TODO: Implement news search
        # results = self.client.search(
        #     query=f"{company_name} news announcements",
        #     max_results=10,
        #     include_domains=["techcrunch.com", "reuters.com", ...],
        # )
        raise NotImplementedError

    def get_key_signals(self, company_name: str) -> RetrievalResult:
        # TODO: Could search for specific signal types
        raise NotImplementedError

    def list_companies(self) -> list[str]:
        # News APIs don't have a company list - use another source
        raise NotImplementedError


class CompositeDataSource:
    """
    Combines multiple data sources for comprehensive coverage.

    IMPLEMENTATION GUIDE:
    ---------------------
    Use this to combine best-of-breed APIs:
    - Harmonic for company profiles and signals
    - News API for recent news
    - Custom CRM for portfolio data

    Example:
        source = CompositeDataSource(
            profile_source=HarmonicDataSource(api_key),
            news_source=NewsDataSource(api_key),
            signals_source=HarmonicDataSource(api_key),
        )
    """

    def __init__(
        self,
        profile_source: DataSource,
        news_source: DataSource,
        signals_source: DataSource,
    ):
        self.profile_source = profile_source
        self.news_source = news_source
        self.signals_source = signals_source

    def get_company_profile(self, company_name: str) -> RetrievalResult:
        return self.profile_source.get_company_profile(company_name)

    def get_recent_news(self, company_name: str, days: int = 30) -> RetrievalResult:
        return self.news_source.get_recent_news(company_name, days)

    def get_key_signals(self, company_name: str) -> RetrievalResult:
        return self.signals_source.get_key_signals(company_name)

    def list_companies(self) -> list[str]:
        # Aggregate from all sources, deduplicate
        companies = set()
        for source in [self.profile_source, self.news_source, self.signals_source]:
            try:
                companies.update(source.list_companies())
            except NotImplementedError:
                pass
        return sorted(companies)


# =============================================================================
# UTILITY FUNCTIONS
# =============================================================================

def normalize_company_name(name: str) -> str:
    """Normalize company name for consistent matching."""
    return name.strip().title()


def build_citation_map(sources: list[Source]) -> dict[str, int]:
    """
    Build a mapping from source ID to citation number.

    Returns:
        Dict mapping source_id -> citation number (1-indexed)
    """
    return {source.id: idx + 1 for idx, source in enumerate(sources)}


def format_references_section(sources: list[Source]) -> str:
    """Format the references section for the briefing."""
    if not sources:
        return ""

    lines = ["### References", ""]
    for idx, source in enumerate(sources, 1):
        lines.append(source.to_reference(idx))

    return "\n".join(lines)


# =============================================================================
# LANGGRAPH NODE FUNCTIONS
# =============================================================================

@trace_step("validate_company", run_type="chain")
def validate_company_node(state: BriefingState) -> dict:
    """
    Validate URL and look up company in Harmonic.

    This is the first node in the graph - validates the URL and looks up
    the company to get its name before retrieval operations.
    """
    start = time.perf_counter()

    url = state["url"]
    ctx = state.get("tracing_context")

    # Get data source from state or create default (HarmonicDataSource)
    data_source = state.get("_data_source")
    if data_source is None:
        from .harmonic_source import HarmonicDataSource
        data_source = HarmonicDataSource()

    error = None
    company_name = None

    # Look up company by URL to validate and get company name
    try:
        # Use the profile retrieval to validate - it will return the company name
        profile_result = data_source.get_company_profile(url)
        if profile_result.sources and profile_result.sources[0].title:
            # Extract company name from the source title (e.g., "Stripe Company Profile" -> "Stripe")
            title = profile_result.sources[0].title
            company_name = title.replace(" Company Profile", "").strip()
        elif profile_result.raw_results:
            # Get name from raw results
            raw = profile_result.raw_results[0] if profile_result.raw_results else {}
            company_name = raw.get("name", url)
        else:
            error = f"Company not found in Harmonic for URL: {url}"
    except Exception as e:
        error = f"Error looking up company: {str(e)}"

    elapsed_ms = int((time.perf_counter() - start) * 1000)

    if ctx:
        ctx.record_step_timing("validate_company", elapsed_ms)

    return {
        "company_name": company_name or url,
        "error": error,
        "step_timings_ms": {**state.get("step_timings_ms", {}), "validate_company": elapsed_ms},
    }


@trace_step("retrieve_profile", run_type="tool")
def retrieve_profile_node(state: BriefingState) -> dict:
    """
    Retrieve company profile information.

    Calls the data source to get company overview/profile data.
    Tracks sources for citation.
    """
    start = time.perf_counter()

    if state.get("error"):
        return {}  # Skip if previous error

    url = state["url"]
    ctx = state.get("tracing_context")
    data_source = state.get("_data_source")
    if data_source is None:
        from .harmonic_source import HarmonicDataSource
        data_source = HarmonicDataSource()

    result = data_source.get_company_profile(url)

    elapsed_ms = int((time.perf_counter() - start) * 1000)

    if ctx:
        ctx.record_step_timing("retrieve_profile", elapsed_ms)
        ctx.record_retrieval("profile", result.source_count, result.source_ids)

    # Accumulate sources
    current_sources = state.get("all_sources", [])

    return {
        "profile_result": result,
        "all_sources": current_sources + result.sources,
        "step_timings_ms": {**state.get("step_timings_ms", {}), "retrieve_profile": elapsed_ms},
    }


@trace_step("retrieve_news", run_type="tool")
def retrieve_news_node(state: BriefingState) -> dict:
    """
    Retrieve recent news articles about the company.

    Calls the data source to get recent news/developments.
    Tracks sources for citation.
    """
    start = time.perf_counter()

    if state.get("error"):
        return {}

    url = state["url"]
    ctx = state.get("tracing_context")
    data_source = state.get("_data_source")
    if data_source is None:
        from .harmonic_source import HarmonicDataSource
        data_source = HarmonicDataSource()

    result = data_source.get_recent_news(url, days=DEFAULT_NEWS_DAYS)

    elapsed_ms = int((time.perf_counter() - start) * 1000)

    if ctx:
        ctx.record_step_timing("retrieve_news", elapsed_ms)
        ctx.record_retrieval("news", result.source_count, result.source_ids)

    current_sources = state.get("all_sources", [])

    return {
        "news_result": result,
        "all_sources": current_sources + result.sources,
        "step_timings_ms": {**state.get("step_timings_ms", {}), "retrieve_news": elapsed_ms},
    }


@trace_step("retrieve_signals", run_type="tool")
def retrieve_signals_node(state: BriefingState) -> dict:
    """
    Retrieve key signals and strategic indicators.

    Calls the data source to get signal reports (hiring, funding, etc.).
    Tracks sources for citation.
    """
    start = time.perf_counter()

    if state.get("error"):
        return {}

    url = state["url"]
    ctx = state.get("tracing_context")
    data_source = state.get("_data_source")
    if data_source is None:
        from .harmonic_source import HarmonicDataSource
        data_source = HarmonicDataSource()

    result = data_source.get_key_signals(url)

    elapsed_ms = int((time.perf_counter() - start) * 1000)

    if ctx:
        ctx.record_step_timing("retrieve_signals", elapsed_ms)
        ctx.record_retrieval("signals", result.source_count, result.source_ids)

    current_sources = state.get("all_sources", [])

    return {
        "signals_result": result,
        "all_sources": current_sources + result.sources,
        "step_timings_ms": {**state.get("step_timings_ms", {}), "retrieve_signals": elapsed_ms},
    }


@trace_step("synthesize_briefing", run_type="llm")
def synthesize_briefing_node(state: BriefingState) -> dict:
    """
    Synthesize all retrieved information into a cohesive briefing.

    Uses LLM to combine profile, news, and signals into a well-structured
    briefing with inline citations.
    """
    start = time.perf_counter()

    if state.get("error"):
        # Return error briefing
        error_markdown = f"""# Meeting Briefing: {state['company_name']}

## Error

{state['error']}

---

*Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}*
*Run ID: {state['run_id']}*
"""
        return {"briefing_markdown": error_markdown}

    company_name = state["company_name"]
    ctx = state.get("tracing_context")
    all_sources = state.get("all_sources", [])

    # Build citation map
    citation_map = build_citation_map(all_sources)

    # Get retrieval results
    profile = state.get("profile_result")
    news = state.get("news_result")
    signals = state.get("signals_result")

    # Format source lists for the prompt
    def format_sources_for_prompt(sources: list[Source]) -> str:
        """Format sources with their citation numbers for the LLM."""
        lines = []
        for source in sources:
            cite_num = citation_map.get(source.id, "?")
            lines.append(f"  - [{cite_num}] {source.title} ({source.document_type})")
        return "\n".join(lines) if lines else "  (none)"

    profile_sources = format_sources_for_prompt(profile.sources if profile else [])
    news_sources = format_sources_for_prompt(news.sources if news else [])
    signals_sources = format_sources_for_prompt(signals.sources if signals else [])

    # Initialize LLM
    llm = ChatOpenAI(model=DEFAULT_LLM_MODEL, temperature=0)

    system_prompt = """You are an AI assistant preparing meeting briefings for venture capital investors.

Your task is to synthesize the provided information into a comprehensive but succinct executive brief. Cover all important points without unnecessary filler.

CITATION FORMAT:
- Use inline citations [1], [2] for key claims and data points
- Cite sources when referencing specific facts, metrics, or quotes

STRUCTURE YOUR OUTPUT EXACTLY AS:

## TL;DR
[2-3 sentences summarizing the most important thing to know going into this meeting.]

## Company Overview
[Brief description of what the company does, stage, and key metrics]

## Key Points
• [Critical point with supporting detail] [1]
• [Second important point] [2]
• [Additional points as needed - include all relevant information]

## Recent Developments
• [Notable recent news, funding, product launches, etc.]

## Signals & Trends
• [Hiring trends, traffic changes, competitive dynamics]

## For This Meeting
• [Key questions to ask]
• [Risks or opportunities to probe]
• [Areas needing clarification]

GUIDELINES:
- Be succinct but comprehensive - don't omit important information
- No fluff or filler, but include all relevant details
- Be direct and opinionated - flag what matters most
- If something is concerning, say so clearly"""

    user_prompt = f"""Create a meeting briefing for **{company_name}**.

## Available Sources (use these citation numbers):
{profile_sources}
{news_sources}
{signals_sources}

## Company Profile
{profile.content if profile else 'No profile data available.'}

## Recent News
{news.content if news else 'No news data available.'}

## Key Signals
{signals.content if signals else 'No signals data available.'}

Synthesize all available information into a comprehensive briefing. Be succinct but don't cut off important details."""

    messages = [
        SystemMessage(content=system_prompt),
        HumanMessage(content=user_prompt)
    ]

    response = llm.invoke(messages)
    briefing_content = response.content

    step_timings = state.get("step_timings_ms", {})

    # Replace citation numbers [1], [2], etc. with clickable markdown links
    import re

    def make_citations_clickable(text: str, sources: list[Source]) -> str:
        """Replace [N] citations with clickable markdown links."""
        def replace_citation(match):
            cite_num = int(match.group(1))
            if 1 <= cite_num <= len(sources):
                source = sources[cite_num - 1]
                if source.url:
                    return f"[[{cite_num}]]({source.url})"
            return match.group(0)  # Return unchanged if no URL

        return re.sub(r'\[(\d+)\]', replace_citation, text)

    briefing_with_links = make_citations_clickable(briefing_content, all_sources)

    # Assemble final markdown - clean and compact
    final_markdown = f"""# {company_name} | Meeting Brief
*{datetime.now().strftime('%Y-%m-%d')}*

{briefing_with_links}
"""

    elapsed_ms = int((time.perf_counter() - start) * 1000)

    if ctx:
        ctx.record_step_timing("synthesize_briefing", elapsed_ms)

    return {
        "briefing_markdown": final_markdown,
        "step_timings_ms": {**step_timings, "synthesize_briefing": elapsed_ms},
    }


# =============================================================================
# LANGGRAPH WORKFLOW BUILDER
# =============================================================================

def build_briefing_graph() -> StateGraph:
    """
    Build the LangGraph workflow for meeting briefings.

    Graph structure:
        START
          ↓
        validate_company
          ↓
        retrieve_profile
          ↓
        retrieve_news
          ↓
        retrieve_signals
          ↓
        synthesize_briefing
          ↓
        END

    This is a deterministic flow - all retrievers are always called.
    Future enhancement: Add conditional edges for error handling or
    parallel retrieval.
    """
    # Create the graph with our state schema
    graph = StateGraph(BriefingState)

    # Add nodes
    graph.add_node("validate_company", validate_company_node)
    graph.add_node("retrieve_profile", retrieve_profile_node)
    graph.add_node("retrieve_news", retrieve_news_node)
    graph.add_node("retrieve_signals", retrieve_signals_node)
    graph.add_node("synthesize_briefing", synthesize_briefing_node)

    # Add edges (deterministic flow)
    graph.add_edge(START, "validate_company")
    graph.add_edge("validate_company", "retrieve_profile")
    graph.add_edge("retrieve_profile", "retrieve_news")
    graph.add_edge("retrieve_news", "retrieve_signals")
    graph.add_edge("retrieve_signals", "synthesize_briefing")
    graph.add_edge("synthesize_briefing", END)

    return graph


# =============================================================================
# MEETING BRIEFING AGENT (Main Interface)
# =============================================================================

class MeetingBriefingAgent:
    """
    Meeting briefing agent with LangGraph workflow and LangSmith tracing.

    This is the main interface for generating meeting briefings. It:
    - Accepts a company/person URL as input (exact match via Harmonic)
    - Runs the LangGraph workflow
    - Returns a structured result with the briefing and metadata

    Usage:
        # Default: Uses Harmonic API for company data
        agent = MeetingBriefingAgent()

        # Lookup by company website
        result = agent.prepare_briefing("https://stripe.com")

        # Lookup by company LinkedIn
        result = agent.prepare_briefing("https://linkedin.com/company/stripe")

        # Lookup by person LinkedIn (gets their current company)
        result = agent.prepare_briefing("https://linkedin.com/in/johncollison")

        print(result["briefing_markdown"])

    Args:
        data_source: DataSource implementation (defaults to HarmonicDataSource)
        time_window_days: Days to look back for news (default: 30)
    """

    def __init__(
        self,
        data_source: Optional[DataSource] = None,
        time_window_days: int = DEFAULT_NEWS_DAYS,
    ):
        """
        Initialize the meeting briefing agent.

        Args:
            data_source: Data source for retrieval (defaults to HarmonicDataSource)
            time_window_days: Days to look back for news articles
        """
        if data_source is None:
            from .harmonic_source import HarmonicDataSource
            data_source = HarmonicDataSource()
        self.data_source = data_source
        self.time_window_days = time_window_days

        # Build and compile the graph
        self.graph = build_briefing_graph().compile()

    def prepare_briefing(self, url: str) -> dict:
        """
        Prepare a comprehensive meeting briefing for a company.

        This is the main entry point. The entire run is traced in LangSmith
        when tracing is enabled.

        Args:
            url: Company website URL, LinkedIn company URL, or LinkedIn person URL.
                 Examples:
                 - "stripe.com" or "https://stripe.com"
                 - "https://linkedin.com/company/stripe"
                 - "https://linkedin.com/in/johncollison" (gets their company)

        Returns:
            Dict containing:
                - url: The input URL
                - company_name: Resolved company name from Harmonic
                - run_id: Unique run identifier
                - timestamp: ISO timestamp of generation
                - briefing_markdown: The complete briefing document
                - retrieval_counts: Documents retrieved per source type
                - retrieval_doc_ids: Document IDs per source type
                - step_timings_ms: Timing for each workflow step
                - total_elapsed_ms: Total execution time
                - success: Whether the briefing was generated successfully
                - error: Error message if any
        """
        run_id = str(uuid4())
        start_time = time.perf_counter()

        # Create tracing context (company_name will be resolved during validation)
        ctx = TracingContext(
            run_id=run_id,
            company_name=url,  # Will be updated after validation
            time_window_days=self.time_window_days,
        )
        ctx.start()

        error_str = None
        output_markdown = None
        company_name = url

        try:
            # Build initial state
            initial_state: BriefingState = {
                "url": url,
                "run_id": run_id,
                "company_name": "",  # Will be resolved by validate node
                "profile_result": None,
                "news_result": None,
                "signals_result": None,
                "all_sources": [],
                "briefing_markdown": None,
                "error": None,
                "step_timings_ms": {},
                "tracing_context": ctx,
                "start_time": start_time,
                "total_elapsed_ms": None,
                # Inject data source into state for nodes to use
                "_data_source": self.data_source,
            }

            # Run the graph
            final_state = self.graph.invoke(initial_state)

            output_markdown = final_state.get("briefing_markdown", "")
            error_str = final_state.get("error")
            company_name = final_state.get("company_name", url)

        except Exception as e:
            error_str = str(e)
            output_markdown = f"# Error\n\nFailed to generate briefing for {url}: {error_str}"

        finally:
            ctx.end(output=output_markdown, error=error_str)

        total_elapsed_ms = int((time.perf_counter() - start_time) * 1000)

        return {
            "url": url,
            "company_name": company_name,
            "run_id": run_id,
            "timestamp": datetime.now().isoformat(),
            "briefing_markdown": output_markdown,
            "retrieval_counts": ctx.retrieval_counts.copy(),
            "retrieval_doc_ids": ctx.retrieval_doc_ids.copy(),
            "step_timings_ms": ctx.step_timings.copy(),
            "total_elapsed_ms": total_elapsed_ms,
            "success": error_str is None,
            "error": error_str,
        }

    def list_available_companies(self) -> list[str]:
        """List companies available in the current data source."""
        return self.data_source.list_companies()


# =============================================================================
# CLI ENTRY POINT
# =============================================================================

def main():
    """Demo the meeting briefing agent."""
    import sys

    print("Meeting Briefing Agent - LangGraph Implementation")
    print("=" * 60)
    print(f"Tracing enabled: {tracing_enabled()}")
    print("Data source: Harmonic API")
    print()

    agent = MeetingBriefingAgent()

    # Use command line arg or default to stripe.com as demo
    url = sys.argv[1] if len(sys.argv) > 1 else "stripe.com"
    print(f"Preparing briefing for URL: {url}")
    print("-" * 60)

    result = agent.prepare_briefing(url)

    if result["success"]:
        print(f"Company: {result['company_name']}")
        print()
        print(result["briefing_markdown"])
    else:
        print(f"Error: {result['error']}")

    print("\n" + "=" * 60)
    print("Run Metadata:")
    print(f"  URL: {result['url']}")
    print(f"  Company: {result['company_name']}")
    print(f"  Run ID: {result['run_id']}")
    print(f"  Retrieval Counts: {result['retrieval_counts']}")
    print(f"  Step Timings: {result['step_timings_ms']}")
    print(f"  Total Time: {result['total_elapsed_ms']}ms")


if __name__ == "__main__":
    main()

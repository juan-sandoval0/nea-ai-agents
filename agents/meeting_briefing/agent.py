"""
Meeting Briefing Agent with LangSmith Tracing
==============================================
Pipeline: InputHandler -> Router -> Retrievers -> Synthesizer -> OutputFormatter

All LLM and tool calls are traced via LangSmith when enabled.
"""

import os
import sys
import time
import hashlib
from typing import Optional, TYPE_CHECKING
from uuid import uuid4
from datetime import datetime

# Guarded imports for optional dependencies
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

# These are imported at runtime in __init__ to allow the module to be parsed
if TYPE_CHECKING:
    from langchain_openai import ChatOpenAI
    from langchain_core.messages import HumanMessage, SystemMessage
    from .ingestion import DocumentIngestionPipeline

from observability.langsmith import (
    tracing_enabled,
    TracingContext,
    trace_step,
)

# Default time window for news retrieval
DEFAULT_NEWS_DAYS = 30

# Mock companies for evaluation (keep in sync with __init__.py)
MOCK_COMPANIES = [
    "Nexus AI",
    "Quantum Ledger",
    "Helix Therapeutics",
    "Terraflow",
    "Codelayer",
]


def normalize_company_name(name: str) -> str:
    """Normalize company name for consistent matching."""
    return name.strip().title()


def generate_doc_id(content: str, metadata: dict) -> str:
    """Generate a stable document ID from content hash."""
    hash_input = f"{content[:200]}|{metadata.get('company_name', '')}|{metadata.get('document_type', '')}"
    return hashlib.md5(hash_input.encode()).hexdigest()[:12]


class MeetingBriefingAgent:
    """
    Meeting briefing agent with full LangSmith tracing.

    Pipeline stages:
    1. InputHandler - normalize company name, validate
    2. Router - deterministic routing to all 3 retrievers
    3. Retrievers - company_profile, news, signals
    4. Synthesizer - LLM synthesizes briefing
    5. OutputFormatter - format as markdown
    """

    def __init__(self, time_window_days: int = DEFAULT_NEWS_DAYS):
        """
        Initialize the agent.

        Args:
            time_window_days: Days to look back for news articles
        """
        # Import heavy dependencies at runtime
        from langchain_openai import ChatOpenAI
        from .ingestion import DocumentIngestionPipeline

        self.time_window_days = time_window_days
        self.pipeline = DocumentIngestionPipeline()

        # Ensure documents are ingested
        self.pipeline.ingest()

        # Initialize LLM for synthesis
        self.llm = ChatOpenAI(
            model="gpt-4o",
            temperature=0,
        )

    @trace_step("company_profile_retriever", run_type="tool")
    def _retrieve_company_profile(
        self,
        company_name: str,
        ctx: TracingContext
    ) -> tuple[str, list[str]]:
        """Retrieve company profile documents."""
        start = time.perf_counter()

        results = self.pipeline.query_by_company(
            company_name,
            document_types=["company_profile"],
            n_results=5
        )

        doc_ids = []
        content_parts = []

        for r in results:
            doc_id = r["metadata"].get("id") or generate_doc_id(
                r["content"], r["metadata"]
            )
            doc_ids.append(doc_id)
            content_parts.append(
                f"[Score: {r['similarity_score']}]\n{r['content']}"
            )

        elapsed_ms = int((time.perf_counter() - start) * 1000)
        ctx.record_step_timing("company_profile_retriever", elapsed_ms)
        ctx.record_retrieval("profile", len(results), doc_ids)

        if not content_parts:
            return f"No company profile found for {company_name}.", []

        return "\n\n---\n\n".join(content_parts), doc_ids

    @trace_step("news_retriever", run_type="tool")
    def _retrieve_news(
        self,
        company_name: str,
        ctx: TracingContext
    ) -> tuple[str, list[str]]:
        """Retrieve recent news articles."""
        start = time.perf_counter()

        results = self.pipeline.query_by_company(
            company_name,
            document_types=["news_article"],
            n_results=10
        )

        doc_ids = []
        content_parts = []

        for r in results:
            doc_id = r["metadata"].get("id") or generate_doc_id(
                r["content"], r["metadata"]
            )
            doc_ids.append(doc_id)
            date = r["metadata"].get("date", "Unknown date")
            content_parts.append(
                f"[{date}] [Score: {r['similarity_score']}]\n{r['content']}"
            )

        elapsed_ms = int((time.perf_counter() - start) * 1000)
        ctx.record_step_timing("news_retriever", elapsed_ms)
        ctx.record_retrieval("news", len(results), doc_ids)

        if not content_parts:
            return f"No recent news found for {company_name}.", []

        return "\n\n---\n\n".join(content_parts), doc_ids

    @trace_step("signals_retriever", run_type="tool")
    def _retrieve_signals(
        self,
        company_name: str,
        ctx: TracingContext
    ) -> tuple[str, list[str]]:
        """Retrieve key signal reports."""
        start = time.perf_counter()

        results = self.pipeline.query_by_company(
            company_name,
            document_types=["signal_report"],
            n_results=7
        )

        doc_ids = []
        content_parts = []

        for r in results:
            doc_id = r["metadata"].get("id") or generate_doc_id(
                r["content"], r["metadata"]
            )
            doc_ids.append(doc_id)
            signal_type = r["metadata"].get("signal_type", "Unknown")
            content_parts.append(
                f"[Signal: {signal_type}] [Score: {r['similarity_score']}]\n{r['content']}"
            )

        elapsed_ms = int((time.perf_counter() - start) * 1000)
        ctx.record_step_timing("signals_retriever", elapsed_ms)
        ctx.record_retrieval("signals", len(results), doc_ids)

        if not content_parts:
            return f"No key signals found for {company_name}.", []

        return "\n\n---\n\n".join(content_parts), doc_ids

    @trace_step("synthesizer", run_type="llm")
    def _synthesize_briefing(
        self,
        company_name: str,
        profile_content: str,
        news_content: str,
        signals_content: str,
        ctx: TracingContext
    ) -> str:
        """Use LLM to synthesize the briefing from retrieved content."""
        from langchain_core.messages import HumanMessage, SystemMessage

        start = time.perf_counter()

        system_prompt = """You are an AI assistant preparing meeting briefings for venture capital investors.

Your task is to synthesize a comprehensive, well-structured briefing from the provided company information.

Structure your briefing with these sections:
1. **Company Overview** - Key facts about the company
2. **Recent Developments** - Notable news and updates
3. **Key Signals & Indicators** - Strategic insights and trends
4. **Recommended Discussion Points** - Suggested topics for the meeting

Be thorough but concise. Highlight the most important information."""

        user_prompt = f"""Please synthesize a meeting briefing for {company_name} using the following information:

## Company Profile
{profile_content}

## Recent News
{news_content}

## Key Signals
{signals_content}

Create a well-organized briefing document."""

        messages = [
            SystemMessage(content=system_prompt),
            HumanMessage(content=user_prompt)
        ]

        response = self.llm.invoke(messages)

        elapsed_ms = int((time.perf_counter() - start) * 1000)
        ctx.record_step_timing("synthesizer", elapsed_ms)

        return response.content

    def _format_output(self, company_name: str, briefing: str, ctx: TracingContext) -> str:
        """Format the final output as markdown."""
        start = time.perf_counter()

        output = f"""# Meeting Briefing: {company_name}

*Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}*
*Run ID: {ctx.run_id}*

---

{briefing}

---

## Retrieval Statistics

| Source | Documents Retrieved |
|--------|---------------------|
| Company Profile | {ctx.retrieval_counts['profile_k']} |
| News Articles | {ctx.retrieval_counts['news_k']} |
| Signal Reports | {ctx.retrieval_counts['signals_k']} |

*Total retrieval time: {sum(v for k, v in ctx.step_timings.items() if 'retriever' in k)}ms*
"""

        elapsed_ms = int((time.perf_counter() - start) * 1000)
        ctx.record_step_timing("output_formatter", elapsed_ms)

        return output

    def prepare_briefing(self, company_name: str) -> dict:
        """
        Prepare a comprehensive meeting briefing for a company.

        This is the main entry point. The entire run is traced in LangSmith.

        Args:
            company_name: Name of the company

        Returns:
            Dict with briefing output and metadata
        """
        run_id = str(uuid4())
        normalized_name = normalize_company_name(company_name)

        # Create tracing context
        ctx = TracingContext(
            run_id=run_id,
            company_name=normalized_name,
            time_window_days=self.time_window_days
        )
        ctx.start()

        error_str = None
        output_markdown = None

        try:
            # Stage 1: Input handling (already done - normalization)

            # Stage 2: Router - deterministic, call all retrievers
            # Stage 3: Retrievers
            profile_content, profile_ids = self._retrieve_company_profile(
                normalized_name, ctx
            )
            news_content, news_ids = self._retrieve_news(normalized_name, ctx)
            signals_content, signals_ids = self._retrieve_signals(
                normalized_name, ctx
            )

            # Stage 4: Synthesizer
            briefing = self._synthesize_briefing(
                normalized_name,
                profile_content,
                news_content,
                signals_content,
                ctx
            )

            # Stage 5: Output formatter
            output_markdown = self._format_output(normalized_name, briefing, ctx)

        except Exception as e:
            error_str = str(e)
            output_markdown = f"# Error\n\nFailed to generate briefing for {normalized_name}: {error_str}"

        finally:
            ctx.end(output=output_markdown, error=error_str)

        return {
            "company_name": normalized_name,
            "run_id": run_id,
            "timestamp": datetime.now().isoformat(),
            "output_markdown": output_markdown,
            "retrieval_counts": ctx.retrieval_counts.copy(),
            "retrieval_doc_ids": ctx.retrieval_doc_ids.copy(),
            "step_timings_ms": ctx.step_timings.copy(),
            "total_elapsed_ms": ctx.total_elapsed_ms,
            "success": error_str is None,
            "error": error_str,
        }


def main():
    """Demo the meeting briefing agent."""
    print("Meeting Briefing Agent Demo")
    print("=" * 60)
    print(f"Tracing enabled: {tracing_enabled()}")
    print()

    agent = MeetingBriefingAgent()

    company = "Nexus AI"
    print(f"Preparing briefing for: {company}")
    print("-" * 60)

    result = agent.prepare_briefing(company)

    if result["success"]:
        print(result["output_markdown"])
    else:
        print(f"Error: {result['error']}")

    print("\n" + "=" * 60)
    print("Run Metadata:")
    print(f"  Run ID: {result['run_id']}")
    print(f"  Retrieval Counts: {result['retrieval_counts']}")
    print(f"  Total Time: {result['total_elapsed_ms']}ms")


if __name__ == "__main__":
    main()

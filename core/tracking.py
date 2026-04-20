"""
Engagement Tracking for NEA AI Agents
======================================

Tracks usage metrics, API calls, and user feedback.

Tables:
- usage_events: Who queried what company, when
- api_calls: Harmonic API, LLM calls, tokens, costs
- feedback: User ratings and comments on briefings

Usage:
    from core.tracking import Tracker

    tracker = Tracker()

    # Log usage
    tracker.log_usage(company_id="stripe.com", action="ingest", user="ana")

    # Log API call
    tracker.log_api_call(
        service="harmonic",
        endpoint="/companies/123",
        tokens_in=0,
        tokens_out=0,
        cost=0.001
    )

    # Log feedback
    tracker.log_feedback(
        company_id="stripe.com",
        rating=5,
        comment="Great briefing!"
    )

    # Get stats
    stats = tracker.get_stats()
"""

from __future__ import annotations

import csv
import os
import sqlite3
from dataclasses import dataclass, asdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, Union
import logging
import json

logger = logging.getLogger(__name__)

# Use same database as main data
DEFAULT_DB_PATH = Path(__file__).parent.parent / "data" / "nea_agents.db"


def _is_readonly_env() -> bool:
    """Detect read-only serverless environments (Vercel, AWS Lambda) where
    SQLite writes to the bundle path will fail."""
    return bool(os.getenv("VERCEL") or os.getenv("AWS_LAMBDA_FUNCTION_NAME"))


@dataclass
class UsageEvent:
    """A single usage event."""
    company_id: str
    action: str  # ingest, briefing, lookup
    user: Optional[str] = None
    session_id: Optional[str] = None
    timestamp: str = None
    metadata: dict = None

    def __post_init__(self):
        if self.timestamp is None:
            self.timestamp = datetime.utcnow().isoformat()
        if self.metadata is None:
            self.metadata = {}


@dataclass
class APICall:
    """A single API call record."""
    service: str  # harmonic, openai, etc.
    endpoint: str
    method: str = "GET"
    status_code: int = 200
    tokens_in: int = 0
    tokens_out: int = 0
    cost: float = 0.0
    latency_ms: int = 0
    timestamp: str = None
    metadata: dict = None

    def __post_init__(self):
        if self.timestamp is None:
            self.timestamp = datetime.utcnow().isoformat()
        if self.metadata is None:
            self.metadata = {}


class Tracker:
    """
    Engagement tracker for AI agents.

    Logs usage events, API calls, and user feedback to SQLite.
    """

    def __init__(self, db_path: Optional[str] = None):
        self.db_path = Path(db_path) if db_path else DEFAULT_DB_PATH
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        return conn

    def _init_schema(self):
        conn = self._get_connection()
        try:
            cursor = conn.cursor()

            # Usage events table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS usage_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    company_id TEXT NOT NULL,
                    action TEXT NOT NULL,
                    user TEXT,
                    session_id TEXT,
                    timestamp TEXT NOT NULL,
                    metadata TEXT DEFAULT '{}'
                )
            """)

            # API calls table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS api_calls (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    service TEXT NOT NULL,
                    endpoint TEXT NOT NULL,
                    method TEXT DEFAULT 'GET',
                    status_code INTEGER DEFAULT 200,
                    tokens_in INTEGER DEFAULT 0,
                    tokens_out INTEGER DEFAULT 0,
                    cost REAL DEFAULT 0.0,
                    latency_ms INTEGER DEFAULT 0,
                    timestamp TEXT NOT NULL,
                    metadata TEXT DEFAULT '{}'
                )
            """)


            # LLM calls table - detailed tracking for reproducibility
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS llm_calls (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    call_id TEXT UNIQUE NOT NULL,
                    timestamp TEXT NOT NULL,
                    -- Prompt tracking
                    prompt_id TEXT,
                    prompt_version TEXT,
                    prompt_hash TEXT,
                    system_prompt_hash TEXT,
                    user_prompt_hash TEXT,
                    -- Model tracking
                    model TEXT NOT NULL,
                    model_config_name TEXT,
                    temperature REAL DEFAULT 0.0,
                    max_tokens INTEGER,
                    -- Metrics
                    tokens_in INTEGER DEFAULT 0,
                    tokens_out INTEGER DEFAULT 0,
                    latency_ms INTEGER DEFAULT 0,
                    -- Context
                    company_id TEXT,
                    operation TEXT,
                    success INTEGER DEFAULT 1,
                    error_message TEXT,
                    -- Full metadata JSON
                    metadata TEXT DEFAULT '{}'
                )
            """)

            # Create indexes
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_usage_company ON usage_events(company_id)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_usage_timestamp ON usage_events(timestamp)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_api_service ON api_calls(service)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_api_timestamp ON api_calls(timestamp)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_llm_timestamp ON llm_calls(timestamp)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_llm_prompt ON llm_calls(prompt_id)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_llm_model ON llm_calls(model)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_llm_operation ON llm_calls(operation)")

            conn.commit()
            logger.debug("Tracking schema initialized")

        finally:
            conn.close()

    # =========================================================================
    # USAGE TRACKING
    # =========================================================================

    def log_usage(
        self,
        company_id: str,
        action: str,
        user: Optional[str] = None,
        session_id: Optional[str] = None,
        metadata: Optional[dict] = None,
    ) -> int:
        """Log a usage event. Returns the event ID."""
        event = UsageEvent(
            company_id=company_id,
            action=action,
            user=user,
            session_id=session_id,
            metadata=metadata or {},
        )

        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO usage_events (company_id, action, user, session_id, timestamp, metadata)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (
                event.company_id,
                event.action,
                event.user,
                event.session_id,
                event.timestamp,
                json.dumps(event.metadata),
            ))
            conn.commit()
            return cursor.lastrowid
        finally:
            conn.close()

    def get_usage_history(
        self,
        company_id: Optional[str] = None,
        action: Optional[str] = None,
        days: int = 30,
        limit: int = 100,
    ) -> list[dict]:
        """Get usage history with optional filters."""
        conn = self._get_connection()
        try:
            cursor = conn.cursor()

            query = "SELECT * FROM usage_events WHERE 1=1"
            params = []

            if company_id:
                query += " AND company_id = ?"
                params.append(company_id)
            if action:
                query += " AND action = ?"
                params.append(action)

            cutoff = (datetime.utcnow() - timedelta(days=days)).isoformat()
            query += " AND timestamp >= ?"
            params.append(cutoff)

            query += " ORDER BY timestamp DESC LIMIT ?"
            params.append(limit)

            cursor.execute(query, params)
            return [dict(row) for row in cursor.fetchall()]
        finally:
            conn.close()

    # =========================================================================
    # API CALL TRACKING
    # =========================================================================

    def log_api_call(
        self,
        service: str,
        endpoint: str,
        method: str = "GET",
        status_code: int = 200,
        tokens_in: int = 0,
        tokens_out: int = 0,
        cost: float = 0.0,
        latency_ms: int = 0,
        metadata: Optional[dict] = None,
    ) -> int:
        """Log an API call. Returns the call ID."""
        call = APICall(
            service=service,
            endpoint=endpoint,
            method=method,
            status_code=status_code,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            cost=cost,
            latency_ms=latency_ms,
            metadata=metadata or {},
        )

        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO api_calls
                (service, endpoint, method, status_code, tokens_in, tokens_out, cost, latency_ms, timestamp, metadata)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                call.service,
                call.endpoint,
                call.method,
                call.status_code,
                call.tokens_in,
                call.tokens_out,
                call.cost,
                call.latency_ms,
                call.timestamp,
                json.dumps(call.metadata),
            ))
            conn.commit()
            return cursor.lastrowid
        finally:
            conn.close()

    # =========================================================================
    # LLM CALL TRACKING (for reproducibility)
    # =========================================================================

    def log_llm_call(
        self,
        call_id: str,
        model: str,
        operation: str,
        tokens_in: int = 0,
        tokens_out: int = 0,
        latency_ms: int = 0,
        prompt_id: Optional[str] = None,
        prompt_version: Optional[str] = None,
        prompt_hash: Optional[str] = None,
        system_prompt_hash: Optional[str] = None,
        user_prompt_hash: Optional[str] = None,
        model_config_name: Optional[str] = None,
        temperature: float = 0.0,
        max_tokens: Optional[int] = None,
        company_id: Optional[str] = None,
        success: bool = True,
        error_message: Optional[str] = None,
        metadata: Optional[dict] = None,
    ) -> str:
        """
        Log an LLM call with full metadata for reproducibility.

        This captures everything needed to understand and reproduce
        the generation: prompt version, model config, and context.

        Args:
            call_id: Unique identifier for this call
            model: Model used (e.g., "gpt-4o-mini")
            operation: Operation type (briefing, summarization, etc.)
            tokens_in: Input tokens
            tokens_out: Output tokens
            latency_ms: Call latency in milliseconds
            prompt_id: Registered prompt identifier
            prompt_version: Prompt version string
            prompt_hash: Hash of prompt content
            system_prompt_hash: Hash of system prompt
            user_prompt_hash: Hash of user prompt
            model_config_name: Name of model config used
            temperature: Temperature setting
            max_tokens: Max tokens setting
            company_id: Company being processed
            success: Whether the call succeeded
            error_message: Error message if failed
            metadata: Additional metadata

        Returns:
            The call_id for reference
        """
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO llm_calls (
                    call_id, timestamp, prompt_id, prompt_version, prompt_hash,
                    system_prompt_hash, user_prompt_hash, model, model_config_name,
                    temperature, max_tokens, tokens_in, tokens_out, latency_ms,
                    company_id, operation, success, error_message, metadata
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                call_id,
                datetime.utcnow().isoformat(),
                prompt_id,
                prompt_version,
                prompt_hash,
                system_prompt_hash,
                user_prompt_hash,
                model,
                model_config_name,
                temperature,
                max_tokens,
                tokens_in,
                tokens_out,
                latency_ms,
                company_id,
                operation,
                1 if success else 0,
                error_message,
                json.dumps(metadata or {}),
            ))
            conn.commit()
            logger.debug(
                f"Logged LLM call: {operation} with {model} "
                f"(prompt: {prompt_id}@{prompt_version})"
            )
            return call_id
        finally:
            conn.close()

    def log_llm_call_from_metadata(self, metadata: "LLMCallMetadata") -> str:
        """
        Log an LLM call from an LLMCallMetadata object.

        Args:
            metadata: LLMCallMetadata object with all call details

        Returns:
            The call_id for reference
        """
        # Import here to avoid circular import
        from core.prompt_registry import LLMCallMetadata

        return self.log_llm_call(
            call_id=metadata.call_id,
            model=metadata.model,
            operation=metadata.operation,
            tokens_in=metadata.tokens_in,
            tokens_out=metadata.tokens_out,
            latency_ms=metadata.latency_ms,
            prompt_id=metadata.prompt_id,
            prompt_version=metadata.prompt_version,
            prompt_hash=metadata.prompt_hash,
            system_prompt_hash=metadata.system_prompt_hash,
            user_prompt_hash=metadata.user_prompt_hash,
            model_config_name=metadata.model_config_name,
            temperature=metadata.temperature,
            max_tokens=metadata.max_tokens,
            company_id=metadata.company_id,
        )

    def get_llm_call(self, call_id: str) -> Optional[dict]:
        """Get a specific LLM call by ID."""
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM llm_calls WHERE call_id = ?", (call_id,))
            row = cursor.fetchone()
            return dict(row) if row else None
        finally:
            conn.close()

    def get_llm_calls_by_prompt(
        self,
        prompt_id: str,
        prompt_version: Optional[str] = None,
        days: int = 30,
    ) -> list[dict]:
        """
        Get all LLM calls that used a specific prompt.

        Useful for analyzing prompt performance or finding regressions.
        """
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            cutoff = (datetime.utcnow() - timedelta(days=days)).isoformat()

            query = """
                SELECT * FROM llm_calls
                WHERE prompt_id = ? AND timestamp >= ?
            """
            params = [prompt_id, cutoff]

            if prompt_version:
                query += " AND prompt_version = ?"
                params.append(prompt_version)

            query += " ORDER BY timestamp DESC"
            cursor.execute(query, params)
            return [dict(row) for row in cursor.fetchall()]
        finally:
            conn.close()

    def get_llm_stats(self, days: int = 30) -> dict:
        """Get aggregated LLM call statistics."""
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            cutoff = (datetime.utcnow() - timedelta(days=days)).isoformat()

            # Stats by model
            cursor.execute("""
                SELECT
                    model,
                    COUNT(*) as total_calls,
                    SUM(tokens_in) as total_tokens_in,
                    SUM(tokens_out) as total_tokens_out,
                    AVG(latency_ms) as avg_latency_ms,
                    SUM(CASE WHEN success = 0 THEN 1 ELSE 0 END) as failures
                FROM llm_calls
                WHERE timestamp >= ?
                GROUP BY model
            """, (cutoff,))

            by_model = {}
            for row in cursor.fetchall():
                by_model[row["model"]] = {
                    "total_calls": row["total_calls"],
                    "total_tokens_in": row["total_tokens_in"] or 0,
                    "total_tokens_out": row["total_tokens_out"] or 0,
                    "avg_latency_ms": round(row["avg_latency_ms"] or 0, 1),
                    "failure_rate": round(
                        (row["failures"] or 0) / max(row["total_calls"], 1) * 100, 2
                    ),
                }

            # Stats by prompt
            cursor.execute("""
                SELECT
                    prompt_id,
                    prompt_version,
                    COUNT(*) as total_calls,
                    AVG(latency_ms) as avg_latency_ms
                FROM llm_calls
                WHERE timestamp >= ? AND prompt_id IS NOT NULL
                GROUP BY prompt_id, prompt_version
            """, (cutoff,))

            by_prompt = {}
            for row in cursor.fetchall():
                key = f"{row['prompt_id']}@{row['prompt_version']}"
                by_prompt[key] = {
                    "total_calls": row["total_calls"],
                    "avg_latency_ms": round(row["avg_latency_ms"] or 0, 1),
                }

            # Stats by operation
            cursor.execute("""
                SELECT
                    operation,
                    COUNT(*) as total_calls,
                    AVG(latency_ms) as avg_latency_ms
                FROM llm_calls
                WHERE timestamp >= ?
                GROUP BY operation
            """, (cutoff,))

            by_operation = {}
            for row in cursor.fetchall():
                by_operation[row["operation"]] = {
                    "total_calls": row["total_calls"],
                    "avg_latency_ms": round(row["avg_latency_ms"] or 0, 1),
                }

            return {
                "period_days": days,
                "by_model": by_model,
                "by_prompt": by_prompt,
                "by_operation": by_operation,
            }
        finally:
            conn.close()

    def get_api_stats(self, days: int = 30) -> dict:
        """Get aggregated API stats."""
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            cutoff = (datetime.utcnow() - timedelta(days=days)).isoformat()

            cursor.execute("""
                SELECT
                    service,
                    COUNT(*) as total_calls,
                    SUM(tokens_in) as total_tokens_in,
                    SUM(tokens_out) as total_tokens_out,
                    SUM(cost) as total_cost,
                    AVG(latency_ms) as avg_latency_ms
                FROM api_calls
                WHERE timestamp >= ?
                GROUP BY service
            """, (cutoff,))

            stats = {}
            for row in cursor.fetchall():
                stats[row["service"]] = {
                    "total_calls": row["total_calls"],
                    "total_tokens_in": row["total_tokens_in"] or 0,
                    "total_tokens_out": row["total_tokens_out"] or 0,
                    "total_cost": round(row["total_cost"] or 0, 4),
                    "avg_latency_ms": round(row["avg_latency_ms"] or 0, 1),
                }
            return stats
        finally:
            conn.close()


    # =========================================================================
    # AGGREGATE STATS
    # =========================================================================

    def get_stats(self, days: int = 30) -> dict:
        """Get comprehensive engagement stats."""
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            cutoff = (datetime.utcnow() - timedelta(days=days)).isoformat()

            # Usage stats
            cursor.execute("""
                SELECT
                    COUNT(*) as total_events,
                    COUNT(DISTINCT company_id) as unique_companies,
                    COUNT(DISTINCT user) as unique_users
                FROM usage_events
                WHERE timestamp >= ?
            """, (cutoff,))
            usage_row = cursor.fetchone()

            # Action breakdown
            cursor.execute("""
                SELECT action, COUNT(*) as count
                FROM usage_events
                WHERE timestamp >= ?
                GROUP BY action
            """, (cutoff,))
            actions = {row["action"]: row["count"] for row in cursor.fetchall()}

            # Top companies
            cursor.execute("""
                SELECT company_id, COUNT(*) as count
                FROM usage_events
                WHERE timestamp >= ?
                GROUP BY company_id
                ORDER BY count DESC
                LIMIT 10
            """, (cutoff,))
            top_companies = [
                {"company": row["company_id"], "queries": row["count"]}
                for row in cursor.fetchall()
            ]

            return {
                "period_days": days,
                "usage": {
                    "total_events": usage_row["total_events"] or 0,
                    "unique_companies": usage_row["unique_companies"] or 0,
                    "unique_users": usage_row["unique_users"] or 0,
                    "by_action": actions,
                },
                "top_companies": top_companies,
                "api": self.get_api_stats(days),
            }
        finally:
            conn.close()


class NullTracker:
    """No-op tracker for read-only serverless environments. Logging lives in
    LangSmith + structured logs on Vercel; SQLite tracking is legacy local
    observability that can't run on a read-only filesystem."""

    def log_usage(self, *args, **kwargs) -> int:
        return 0

    def log_api_call(self, *args, **kwargs) -> int:
        return 0

    def log_llm_call(self, *args, **kwargs) -> str:
        return kwargs.get("call_id", "")

    def log_llm_call_from_metadata(self, metadata) -> str:
        return getattr(metadata, "call_id", "")

    def log_feedback(self, *args, **kwargs) -> int:
        return 0

    def get_usage_history(self, *args, **kwargs) -> list[dict]:
        return []

    def get_llm_call(self, *args, **kwargs):
        return None

    def get_llm_calls_by_prompt(self, *args, **kwargs) -> list[dict]:
        return []

    def get_llm_stats(self, *args, **kwargs) -> dict:
        return {"period_days": 0, "by_model": {}, "by_prompt": {}, "by_operation": {}}

    def get_api_stats(self, *args, **kwargs) -> dict:
        return {}

    def get_stats(self, *args, **kwargs) -> dict:
        return {
            "period_days": 0,
            "usage": {"total_events": 0, "unique_companies": 0, "unique_users": 0, "by_action": {}},
            "top_companies": [],
            "api": {},
        }


# Singleton tracker instance
_tracker: Optional[Union[Tracker, NullTracker]] = None


def get_tracker() -> Union[Tracker, NullTracker]:
    """Get or create global tracker instance.

    On Vercel / AWS Lambda the filesystem is read-only, so SQLite writes fail.
    Return a NullTracker in those environments — LangSmith + structured logs
    are the production observability path there.
    """
    global _tracker
    if _tracker is None:
        if _is_readonly_env():
            _tracker = NullTracker()
        else:
            _tracker = Tracker()
    return _tracker


# =============================================================================
# COST TRACKING
# =============================================================================

# Cost per unit for each service (approximate)
# Services used: Tavily (website intelligence), Harmonic (company data),
# OpenAI (LLM), NewsAPI (news research)
SERVICE_COSTS = {
    "tavily": {
        "unit": "credit",
        "cost_per_unit": 0.01,  # $0.01 per credit
        "credits_per_crawl": 2,  # ~2 credits per company crawl
    },
    "openai": {
        "unit": "token",
        "cost_per_1k_input": 0.0005,   # gpt-4o-mini input
        "cost_per_1k_output": 0.0015,  # gpt-4o-mini output
    },
    "harmonic": {
        "unit": "request",
        "cost_per_request": 0.0,  # Included in subscription
    },
    "news_api": {
        "unit": "search",
        "cost_per_search": 0.01,  # Estimated per news search
    },
}


def calculate_api_cost(
    service: str,
    tokens_in: int = 0,
    tokens_out: int = 0,
    credits_used: int = 0,
    requests: int = 1,
) -> float:
    """
    Calculate cost for an API call based on service pricing.

    Args:
        service: Service name (tavily, openai, etc.)
        tokens_in: Input tokens (for LLM calls)
        tokens_out: Output tokens (for LLM calls)
        credits_used: Credits used (for Tavily)
        requests: Number of requests

    Returns:
        Estimated cost in USD
    """
    service_lower = service.lower()
    pricing = SERVICE_COSTS.get(service_lower, {})

    if service_lower == "openai":
        input_cost = (tokens_in / 1000) * pricing.get("cost_per_1k_input", 0)
        output_cost = (tokens_out / 1000) * pricing.get("cost_per_1k_output", 0)
        return input_cost + output_cost

    elif service_lower == "tavily":
        if credits_used > 0:
            return credits_used * pricing.get("cost_per_unit", 0.01)
        return pricing.get("credits_per_crawl", 2) * pricing.get("cost_per_unit", 0.01)

    elif service_lower == "news_api":
        return requests * pricing.get("cost_per_search", 0.01)

    elif service_lower == "harmonic":
        return requests * pricing.get("cost_per_request", 0.0)

    return 0.0


def get_cost_summary(
    days: int = 30,
    db_path: Optional[Path] = None,
) -> dict:
    """
    Get comprehensive cost summary.

    Args:
        days: Look back period

    Returns:
        Dict with cost breakdown and projections
    """
    tracker = get_tracker()
    api_stats = tracker.get_api_stats(days)

    total_cost = 0.0
    cost_by_service = {}

    for service, stats in api_stats.items():
        service_cost = stats.get("total_cost", 0) or 0
        total_cost += service_cost
        cost_by_service[service] = {
            "total_cost": round(service_cost, 4),
            "total_calls": stats.get("total_calls", 0),
            "avg_cost_per_call": round(service_cost / max(stats.get("total_calls", 1), 1), 4),
        }

    # Calculate daily average and projections
    daily_avg = total_cost / days if days > 0 else 0
    projected_monthly = daily_avg * 30

    # Get company count for per-company cost
    usage_stats = tracker.get_stats(days)
    unique_companies = usage_stats.get("usage", {}).get("unique_companies", 1) or 1
    cost_per_company = total_cost / unique_companies

    return {
        "period_days": days,
        "total_cost": round(total_cost, 2),
        "cost_by_service": cost_by_service,
        "daily_average": round(daily_avg, 2),
        "projected_monthly": round(projected_monthly, 2),
        "unique_companies_analyzed": unique_companies,
        "cost_per_company": round(cost_per_company, 4),
    }


def project_costs_at_scale(
    companies_per_month: int,
    include_news: bool = True,
) -> dict:
    """
    Project costs if deployed at NEA scale.

    Args:
        companies_per_month: Expected companies to analyze
        include_news: Include NewsAPI news research

    Returns:
        Dict with projected costs
    """
    # Base costs per company (Tavily + OpenAI)
    tavily_cost = SERVICE_COSTS["tavily"]["credits_per_crawl"] * SERVICE_COSTS["tavily"]["cost_per_unit"]
    openai_cost = 0.02  # Estimated per briefing (input + output)

    base_cost_per_company = tavily_cost + openai_cost

    news_api_cost = 0.0
    if include_news:
        news_api_cost = SERVICE_COSTS["news_api"]["cost_per_search"]
        base_cost_per_company += news_api_cost

    monthly_cost = companies_per_month * base_cost_per_company
    annual_cost = monthly_cost * 12

    return {
        "companies_per_month": companies_per_month,
        "cost_per_company": round(base_cost_per_company, 4),
        "monthly_cost": round(monthly_cost, 2),
        "annual_cost": round(annual_cost, 2),
        "breakdown": {
            "tavily_crawl": tavily_cost,
            "news_api_search": news_api_cost,
            "openai_briefing": openai_cost,
        },
        "notes": "Estimates based on current pricing. Actual costs may vary.",
    }


def get_workflow_timing(
    company_id: Optional[str] = None,
    days: int = 30,
) -> dict:
    """
    Get workflow timing metrics.

    Returns average time for different operations.
    """
    tracker = get_tracker()
    api_stats = tracker.get_api_stats(days)

    # Calculate total latency by service
    total_latency_by_service = {}
    for service, stats in api_stats.items():
        avg_latency = stats.get("avg_latency_ms", 0)
        calls = stats.get("total_calls", 0)
        total_latency_by_service[service] = {
            "avg_latency_ms": round(avg_latency, 1),
            "total_calls": calls,
        }

    # Estimate total time per company (sum of all service latencies)
    # This is approximate - actual pipeline may have parallel calls
    estimated_per_company_ms = sum(
        s.get("avg_latency_ms", 0) for s in total_latency_by_service.values()
    )

    return {
        "period_days": days,
        "by_service": total_latency_by_service,
        "estimated_total_per_company_ms": round(estimated_per_company_ms, 1),
        "estimated_total_per_company_seconds": round(estimated_per_company_ms / 1000, 2),
    }


# =============================================================================
# COST PERSISTENCE (JSON/CSV)
# =============================================================================

@dataclass
class CostRecord:
    """A single cost record for persistence."""
    timestamp: str
    company_id: str
    service: str
    operation: str
    cost: float
    tokens_in: int = 0
    tokens_out: int = 0
    latency_ms: int = 0
    metadata: dict = None

    def __post_init__(self):
        if self.metadata is None:
            self.metadata = {}

    def to_dict(self) -> dict:
        return asdict(self)


def save_cost_record(
    company_id: str,
    service: str,
    operation: str,
    cost: float,
    tokens_in: int = 0,
    tokens_out: int = 0,
    latency_ms: int = 0,
    metadata: Optional[dict] = None,
    output_dir: Optional[Path] = None,
) -> CostRecord:
    """
    Save a single cost record to both JSON and CSV files.

    Args:
        company_id: Company identifier
        service: Service name (tavily, openai, etc.)
        operation: Operation type (crawl, search, briefing, etc.)
        cost: Cost in USD
        tokens_in: Input tokens (for LLM)
        tokens_out: Output tokens (for LLM)
        latency_ms: Request latency in ms
        metadata: Additional metadata
        output_dir: Directory for output files (defaults to data/)

    Returns:
        The created CostRecord
    """
    if output_dir is None:
        output_dir = Path(__file__).parent.parent / "data"
    output_dir.mkdir(parents=True, exist_ok=True)

    record = CostRecord(
        timestamp=datetime.utcnow().isoformat(),
        company_id=company_id,
        service=service,
        operation=operation,
        cost=cost,
        tokens_in=tokens_in,
        tokens_out=tokens_out,
        latency_ms=latency_ms,
        metadata=metadata or {},
    )

    # Append to JSON log (newline-delimited JSON)
    json_path = output_dir / "cost_log.jsonl"
    with open(json_path, "a") as f:
        f.write(json.dumps(record.to_dict()) + "\n")

    # Append to CSV
    csv_path = output_dir / "cost_log.csv"
    file_exists = csv_path.exists()
    with open(csv_path, "a", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=[
            "timestamp", "company_id", "service", "operation",
            "cost", "tokens_in", "tokens_out", "latency_ms"
        ])
        if not file_exists:
            writer.writeheader()
        writer.writerow({
            "timestamp": record.timestamp,
            "company_id": record.company_id,
            "service": record.service,
            "operation": record.operation,
            "cost": record.cost,
            "tokens_in": record.tokens_in,
            "tokens_out": record.tokens_out,
            "latency_ms": record.latency_ms,
        })

    logger.debug(f"Saved cost record: {service}/{operation} ${cost:.4f}")
    return record


def load_cost_records(
    output_dir: Optional[Path] = None,
    company_id: Optional[str] = None,
    service: Optional[str] = None,
    days: int = 30,
) -> list[CostRecord]:
    """
    Load cost records from JSON log.

    Args:
        output_dir: Directory with cost files
        company_id: Filter by company
        service: Filter by service
        days: Look back period

    Returns:
        List of CostRecord objects
    """
    if output_dir is None:
        output_dir = Path(__file__).parent.parent / "data"

    json_path = output_dir / "cost_log.jsonl"
    if not json_path.exists():
        return []

    cutoff = (datetime.utcnow() - timedelta(days=days)).isoformat()
    records = []

    with open(json_path, "r") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            data = json.loads(line)

            # Apply filters
            if data.get("timestamp", "") < cutoff:
                continue
            if company_id and data.get("company_id") != company_id:
                continue
            if service and data.get("service") != service:
                continue

            records.append(CostRecord(**data))

    return records


def export_cost_summary(
    output_path: Union[str, Path],
    days: int = 30,
    format: str = "json",
) -> Path:
    """
    Export cost summary to JSON or CSV file.

    Args:
        output_path: Output file path
        days: Look back period
        format: "json" or "csv"

    Returns:
        Path to created file
    """
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    summary = get_cost_summary(days=days)

    if format == "json":
        with open(output_path, "w") as f:
            json.dump(summary, f, indent=2)
    else:  # CSV
        with open(output_path, "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["metric", "value"])
            writer.writerow(["period_days", summary["period_days"]])
            writer.writerow(["total_cost", summary["total_cost"]])
            writer.writerow(["daily_average", summary["daily_average"]])
            writer.writerow(["projected_monthly", summary["projected_monthly"]])
            writer.writerow(["cost_per_company", summary["cost_per_company"]])
            writer.writerow(["unique_companies", summary["unique_companies_analyzed"]])
            writer.writerow([])
            writer.writerow(["service", "total_cost", "total_calls", "avg_cost_per_call"])
            for service, data in summary["cost_by_service"].items():
                writer.writerow([
                    service,
                    data["total_cost"],
                    data["total_calls"],
                    data["avg_cost_per_call"],
                ])

    logger.info(f"Exported cost summary to {output_path}")
    return output_path


def export_evaluation_costs(
    company_ids: list[str],
    output_path: Union[str, Path],
    format: str = "json",
    output_dir: Optional[Path] = None,
) -> dict:
    """
    Export per-company costs for an evaluation run.

    Args:
        company_ids: Companies evaluated
        output_path: Output file path
        format: "json" or "csv"
        output_dir: Directory with cost logs

    Returns:
        Dict with per-run and aggregate costs
    """
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    records = load_cost_records(output_dir=output_dir, days=1)

    # Filter to companies in this evaluation
    eval_records = [r for r in records if r.company_id in company_ids]

    # Aggregate by company
    per_company = {}
    for r in eval_records:
        if r.company_id not in per_company:
            per_company[r.company_id] = {
                "company_id": r.company_id,
                "total_cost": 0.0,
                "by_service": {},
                "operations": [],
            }
        per_company[r.company_id]["total_cost"] += r.cost

        if r.service not in per_company[r.company_id]["by_service"]:
            per_company[r.company_id]["by_service"][r.service] = 0.0
        per_company[r.company_id]["by_service"][r.service] += r.cost

        per_company[r.company_id]["operations"].append({
            "service": r.service,
            "operation": r.operation,
            "cost": r.cost,
            "timestamp": r.timestamp,
        })

    # Calculate aggregate
    total_cost = sum(c["total_cost"] for c in per_company.values())
    avg_cost = total_cost / len(company_ids) if company_ids else 0

    result = {
        "timestamp": datetime.utcnow().isoformat(),
        "companies_evaluated": company_ids,
        "total_companies": len(company_ids),
        "aggregate_cost": round(total_cost, 4),
        "avg_cost_per_company": round(avg_cost, 4),
        "per_company": list(per_company.values()),
    }

    if format == "json":
        with open(output_path, "w") as f:
            json.dump(result, f, indent=2)
    else:  # CSV
        with open(output_path, "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["company_id", "total_cost", "tavily", "openai", "harmonic", "news_api"])
            for company_data in per_company.values():
                by_svc = company_data["by_service"]
                writer.writerow([
                    company_data["company_id"],
                    round(company_data["total_cost"], 4),
                    round(by_svc.get("tavily", 0), 4),
                    round(by_svc.get("openai", 0), 4),
                    round(by_svc.get("harmonic", 0), 4),
                    round(by_svc.get("news_api", 0), 4),
                ])
            writer.writerow([])
            writer.writerow(["Total", round(total_cost, 4)])
            writer.writerow(["Average", round(avg_cost, 4)])

    logger.info(f"Exported evaluation costs to {output_path}")
    return result

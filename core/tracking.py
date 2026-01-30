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

import sqlite3
from dataclasses import dataclass, asdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional
import logging
import json

logger = logging.getLogger(__name__)

# Use same database as main data
DEFAULT_DB_PATH = Path(__file__).parent.parent / "data" / "nea_agents.db"


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


            # Create indexes
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_usage_company ON usage_events(company_id)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_usage_timestamp ON usage_events(timestamp)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_api_service ON api_calls(service)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_api_timestamp ON api_calls(timestamp)")

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


# Singleton tracker instance
_tracker: Optional[Tracker] = None


def get_tracker() -> Tracker:
    """Get or create global tracker instance."""
    global _tracker
    if _tracker is None:
        _tracker = Tracker()
    return _tracker

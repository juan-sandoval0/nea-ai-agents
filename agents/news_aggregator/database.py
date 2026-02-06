"""Database layer for news aggregator using SQLite."""

import sqlite3
import uuid
import json
from datetime import datetime
from dataclasses import dataclass
from typing import Optional, List
from pathlib import Path

DB_PATH = Path(__file__).parent / "news_aggregator.db"


@dataclass
class WatchedCompany:
    id: str
    company_id: str  # domain
    company_name: str
    category: str  # "portfolio" or "competitor"
    harmonic_id: Optional[str] = None
    is_active: bool = True
    added_at: str = None

    def __post_init__(self):
        if self.added_at is None:
            self.added_at = datetime.utcnow().isoformat()


@dataclass
class EmployeeSnapshot:
    id: str
    company_id: str
    snapshot_date: str
    employees_json: str
    created_at: str = None

    def __post_init__(self):
        if self.created_at is None:
            self.created_at = datetime.utcnow().isoformat()

    @property
    def employees(self) -> List[dict]:
        return json.loads(self.employees_json) if self.employees_json else []


@dataclass
class CompanySignal:
    id: str
    company_id: str
    signal_type: str  # funding/team_change/product_launch/acquisition/partnership/news
    headline: str
    description: str
    source_url: Optional[str] = None
    source_name: Optional[str] = None
    published_date: Optional[str] = None
    relevance_score: int = 0
    score_breakdown: Optional[str] = None  # JSON
    raw_data: Optional[str] = None  # JSON
    detected_at: str = None

    def __post_init__(self):
        if self.detected_at is None:
            self.detected_at = datetime.utcnow().isoformat()

    @property
    def raw_data_dict(self) -> dict:
        return json.loads(self.raw_data) if self.raw_data else {}


def get_connection() -> sqlite3.Connection:
    """Get database connection with row factory."""
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    """Initialize database tables."""
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS watched_companies (
            id TEXT PRIMARY KEY,
            company_id TEXT NOT NULL,
            company_name TEXT NOT NULL,
            category TEXT NOT NULL,
            harmonic_id TEXT,
            is_active INTEGER DEFAULT 1,
            added_at TEXT NOT NULL
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS employee_snapshots (
            id TEXT PRIMARY KEY,
            company_id TEXT NOT NULL,
            snapshot_date TEXT NOT NULL,
            employees_json TEXT,
            created_at TEXT NOT NULL,
            FOREIGN KEY (company_id) REFERENCES watched_companies(id)
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS company_signals (
            id TEXT PRIMARY KEY,
            company_id TEXT NOT NULL,
            signal_type TEXT NOT NULL,
            headline TEXT NOT NULL,
            description TEXT,
            source_url TEXT,
            source_name TEXT,
            published_date TEXT,
            relevance_score INTEGER DEFAULT 0,
            score_breakdown TEXT,
            raw_data TEXT,
            detected_at TEXT NOT NULL,
            FOREIGN KEY (company_id) REFERENCES watched_companies(id)
        )
    """)

    cursor.execute("CREATE INDEX IF NOT EXISTS idx_signals_company ON company_signals(company_id)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_signals_type ON company_signals(signal_type)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_signals_score ON company_signals(relevance_score)")

    conn.commit()
    conn.close()


def add_company(company_id: str, company_name: str, category: str, harmonic_id: str = None) -> WatchedCompany:
    """Add a company to the watchlist."""
    company = WatchedCompany(
        id=str(uuid.uuid4()),
        company_id=company_id,
        company_name=company_name,
        category=category,
        harmonic_id=harmonic_id
    )
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO watched_companies (id, company_id, company_name, category, harmonic_id, is_active, added_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (company.id, company.company_id, company.company_name, company.category,
          company.harmonic_id, company.is_active, company.added_at))
    conn.commit()
    conn.close()
    return company


def get_companies(active_only: bool = True) -> List[WatchedCompany]:
    """Get all watched companies."""
    conn = get_connection()
    cursor = conn.cursor()
    if active_only:
        cursor.execute("SELECT * FROM watched_companies WHERE is_active = 1")
    else:
        cursor.execute("SELECT * FROM watched_companies")
    rows = cursor.fetchall()
    conn.close()
    return [WatchedCompany(**dict(row)) for row in rows]


def get_company_by_domain(domain: str) -> Optional[WatchedCompany]:
    """Get company by domain."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM watched_companies WHERE company_id = ?", (domain,))
    row = cursor.fetchone()
    conn.close()
    return WatchedCompany(**dict(row)) if row else None


def update_company_harmonic_id(company_id: str, harmonic_id: str):
    """Update harmonic ID for a company."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("UPDATE watched_companies SET harmonic_id = ? WHERE id = ?", (harmonic_id, company_id))
    conn.commit()
    conn.close()


def save_signal(signal: CompanySignal) -> CompanySignal:
    """Save a signal to the database."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO company_signals
        (id, company_id, signal_type, headline, description, source_url, source_name,
         published_date, relevance_score, score_breakdown, raw_data, detected_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (signal.id, signal.company_id, signal.signal_type, signal.headline, signal.description,
          signal.source_url, signal.source_name, signal.published_date, signal.relevance_score,
          signal.score_breakdown, signal.raw_data, signal.detected_at))
    conn.commit()
    conn.close()
    return signal


def get_signals(
    company_id: str = None,
    signal_type: str = None,
    min_score: int = None,
    limit: int = 100
) -> List[CompanySignal]:
    """Get signals with optional filters."""
    conn = get_connection()
    cursor = conn.cursor()

    query = "SELECT * FROM company_signals WHERE 1=1"
    params = []

    if company_id:
        query += " AND company_id = ?"
        params.append(company_id)
    if signal_type:
        query += " AND signal_type = ?"
        params.append(signal_type)
    if min_score is not None:
        query += " AND relevance_score >= ?"
        params.append(min_score)

    query += " ORDER BY relevance_score DESC, detected_at DESC LIMIT ?"
    params.append(limit)

    cursor.execute(query, params)
    rows = cursor.fetchall()
    conn.close()
    return [CompanySignal(**dict(row)) for row in rows]


def signal_exists(company_id: str, signal_type: str, headline: str) -> bool:
    """Check if a similar signal already exists (deduplication)."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT COUNT(*) FROM company_signals
        WHERE company_id = ? AND signal_type = ? AND headline = ?
    """, (company_id, signal_type, headline))
    count = cursor.fetchone()[0]
    conn.close()
    return count > 0


def save_employee_snapshot(company_id: str, employees: List[dict]) -> EmployeeSnapshot:
    """Save an employee snapshot."""
    snapshot = EmployeeSnapshot(
        id=str(uuid.uuid4()),
        company_id=company_id,
        snapshot_date=datetime.utcnow().strftime("%Y-%m-%d"),
        employees_json=json.dumps(employees)
    )
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO employee_snapshots (id, company_id, snapshot_date, employees_json, created_at)
        VALUES (?, ?, ?, ?, ?)
    """, (snapshot.id, snapshot.company_id, snapshot.snapshot_date, snapshot.employees_json, snapshot.created_at))
    conn.commit()
    conn.close()
    return snapshot


def get_latest_employee_snapshot(company_id: str) -> Optional[EmployeeSnapshot]:
    """Get the most recent employee snapshot for a company."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT * FROM employee_snapshots
        WHERE company_id = ?
        ORDER BY snapshot_date DESC LIMIT 1
    """, (company_id,))
    row = cursor.fetchone()
    conn.close()
    return EmployeeSnapshot(**dict(row)) if row else None


# Initialize on import
init_db()

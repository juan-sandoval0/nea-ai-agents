"""Database layer for news aggregator using SQLite."""

import sqlite3
import uuid
import json
from datetime import datetime, timedelta
from dataclasses import dataclass, field
from typing import Optional, List
from pathlib import Path

DB_PATH = Path(__file__).parent / "news_aggregator.db"


@dataclass
class Investor:
    """An investor who tracks companies."""
    id: str
    name: str
    email: Optional[str] = None
    slack_id: Optional[str] = None
    is_active: bool = True
    created_at: str = None

    def __post_init__(self):
        if self.created_at is None:
            self.created_at = datetime.utcnow().isoformat()


@dataclass
class WatchedCompany:
    """A company being tracked for signals."""
    id: str
    company_id: str  # domain
    company_name: str
    category: str  # "portfolio" or "competitor"
    harmonic_id: Optional[str] = None
    parent_company_id: Optional[str] = None  # For competitors: links to portfolio company
    competitors_refreshed_at: Optional[str] = None  # When competitors were last fetched
    is_active: bool = True
    added_at: str = None

    def __post_init__(self):
        if self.added_at is None:
            self.added_at = datetime.utcnow().isoformat()

    def competitors_need_refresh(self, days: int = 30) -> bool:
        """Check if competitors need to be refreshed (older than N days)."""
        if self.category != "portfolio":
            return False
        if not self.competitors_refreshed_at:
            return True
        refreshed = datetime.fromisoformat(self.competitors_refreshed_at)
        return datetime.utcnow() - refreshed > timedelta(days=days)


@dataclass
class InvestorCompany:
    """Links investors to companies they track."""
    id: str
    investor_id: str
    company_id: str  # References WatchedCompany.id
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

    # Investors table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS investors (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            email TEXT,
            slack_id TEXT,
            is_active INTEGER DEFAULT 1,
            created_at TEXT NOT NULL
        )
    """)

    # Watched companies table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS watched_companies (
            id TEXT PRIMARY KEY,
            company_id TEXT NOT NULL UNIQUE,
            company_name TEXT NOT NULL,
            category TEXT NOT NULL,
            harmonic_id TEXT,
            parent_company_id TEXT,
            competitors_refreshed_at TEXT,
            is_active INTEGER DEFAULT 1,
            added_at TEXT NOT NULL,
            FOREIGN KEY (parent_company_id) REFERENCES watched_companies(id)
        )
    """)

    # Investor-Company junction table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS investor_companies (
            id TEXT PRIMARY KEY,
            investor_id TEXT NOT NULL,
            company_id TEXT NOT NULL,
            added_at TEXT NOT NULL,
            FOREIGN KEY (investor_id) REFERENCES investors(id),
            FOREIGN KEY (company_id) REFERENCES watched_companies(id),
            UNIQUE(investor_id, company_id)
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
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_investor_companies ON investor_companies(investor_id)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_company_parent ON watched_companies(parent_company_id)")

    conn.commit()
    conn.close()


# =============================================================================
# INVESTOR OPERATIONS
# =============================================================================

def add_investor(name: str, email: str = None, slack_id: str = None) -> Investor:
    """Add a new investor."""
    investor = Investor(
        id=str(uuid.uuid4()),
        name=name,
        email=email,
        slack_id=slack_id
    )
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO investors (id, name, email, slack_id, is_active, created_at)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (investor.id, investor.name, investor.email, investor.slack_id,
          investor.is_active, investor.created_at))
    conn.commit()
    conn.close()
    return investor


def get_investor(investor_id: str = None, name: str = None) -> Optional[Investor]:
    """Get investor by ID or name."""
    conn = get_connection()
    cursor = conn.cursor()
    if investor_id:
        cursor.execute("SELECT * FROM investors WHERE id = ?", (investor_id,))
    elif name:
        cursor.execute("SELECT * FROM investors WHERE name = ?", (name,))
    else:
        return None
    row = cursor.fetchone()
    conn.close()
    return Investor(**dict(row)) if row else None


def get_investors(active_only: bool = True) -> List[Investor]:
    """Get all investors."""
    conn = get_connection()
    cursor = conn.cursor()
    if active_only:
        cursor.execute("SELECT * FROM investors WHERE is_active = 1")
    else:
        cursor.execute("SELECT * FROM investors")
    rows = cursor.fetchall()
    conn.close()
    return [Investor(**dict(row)) for row in rows]


def get_or_create_default_investor() -> Investor:
    """Get or create a default investor for single-user mode."""
    investor = get_investor(name="default")
    if not investor:
        investor = add_investor(name="default", email=None)
    return investor


# =============================================================================
# COMPANY OPERATIONS
# =============================================================================

def get_company_by_domain(domain: str) -> Optional[WatchedCompany]:
    """Get company by domain (company_id)."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM watched_companies WHERE company_id = ?", (domain,))
    row = cursor.fetchone()
    conn.close()
    return WatchedCompany(**dict(row)) if row else None


def get_company_by_id(company_id: str) -> Optional[WatchedCompany]:
    """Get company by internal ID."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM watched_companies WHERE id = ?", (company_id,))
    row = cursor.fetchone()
    conn.close()
    return WatchedCompany(**dict(row)) if row else None


def add_company(
    company_id: str,
    company_name: str,
    category: str,
    harmonic_id: str = None,
    parent_company_id: str = None
) -> WatchedCompany:
    """Add a company to the watchlist (or return existing)."""
    # Check if company already exists
    existing = get_company_by_domain(company_id)
    if existing:
        return existing

    company = WatchedCompany(
        id=str(uuid.uuid4()),
        company_id=company_id,
        company_name=company_name,
        category=category,
        harmonic_id=harmonic_id,
        parent_company_id=parent_company_id
    )
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO watched_companies
        (id, company_id, company_name, category, harmonic_id, parent_company_id,
         competitors_refreshed_at, is_active, added_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (company.id, company.company_id, company.company_name, company.category,
          company.harmonic_id, company.parent_company_id, company.competitors_refreshed_at,
          company.is_active, company.added_at))
    conn.commit()
    conn.close()
    return company


def link_investor_to_company(investor_id: str, company_id: str) -> InvestorCompany:
    """Link an investor to a company."""
    conn = get_connection()
    cursor = conn.cursor()

    # Check if link already exists
    cursor.execute("""
        SELECT * FROM investor_companies
        WHERE investor_id = ? AND company_id = ?
    """, (investor_id, company_id))
    existing = cursor.fetchone()
    if existing:
        conn.close()
        return InvestorCompany(**dict(existing))

    link = InvestorCompany(
        id=str(uuid.uuid4()),
        investor_id=investor_id,
        company_id=company_id
    )
    cursor.execute("""
        INSERT INTO investor_companies (id, investor_id, company_id, added_at)
        VALUES (?, ?, ?, ?)
    """, (link.id, link.investor_id, link.company_id, link.added_at))
    conn.commit()
    conn.close()
    return link


def unlink_investor_from_company(investor_id: str, company_id: str) -> bool:
    """Remove link between investor and company."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        DELETE FROM investor_companies
        WHERE investor_id = ? AND company_id = ?
    """, (investor_id, company_id))
    deleted = cursor.rowcount > 0
    conn.commit()
    conn.close()
    return deleted


def get_companies(
    active_only: bool = True,
    investor_id: str = None,
    category: str = None,
    parent_company_id: str = None
) -> List[WatchedCompany]:
    """Get watched companies with optional filters."""
    conn = get_connection()
    cursor = conn.cursor()

    if investor_id:
        # Get companies for a specific investor
        query = """
            SELECT wc.* FROM watched_companies wc
            JOIN investor_companies ic ON wc.id = ic.company_id
            WHERE ic.investor_id = ?
        """
        params = [investor_id]
        if active_only:
            query += " AND wc.is_active = 1"
        if category:
            query += " AND wc.category = ?"
            params.append(category)
        if parent_company_id:
            query += " AND wc.parent_company_id = ?"
            params.append(parent_company_id)
        cursor.execute(query, params)
    else:
        # Get all companies
        query = "SELECT * FROM watched_companies WHERE 1=1"
        params = []
        if active_only:
            query += " AND is_active = 1"
        if category:
            query += " AND category = ?"
            params.append(category)
        if parent_company_id:
            query += " AND parent_company_id = ?"
            params.append(parent_company_id)
        cursor.execute(query, params)

    rows = cursor.fetchall()
    conn.close()
    return [WatchedCompany(**dict(row)) for row in rows]


def get_portfolio_companies(investor_id: str = None) -> List[WatchedCompany]:
    """Get only portfolio companies."""
    return get_companies(investor_id=investor_id, category="portfolio")


def get_competitors_for_company(parent_company_id: str) -> List[WatchedCompany]:
    """Get competitors linked to a portfolio company."""
    return get_companies(parent_company_id=parent_company_id, category="competitor")


def update_company(company_id: str, **updates) -> bool:
    """Update company fields."""
    if not updates:
        return False

    conn = get_connection()
    cursor = conn.cursor()

    set_clauses = ", ".join(f"{k} = ?" for k in updates.keys())
    values = list(updates.values()) + [company_id]

    cursor.execute(f"""
        UPDATE watched_companies SET {set_clauses} WHERE id = ?
    """, values)

    updated = cursor.rowcount > 0
    conn.commit()
    conn.close()
    return updated


def update_company_harmonic_id(company_id: str, harmonic_id: str):
    """Update harmonic ID for a company."""
    update_company(company_id, harmonic_id=harmonic_id)


def update_competitors_refreshed(company_id: str):
    """Mark competitors as refreshed now."""
    update_company(company_id, competitors_refreshed_at=datetime.utcnow().isoformat())


def deactivate_company(company_id: str) -> bool:
    """Soft-delete a company by marking inactive."""
    return update_company(company_id, is_active=0)


def remove_company(company_id: str, hard_delete: bool = False) -> bool:
    """Remove a company (soft or hard delete)."""
    if not hard_delete:
        return deactivate_company(company_id)

    conn = get_connection()
    cursor = conn.cursor()

    # Remove investor links
    cursor.execute("DELETE FROM investor_companies WHERE company_id = ?", (company_id,))
    # Remove signals
    cursor.execute("DELETE FROM company_signals WHERE company_id = ?", (company_id,))
    # Remove snapshots
    cursor.execute("DELETE FROM employee_snapshots WHERE company_id = ?", (company_id,))
    # Remove company
    cursor.execute("DELETE FROM watched_companies WHERE id = ?", (company_id,))

    deleted = cursor.rowcount > 0
    conn.commit()
    conn.close()
    return deleted


# =============================================================================
# SIGNAL OPERATIONS
# =============================================================================

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
    limit: int = 100,
    investor_id: str = None
) -> List[CompanySignal]:
    """Get signals with optional filters."""
    conn = get_connection()
    cursor = conn.cursor()

    if investor_id:
        # Get signals for companies tracked by this investor
        query = """
            SELECT cs.* FROM company_signals cs
            JOIN investor_companies ic ON cs.company_id = ic.company_id
            WHERE ic.investor_id = ?
        """
        params = [investor_id]
    else:
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


# =============================================================================
# EMPLOYEE SNAPSHOT OPERATIONS
# =============================================================================

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

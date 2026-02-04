"""
Shared Database Schema and Models
=================================

SQLite-based storage for structured company data used by multiple agents.

Tables:
- company_core: Company snapshot data
- founders: Founders and key team members
- news: News articles
- key_signals: Strategic signals and indicators

Usage:
    from core.database import Database, CompanyCore, Founder

    db = Database()
    db.upsert_company(company_data)
    bundle = db.get_company_bundle(company_id)
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import Optional
import logging

logger = logging.getLogger(__name__)

# =============================================================================
# CONFIGURATION
# =============================================================================

# Default database path in the data directory
DEFAULT_DB_PATH = Path(__file__).parent.parent / "data" / "nea_agents.db"


# =============================================================================
# DATA MODELS
# =============================================================================

@dataclass
class CompanyCore:
    """Company core data matching company_core table schema."""
    company_id: str  # URL/domain used for lookup
    company_name: str
    founding_date: Optional[str] = None
    hq: Optional[str] = None
    employee_count: Optional[int] = None
    total_funding: Optional[float] = None
    products: Optional[str] = None
    customers: Optional[str] = None
    arr_apr: Optional[str] = None
    last_round_date: Optional[str] = None
    last_round_funding: Optional[float] = None
    web_traffic_trend: Optional[str] = None  # e.g., "+5.2% (30d)"
    website_update: Optional[str] = None  # NULL; pending Tavily
    hiring_firing: Optional[str] = None  # e.g., "-9.7% (90d)"
    observed_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    source_map: dict = field(default_factory=dict)  # field -> source mapping

    def to_dict(self) -> dict:
        """Convert to dictionary for DB storage."""
        d = asdict(self)
        d['source_map'] = json.dumps(d['source_map'])
        return d

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> CompanyCore:
        """Create from database row."""
        d = dict(row)
        d['source_map'] = json.loads(d.get('source_map', '{}'))
        return cls(**d)


@dataclass
class Founder:
    """Founder/key team member matching founders table schema."""
    company_id: str
    name: str
    role_title: Optional[str] = None
    linkedin_url: Optional[str] = None
    background: Optional[str] = None  # NULL; pending Swarm
    observed_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    source: str = "harmonic"  # or "pending_swarm" for background

    def to_dict(self) -> dict:
        """Convert to dictionary for DB storage."""
        return asdict(self)

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> Founder:
        """Create from database row."""
        d = dict(row)
        d.pop('id', None)  # Remove autoincrement id
        return cls(**d)


@dataclass
class NewsArticle:
    """News article matching news table schema."""
    company_id: str
    article_headline: str
    outlet: Optional[str] = None
    url: Optional[str] = None
    published_date: Optional[str] = None
    excerpts: Optional[str] = None  # Article content/excerpts for LLM context
    observed_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    source: str = "news_api"  # or "pending_news_api"

    def to_dict(self) -> dict:
        """Convert to dictionary for DB storage."""
        return asdict(self)

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> NewsArticle:
        """Create from database row."""
        d = dict(row)
        d.pop('id', None)  # Remove autoincrement id
        return cls(**d)


@dataclass
class KeySignal:
    """Key signal matching key_signals table schema."""
    company_id: str
    signal_type: str  # hiring, traffic, funding, website_update
    description: str
    observed_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    source: str = "harmonic"  # or "pending_tavily"

    def to_dict(self) -> dict:
        """Convert to dictionary for DB storage."""
        return asdict(self)

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> KeySignal:
        """Create from database row."""
        d = dict(row)
        d.pop('id', None)  # Remove autoincrement id
        return cls(**d)


@dataclass
class CompanyBundle:
    """Complete company data bundle for briefing generation."""
    company_core: Optional[CompanyCore] = None
    founders: list[Founder] = field(default_factory=list)
    news: list[NewsArticle] = field(default_factory=list)
    key_signals: list[KeySignal] = field(default_factory=list)

    def to_dict(self) -> dict:
        """Convert entire bundle to dictionary."""
        return {
            'company_core': asdict(self.company_core) if self.company_core else None,
            'founders': [asdict(f) for f in self.founders],
            'news': [asdict(n) for n in self.news],
            'key_signals': [asdict(s) for s in self.key_signals],
        }


# =============================================================================
# DATABASE CLASS
# =============================================================================

class Database:
    """
    SQLite database for structured company data.

    Tables:
    - company_core: Company snapshot data
    - founders: Founders and key team members
    - news: News articles (pending implementation)
    - key_signals: Strategic signals and indicators
    """

    def __init__(self, db_path: Optional[str] = None):
        """
        Initialize database connection.

        Args:
            db_path: Path to SQLite database file. Uses default if not specified.
        """
        self.db_path = Path(db_path) if db_path else DEFAULT_DB_PATH
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    def _get_connection(self) -> sqlite3.Connection:
        """Get database connection with row factory."""
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        return conn

    def _init_schema(self):
        """Initialize database schema."""
        conn = self._get_connection()
        try:
            cursor = conn.cursor()

            # Company core table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS company_core (
                    company_id TEXT PRIMARY KEY,
                    company_name TEXT NOT NULL,
                    founding_date TEXT,
                    hq TEXT,
                    employee_count INTEGER,
                    total_funding REAL,
                    products TEXT,
                    customers TEXT,
                    arr_apr TEXT,
                    last_round_date TEXT,
                    last_round_funding REAL,
                    web_traffic_trend TEXT,
                    website_update TEXT,
                    hiring_firing TEXT,
                    observed_at TEXT NOT NULL,
                    source_map TEXT DEFAULT '{}'
                )
            """)

            # Founders table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS founders (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    company_id TEXT NOT NULL,
                    name TEXT NOT NULL,
                    role_title TEXT,
                    linkedin_url TEXT,
                    background TEXT,
                    observed_at TEXT NOT NULL,
                    source TEXT DEFAULT 'harmonic',
                    FOREIGN KEY (company_id) REFERENCES company_core(company_id),
                    UNIQUE(company_id, name)
                )
            """)

            # News table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS news (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    company_id TEXT NOT NULL,
                    article_headline TEXT NOT NULL,
                    outlet TEXT,
                    url TEXT,
                    published_date TEXT,
                    excerpts TEXT,
                    observed_at TEXT NOT NULL,
                    source TEXT DEFAULT 'news_api',
                    FOREIGN KEY (company_id) REFERENCES company_core(company_id),
                    UNIQUE(company_id, url)
                )
            """)

            # Add excerpts column if it doesn't exist (migration for existing DBs)
            try:
                cursor.execute("ALTER TABLE news ADD COLUMN excerpts TEXT")
            except sqlite3.OperationalError:
                pass  # Column already exists

            # Key signals table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS key_signals (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    company_id TEXT NOT NULL,
                    signal_type TEXT NOT NULL,
                    description TEXT NOT NULL,
                    observed_at TEXT NOT NULL,
                    source TEXT DEFAULT 'harmonic',
                    FOREIGN KEY (company_id) REFERENCES company_core(company_id)
                )
            """)

            # Create indexes
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_founders_company ON founders(company_id)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_news_company ON news(company_id)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_signals_company ON key_signals(company_id)")
            cursor.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_news_company_url ON news(company_id, url)")

            conn.commit()
            logger.info(f"Database schema initialized at {self.db_path}")

        finally:
            conn.close()

    # =========================================================================
    # COMPANY CORE OPERATIONS
    # =========================================================================

    def upsert_company(self, company: CompanyCore) -> None:
        """Insert or update company core data."""
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            data = company.to_dict()

            cursor.execute("""
                INSERT INTO company_core (
                    company_id, company_name, founding_date, hq, employee_count,
                    total_funding, products, customers, arr_apr, last_round_date,
                    last_round_funding, web_traffic_trend, website_update,
                    hiring_firing, observed_at, source_map
                ) VALUES (
                    :company_id, :company_name, :founding_date, :hq, :employee_count,
                    :total_funding, :products, :customers, :arr_apr, :last_round_date,
                    :last_round_funding, :web_traffic_trend, :website_update,
                    :hiring_firing, :observed_at, :source_map
                )
                ON CONFLICT(company_id) DO UPDATE SET
                    company_name = excluded.company_name,
                    founding_date = excluded.founding_date,
                    hq = excluded.hq,
                    employee_count = excluded.employee_count,
                    total_funding = excluded.total_funding,
                    products = excluded.products,
                    customers = excluded.customers,
                    arr_apr = excluded.arr_apr,
                    last_round_date = excluded.last_round_date,
                    last_round_funding = excluded.last_round_funding,
                    web_traffic_trend = excluded.web_traffic_trend,
                    website_update = excluded.website_update,
                    hiring_firing = excluded.hiring_firing,
                    observed_at = excluded.observed_at,
                    source_map = excluded.source_map
            """, data)

            conn.commit()
            logger.debug(f"Upserted company: {company.company_id}")

        finally:
            conn.close()

    def get_company(self, company_id: str) -> Optional[CompanyCore]:
        """Get company core data by ID."""
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT * FROM company_core WHERE company_id = ?",
                (company_id,)
            )
            row = cursor.fetchone()
            return CompanyCore.from_row(row) if row else None
        finally:
            conn.close()

    # =========================================================================
    # FOUNDERS OPERATIONS
    # =========================================================================

    def upsert_founders(self, founders: list[Founder]) -> None:
        """Insert or update founders for a company."""
        if not founders:
            return

        conn = self._get_connection()
        try:
            cursor = conn.cursor()

            for founder in founders:
                data = founder.to_dict()
                cursor.execute("""
                    INSERT INTO founders (
                        company_id, name, role_title, linkedin_url,
                        background, observed_at, source
                    ) VALUES (
                        :company_id, :name, :role_title, :linkedin_url,
                        :background, :observed_at, :source
                    )
                    ON CONFLICT(company_id, name) DO UPDATE SET
                        role_title = excluded.role_title,
                        linkedin_url = excluded.linkedin_url,
                        background = COALESCE(excluded.background, founders.background),
                        observed_at = excluded.observed_at,
                        source = excluded.source
                """, data)

            conn.commit()
            logger.debug(f"Upserted {len(founders)} founders")

        finally:
            conn.close()

    def get_founders(self, company_id: str) -> list[Founder]:
        """Get founders for a company."""
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT * FROM founders WHERE company_id = ?",
                (company_id,)
            )
            return [Founder.from_row(row) for row in cursor.fetchall()]
        finally:
            conn.close()

    def delete_founders(self, company_id: str) -> None:
        """Delete all founders for a company."""
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM founders WHERE company_id = ?", (company_id,))
            conn.commit()
            logger.debug(f"Deleted founders for {company_id}")
        finally:
            conn.close()

    # =========================================================================
    # NEWS OPERATIONS
    # =========================================================================

    def insert_news(self, articles: list[NewsArticle]) -> None:
        """Insert news articles for a company."""
        if not articles:
            return

        conn = self._get_connection()
        try:
            cursor = conn.cursor()

            for article in articles:
                data = article.to_dict()
                cursor.execute("""
                    INSERT OR IGNORE INTO news (
                        company_id, article_headline, outlet, url,
                        published_date, excerpts, observed_at, source
                    ) VALUES (
                        :company_id, :article_headline, :outlet, :url,
                        :published_date, :excerpts, :observed_at, :source
                    )
                """, data)

            conn.commit()
            logger.debug(f"Inserted {len(articles)} news articles")

        finally:
            conn.close()

    def get_news(self, company_id: str, limit: int = 10) -> list[NewsArticle]:
        """Get recent news for a company."""
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT * FROM news
                WHERE company_id = ?
                ORDER BY published_date DESC, observed_at DESC
                LIMIT ?
            """, (company_id, limit))
            return [NewsArticle.from_row(row) for row in cursor.fetchall()]
        finally:
            conn.close()

    # =========================================================================
    # KEY SIGNALS OPERATIONS
    # =========================================================================

    def upsert_signals(self, signals: list[KeySignal]) -> None:
        """Insert or update key signals for a company."""
        if not signals:
            return

        conn = self._get_connection()
        try:
            cursor = conn.cursor()

            # Group by company and delete existing signals for those types
            company_ids = set(s.company_id for s in signals)
            signal_types = set(s.signal_type for s in signals)

            for cid in company_ids:
                for stype in signal_types:
                    cursor.execute("""
                        DELETE FROM key_signals
                        WHERE company_id = ? AND signal_type = ?
                    """, (cid, stype))

            # Insert new signals
            for signal in signals:
                data = signal.to_dict()
                cursor.execute("""
                    INSERT INTO key_signals (
                        company_id, signal_type, description, observed_at, source
                    ) VALUES (
                        :company_id, :signal_type, :description, :observed_at, :source
                    )
                """, data)

            conn.commit()
            logger.debug(f"Upserted {len(signals)} signals")

        finally:
            conn.close()

    def get_signals(self, company_id: str) -> list[KeySignal]:
        """Get key signals for a company."""
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT * FROM key_signals WHERE company_id = ? ORDER BY observed_at DESC",
                (company_id,)
            )
            return [KeySignal.from_row(row) for row in cursor.fetchall()]
        finally:
            conn.close()

    # =========================================================================
    # BUNDLE OPERATIONS
    # =========================================================================

    def get_company_bundle(self, company_id: str) -> CompanyBundle:
        """Get complete company data bundle."""
        return CompanyBundle(
            company_core=self.get_company(company_id),
            founders=self.get_founders(company_id),
            news=self.get_news(company_id),
            key_signals=self.get_signals(company_id),
        )

    def clear_company_data(self, company_id: str) -> None:
        """Clear all data for a company."""
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM key_signals WHERE company_id = ?", (company_id,))
            cursor.execute("DELETE FROM news WHERE company_id = ?", (company_id,))
            cursor.execute("DELETE FROM founders WHERE company_id = ?", (company_id,))
            cursor.execute("DELETE FROM company_core WHERE company_id = ?", (company_id,))
            conn.commit()
            logger.info(f"Cleared all data for company: {company_id}")
        finally:
            conn.close()

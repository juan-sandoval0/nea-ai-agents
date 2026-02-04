"""
Briefing history database.

Stores generated briefings for the history feature.
"""

import json
import sqlite3
from dataclasses import dataclass, asdict
from datetime import datetime
from pathlib import Path
from typing import Optional
import logging

logger = logging.getLogger(__name__)

# Default database path (same directory as main database)
DEFAULT_HISTORY_DB_PATH = Path(__file__).parent.parent / "data" / "briefing_history.db"


@dataclass
class BriefingRecord:
    """A stored briefing record."""
    id: str
    company_id: str
    company_name: str
    created_at: datetime
    markdown: str
    success: bool
    error: Optional[str] = None
    data_sources: dict = None

    def to_dict(self) -> dict:
        """Convert to dictionary for DB storage."""
        d = asdict(self)
        d['created_at'] = self.created_at.isoformat()
        d['data_sources'] = json.dumps(self.data_sources or {})
        return d

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> "BriefingRecord":
        """Create from database row."""
        d = dict(row)
        d['created_at'] = datetime.fromisoformat(d['created_at'])
        d['data_sources'] = json.loads(d.get('data_sources', '{}'))
        d['success'] = bool(d['success'])
        return cls(**d)


class BriefingHistoryDB:
    """SQLite database for briefing history."""

    def __init__(self, db_path: Optional[str] = None):
        """Initialize database connection."""
        self.db_path = Path(db_path) if db_path else DEFAULT_HISTORY_DB_PATH
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

            cursor.execute("""
                CREATE TABLE IF NOT EXISTS briefing_history (
                    id TEXT PRIMARY KEY,
                    company_id TEXT NOT NULL,
                    company_name TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    markdown TEXT NOT NULL,
                    success INTEGER NOT NULL,
                    error TEXT,
                    data_sources TEXT DEFAULT '{}'
                )
            """)

            # Index for searching and sorting
            cursor.execute(
                "CREATE INDEX IF NOT EXISTS idx_history_company_id ON briefing_history(company_id)"
            )
            cursor.execute(
                "CREATE INDEX IF NOT EXISTS idx_history_created ON briefing_history(created_at DESC)"
            )
            cursor.execute(
                "CREATE INDEX IF NOT EXISTS idx_history_company_name ON briefing_history(company_name)"
            )

            conn.commit()
            logger.info(f"Briefing history database initialized at {self.db_path}")

        finally:
            conn.close()

    def save_briefing(self, record: BriefingRecord) -> None:
        """Save a briefing to history."""
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            data = record.to_dict()

            cursor.execute("""
                INSERT INTO briefing_history (
                    id, company_id, company_name, created_at,
                    markdown, success, error, data_sources
                ) VALUES (
                    :id, :company_id, :company_name, :created_at,
                    :markdown, :success, :error, :data_sources
                )
            """, data)

            conn.commit()
            logger.info(f"Saved briefing {record.id} for {record.company_name}")

        finally:
            conn.close()

    def get_briefing(self, briefing_id: str) -> Optional[BriefingRecord]:
        """Get a briefing by ID."""
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT * FROM briefing_history WHERE id = ?",
                (briefing_id,)
            )
            row = cursor.fetchone()
            return BriefingRecord.from_row(row) if row else None
        finally:
            conn.close()

    def list_briefings(
        self,
        search: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[BriefingRecord]:
        """List briefings with optional search."""
        conn = self._get_connection()
        try:
            cursor = conn.cursor()

            if search:
                # Search in company_name and company_id
                cursor.execute("""
                    SELECT * FROM briefing_history
                    WHERE company_name LIKE ? OR company_id LIKE ?
                    ORDER BY created_at DESC
                    LIMIT ? OFFSET ?
                """, (f"%{search}%", f"%{search}%", limit, offset))
            else:
                cursor.execute("""
                    SELECT * FROM briefing_history
                    ORDER BY created_at DESC
                    LIMIT ? OFFSET ?
                """, (limit, offset))

            return [BriefingRecord.from_row(row) for row in cursor.fetchall()]

        finally:
            conn.close()

    def count_briefings(self, search: Optional[str] = None) -> int:
        """Count briefings with optional search."""
        conn = self._get_connection()
        try:
            cursor = conn.cursor()

            if search:
                cursor.execute("""
                    SELECT COUNT(*) FROM briefing_history
                    WHERE company_name LIKE ? OR company_id LIKE ?
                """, (f"%{search}%", f"%{search}%"))
            else:
                cursor.execute("SELECT COUNT(*) FROM briefing_history")

            return cursor.fetchone()[0]

        finally:
            conn.close()

    def delete_briefing(self, briefing_id: str) -> bool:
        """Delete a briefing. Returns True if deleted."""
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute(
                "DELETE FROM briefing_history WHERE id = ?",
                (briefing_id,)
            )
            conn.commit()
            deleted = cursor.rowcount > 0
            if deleted:
                logger.info(f"Deleted briefing {briefing_id}")
            return deleted
        finally:
            conn.close()

    def clear_all(self) -> int:
        """Clear all briefing history. Returns count deleted."""
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM briefing_history")
            count = cursor.rowcount
            conn.commit()
            logger.info(f"Cleared {count} briefings from history")
            return count
        finally:
            conn.close()

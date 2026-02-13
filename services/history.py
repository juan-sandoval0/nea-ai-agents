"""
Briefing history database using Supabase.

Stores generated briefings for the history feature.
"""

from dataclasses import dataclass, asdict
from datetime import datetime
from typing import Optional
import logging

from core.clients.supabase_client import get_supabase

logger = logging.getLogger(__name__)


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
        return d

    @classmethod
    def from_row(cls, row: dict) -> "BriefingRecord":
        """Create from Supabase row."""
        created_at = row['created_at']
        if isinstance(created_at, str):
            # Handle ISO format with timezone
            created_at = datetime.fromisoformat(created_at.replace('Z', '+00:00'))
            created_at = created_at.replace(tzinfo=None)

        return cls(
            id=row['id'],
            company_id=row['company_id'],
            company_name=row['company_name'],
            created_at=created_at,
            markdown=row.get('markdown', ''),
            success=row.get('success', True),
            error=row.get('error'),
            data_sources=row.get('data_sources') or {},
        )


class BriefingHistoryDB:
    """Supabase database for briefing history."""

    def __init__(self, db_path: Optional[str] = None):
        """Initialize database connection.

        Args:
            db_path: Ignored - kept for API compatibility with SQLite version
        """
        # db_path is ignored, we use Supabase
        pass

    def save_briefing(self, record: BriefingRecord) -> None:
        """Save a briefing to history."""
        supabase = get_supabase()
        data = {
            "company_id": record.company_id,
            "company_name": record.company_name,
            "markdown": record.markdown,
            "success": record.success,
            "error": record.error,
            "data_sources": record.data_sources or {},
        }

        supabase.table("briefing_history").insert(data).execute()
        logger.info(f"Saved briefing for {record.company_name}")

    def get_briefing(self, briefing_id: str) -> Optional[BriefingRecord]:
        """Get a briefing by ID."""
        supabase = get_supabase()
        result = supabase.table("briefing_history").select("*").eq("id", briefing_id).execute()

        if not result.data:
            return None
        return BriefingRecord.from_row(result.data[0])

    def list_briefings(
        self,
        search: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[BriefingRecord]:
        """List briefings with optional search."""
        supabase = get_supabase()
        query = supabase.table("briefing_history").select("*")

        if search:
            # Search in company_name and company_id using ilike
            query = query.or_(f"company_name.ilike.%{search}%,company_id.ilike.%{search}%")

        query = query.order("created_at", desc=True).range(offset, offset + limit - 1)

        result = query.execute()
        return [BriefingRecord.from_row(row) for row in result.data]

    def count_briefings(self, search: Optional[str] = None) -> int:
        """Count briefings with optional search."""
        supabase = get_supabase()
        query = supabase.table("briefing_history").select("id", count="exact")

        if search:
            query = query.or_(f"company_name.ilike.%{search}%,company_id.ilike.%{search}%")

        result = query.execute()
        return result.count or 0

    def delete_briefing(self, briefing_id: str) -> bool:
        """Delete a briefing. Returns True if deleted."""
        supabase = get_supabase()
        result = supabase.table("briefing_history").delete().eq("id", briefing_id).execute()

        deleted = len(result.data) > 0
        if deleted:
            logger.info(f"Deleted briefing {briefing_id}")
        return deleted

    def clear_all(self) -> int:
        """Clear all briefing history. Returns count deleted."""
        supabase = get_supabase()

        # First count existing records
        count_result = supabase.table("briefing_history").select("id", count="exact").execute()
        count = count_result.count or 0

        if count > 0:
            # Delete all records by using a condition that's always true
            supabase.table("briefing_history").delete().neq("id", "").execute()
            logger.info(f"Cleared {count} briefings from history")

        return count

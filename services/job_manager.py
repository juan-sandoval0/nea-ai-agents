"""
Job Manager Service
===================

Manages job runs for tracking agent execution status.
Jobs are stored in Supabase so Lovable can poll status directly.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Optional
import logging

from core.clients.supabase_client import get_supabase

logger = logging.getLogger(__name__)


@dataclass
class JobRun:
    """A job run record."""
    id: str
    agent_type: str
    status: str  # pending, running, completed, failed
    created_at: datetime
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    error: Optional[str] = None
    result_summary: dict = None
    triggered_by: str = "api"

    @classmethod
    def from_row(cls, row: dict) -> "JobRun":
        """Create from Supabase row."""
        def parse_dt(val):
            if val is None:
                return None
            if isinstance(val, str):
                return datetime.fromisoformat(val.replace('Z', '+00:00')).replace(tzinfo=None)
            return val

        return cls(
            id=row['id'],
            agent_type=row['agent_type'],
            status=row['status'],
            created_at=parse_dt(row['created_at']),
            started_at=parse_dt(row.get('started_at')),
            completed_at=parse_dt(row.get('completed_at')),
            error=row.get('error'),
            result_summary=row.get('result_summary') or {},
            triggered_by=row.get('triggered_by', 'api'),
        )


class JobManager:
    """Manages job runs in Supabase."""

    def create_job(self, agent_type: str, triggered_by: str = "api") -> JobRun:
        """Create a new pending job."""
        supabase = get_supabase()
        data = {
            "agent_type": agent_type,
            "status": "pending",
            "triggered_by": triggered_by,
        }
        result = supabase.table("job_runs").insert(data).execute()
        row = result.data[0]
        logger.info(f"Created job {row['id']} for {agent_type}")
        return JobRun.from_row(row)

    def start_job(self, job_id: str) -> None:
        """Mark a job as running."""
        supabase = get_supabase()
        supabase.table("job_runs").update({
            "status": "running",
            "started_at": datetime.utcnow().isoformat(),
        }).eq("id", job_id).execute()
        logger.info(f"Started job {job_id}")

    def complete_job(self, job_id: str, result_summary: dict = None) -> None:
        """Mark a job as completed."""
        supabase = get_supabase()
        supabase.table("job_runs").update({
            "status": "completed",
            "completed_at": datetime.utcnow().isoformat(),
            "result_summary": result_summary or {},
        }).eq("id", job_id).execute()
        logger.info(f"Completed job {job_id}")

    def fail_job(self, job_id: str, error: str) -> None:
        """Mark a job as failed."""
        supabase = get_supabase()
        supabase.table("job_runs").update({
            "status": "failed",
            "completed_at": datetime.utcnow().isoformat(),
            "error": error,
        }).eq("id", job_id).execute()
        logger.error(f"Failed job {job_id}: {error}")

    def get_job(self, job_id: str) -> Optional[JobRun]:
        """Get a job by ID."""
        supabase = get_supabase()
        result = supabase.table("job_runs").select("*").eq("id", job_id).execute()
        if result.data:
            return JobRun.from_row(result.data[0])
        return None

    def get_latest_job(self, agent_type: str) -> Optional[JobRun]:
        """Get the most recent job for an agent type."""
        supabase = get_supabase()
        result = (
            supabase.table("job_runs")
            .select("*")
            .eq("agent_type", agent_type)
            .order("created_at", desc=True)
            .limit(1)
            .execute()
        )
        if result.data:
            return JobRun.from_row(result.data[0])
        return None

    def get_running_job(self, agent_type: str) -> Optional[JobRun]:
        """Get any currently running job for an agent type."""
        supabase = get_supabase()
        result = (
            supabase.table("job_runs")
            .select("*")
            .eq("agent_type", agent_type)
            .eq("status", "running")
            .order("created_at", desc=True)
            .limit(1)
            .execute()
        )
        if result.data:
            return JobRun.from_row(result.data[0])
        return None

    def list_jobs(self, agent_type: str = None, limit: int = 10) -> list[JobRun]:
        """List recent jobs."""
        supabase = get_supabase()
        query = supabase.table("job_runs").select("*")
        if agent_type:
            query = query.eq("agent_type", agent_type)
        result = query.order("created_at", desc=True).limit(limit).execute()
        return [JobRun.from_row(row) for row in result.data]


# Singleton instance
_job_manager = None


def get_job_manager() -> JobManager:
    """Get the job manager singleton."""
    global _job_manager
    if _job_manager is None:
        _job_manager = JobManager()
    return _job_manager

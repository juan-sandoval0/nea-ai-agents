"""
Structured Logging Setup
========================

JSON-formatted logging for Vercel log drains and observability.

Usage:
    from services.logging_setup import setup_logging, get_logger

    setup_logging(job_id="optional-job-id")
    logger = get_logger(__name__)
    logger.info("Processing started", extra={"company_id": "stripe.com"})
"""

import json
import logging
import os
import sys
import uuid
from datetime import datetime, timezone
from typing import Optional


class JSONFormatter(logging.Formatter):
    """Format logs as JSON for structured logging pipelines."""

    def __init__(self, job_id: Optional[str] = None, trace_id: Optional[str] = None):
        super().__init__()
        self.job_id = job_id
        self.trace_id = trace_id or str(uuid.uuid4())[:8]

    def format(self, record: logging.LogRecord) -> str:
        log_entry = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }

        # Add job_id if available
        if self.job_id:
            log_entry["job_id"] = self.job_id
        elif hasattr(record, "job_id"):
            log_entry["job_id"] = record.job_id

        # Add trace_id
        log_entry["trace_id"] = getattr(record, "trace_id", self.trace_id)

        # Add any extra fields from the log record
        if hasattr(record, "company_id"):
            log_entry["company_id"] = record.company_id
        if hasattr(record, "agent_name"):
            log_entry["agent_name"] = record.agent_name
        if hasattr(record, "duration_ms"):
            log_entry["duration_ms"] = record.duration_ms

        # Add exception info if present
        if record.exc_info:
            log_entry["exception"] = self.formatException(record.exc_info)

        return json.dumps(log_entry)


def setup_logging(
    level: int = logging.INFO,
    job_id: Optional[str] = None,
    use_json: bool = True,
) -> str:
    """
    Configure structured logging for the application.

    Args:
        level: Logging level (default: INFO)
        job_id: Optional job ID for tracing
        use_json: If True, output JSON; if False, use standard format

    Returns:
        trace_id: The trace ID for this session
    """
    trace_id = str(uuid.uuid4())[:8]

    # Get the root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(level)

    # Remove existing handlers
    for handler in root_logger.handlers[:]:
        root_logger.removeHandler(handler)

    # Create console handler
    handler = logging.StreamHandler(sys.stdout)
    handler.setLevel(level)

    if use_json:
        handler.setFormatter(JSONFormatter(job_id=job_id, trace_id=trace_id))
    else:
        handler.setFormatter(logging.Formatter(
            "%(asctime)s %(levelname)s %(name)s %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        ))

    root_logger.addHandler(handler)

    return trace_id


def get_logger(name: str) -> logging.Logger:
    """Get a logger instance."""
    return logging.getLogger(name)


def setup_langsmith(project: Optional[str] = None) -> bool:
    """
    Configure LangSmith tracing if API key is present.

    Args:
        project: Optional project name override

    Returns:
        True if LangSmith was configured, False otherwise
    """
    api_key = os.getenv("LANGSMITH_API_KEY")
    if not api_key:
        return False

    # Set environment variables for LangChain tracing
    os.environ["LANGCHAIN_TRACING_V2"] = "true"
    os.environ["LANGCHAIN_API_KEY"] = api_key

    project_name = project or os.getenv("LANGSMITH_PROJECT", "nea-ai-agents")
    os.environ["LANGCHAIN_PROJECT"] = project_name

    logger = get_logger(__name__)
    logger.info("LangSmith tracing enabled", extra={"project": project_name})

    return True

"""
Observability and Structured Logging
====================================

Provides comprehensive logging, tracing, and debugging capabilities for LLM applications.

Why this is crucial:
1. Plain text logs are hard to search and analyze
2. Without request IDs, you can't trace a single request through the system
3. Without prompt/response logging, you can't debug LLM quality issues
4. Without structured data, you can't build dashboards or alerts

Usage:
    from core.observability import (
        get_logger,
        get_request_context,
        set_request_context,
        log_llm_interaction,
        LogContext,
    )

    # Get a structured logger
    logger = get_logger(__name__)

    # Set request context at entry point
    with LogContext(company_id="stripe.com", user="ana"):
        logger.info("Starting briefing generation")

        # Log LLM interaction with full context
        log_llm_interaction(
            operation="briefing",
            model="gpt-4o-mini",
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            response=response_content,
            tokens_in=100,
            tokens_out=500,
        )
"""

from __future__ import annotations

import contextvars
import hashlib
import json
import logging
import re
import sys
import time
import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from functools import wraps
from pathlib import Path
from typing import Any, Callable, Optional, TypeVar, Union

# Context variables for request tracing
_request_id: contextvars.ContextVar[Optional[str]] = contextvars.ContextVar(
    "request_id", default=None
)
_trace_id: contextvars.ContextVar[Optional[str]] = contextvars.ContextVar(
    "trace_id", default=None
)
_span_id: contextvars.ContextVar[Optional[str]] = contextvars.ContextVar(
    "span_id", default=None
)
_context_data: contextvars.ContextVar[dict] = contextvars.ContextVar(
    "context_data", default={}
)


T = TypeVar("T")


# =============================================================================
# REQUEST CONTEXT MANAGEMENT
# =============================================================================

def generate_request_id() -> str:
    """Generate a unique request ID."""
    return str(uuid.uuid4())


def generate_trace_id() -> str:
    """Generate a unique trace ID (shorter, for log readability)."""
    return uuid.uuid4().hex[:16]


def generate_span_id() -> str:
    """Generate a unique span ID."""
    return uuid.uuid4().hex[:8]


def get_request_id() -> Optional[str]:
    """Get the current request ID."""
    return _request_id.get()


def get_trace_id() -> Optional[str]:
    """Get the current trace ID."""
    return _trace_id.get()


def get_span_id() -> Optional[str]:
    """Get the current span ID."""
    return _span_id.get()


def get_context_data() -> dict:
    """Get the current context data."""
    return _context_data.get().copy()


def set_request_context(
    request_id: Optional[str] = None,
    trace_id: Optional[str] = None,
    **extra_context,
) -> dict:
    """
    Set the request context for the current execution.

    Args:
        request_id: Unique request identifier (generated if not provided)
        trace_id: Trace ID for distributed tracing
        **extra_context: Additional context data (company_id, user, etc.)

    Returns:
        Dict with the set context values
    """
    req_id = request_id or generate_request_id()
    tr_id = trace_id or generate_trace_id()

    _request_id.set(req_id)
    _trace_id.set(tr_id)
    _span_id.set(generate_span_id())

    context = {"request_id": req_id, "trace_id": tr_id, **extra_context}
    _context_data.set(context)

    return context


def clear_request_context() -> None:
    """Clear the current request context."""
    _request_id.set(None)
    _trace_id.set(None)
    _span_id.set(None)
    _context_data.set({})


class LogContext:
    """
    Context manager for setting request context.

    Usage:
        with LogContext(company_id="stripe.com", user="ana"):
            # All logs within this block will include the context
            logger.info("Processing request")
    """

    def __init__(
        self,
        request_id: Optional[str] = None,
        trace_id: Optional[str] = None,
        **extra_context,
    ):
        self.request_id = request_id
        self.trace_id = trace_id
        self.extra_context = extra_context
        self._previous_context: dict = {}

    def __enter__(self) -> "LogContext":
        self._previous_context = get_context_data()
        set_request_context(
            request_id=self.request_id,
            trace_id=self.trace_id,
            **self.extra_context,
        )
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        if self._previous_context:
            _context_data.set(self._previous_context)
        else:
            clear_request_context()


# =============================================================================
# STRUCTURED LOGGING
# =============================================================================

class StructuredFormatter(logging.Formatter):
    """
    JSON formatter for structured logging.

    Outputs logs as JSON with consistent fields for easy parsing.
    """

    def __init__(
        self,
        include_timestamp: bool = True,
        include_context: bool = True,
        include_location: bool = True,
    ):
        super().__init__()
        self.include_timestamp = include_timestamp
        self.include_context = include_context
        self.include_location = include_location

    def format(self, record: logging.LogRecord) -> str:
        log_data = {
            "level": record.levelname,
            "message": record.getMessage(),
            "logger": record.name,
        }

        if self.include_timestamp:
            log_data["timestamp"] = datetime.now(timezone.utc).isoformat()

        if self.include_location:
            log_data["location"] = {
                "file": record.filename,
                "line": record.lineno,
                "function": record.funcName,
            }

        if self.include_context:
            # Add request context
            request_id = get_request_id()
            trace_id = get_trace_id()
            context = get_context_data()

            if request_id:
                log_data["request_id"] = request_id
            if trace_id:
                log_data["trace_id"] = trace_id
            if context:
                log_data["context"] = {
                    k: v for k, v in context.items()
                    if k not in ("request_id", "trace_id")
                }

        # Add exception info if present
        if record.exc_info:
            log_data["exception"] = self.formatException(record.exc_info)

        # Add extra fields from the record
        extra_keys = set(record.__dict__.keys()) - {
            "name", "msg", "args", "created", "filename", "funcName",
            "levelname", "levelno", "lineno", "module", "msecs",
            "pathname", "process", "processName", "relativeCreated",
            "stack_info", "exc_info", "exc_text", "thread", "threadName",
            "message", "asctime",
        }
        for key in extra_keys:
            value = getattr(record, key)
            if value is not None and not key.startswith("_"):
                log_data[key] = value

        return json.dumps(log_data, default=str)


class HumanReadableFormatter(logging.Formatter):
    """
    Human-readable formatter with context for development.

    Format: [LEVEL] [trace_id] logger: message {context}
    """

    COLORS = {
        "DEBUG": "\033[36m",     # Cyan
        "INFO": "\033[32m",      # Green
        "WARNING": "\033[33m",   # Yellow
        "ERROR": "\033[31m",     # Red
        "CRITICAL": "\033[35m",  # Magenta
        "RESET": "\033[0m",
    }

    def __init__(self, use_colors: bool = True):
        super().__init__()
        self.use_colors = use_colors and sys.stderr.isatty()

    def format(self, record: logging.LogRecord) -> str:
        # Color for level
        if self.use_colors:
            level_color = self.COLORS.get(record.levelname, "")
            reset = self.COLORS["RESET"]
        else:
            level_color = ""
            reset = ""

        # Trace ID prefix
        trace_id = get_trace_id()
        trace_prefix = f"[{trace_id[:8]}]" if trace_id else ""

        # Context summary
        context = get_context_data()
        context_str = ""
        if context:
            context_items = [
                f"{k}={v}" for k, v in context.items()
                if k not in ("request_id", "trace_id") and v
            ]
            if context_items:
                context_str = f" {{{', '.join(context_items[:3])}}}"

        # Build message
        timestamp = datetime.now().strftime("%H:%M:%S.%f")[:-3]
        message = record.getMessage()

        formatted = (
            f"{timestamp} {level_color}{record.levelname:8}{reset} "
            f"{trace_prefix} {record.name}: {message}{context_str}"
        )

        # Add exception if present
        if record.exc_info:
            formatted += "\n" + self.formatException(record.exc_info)

        return formatted


def configure_logging(
    level: str = "INFO",
    format: str = "human",  # "human" or "json"
    log_file: Optional[Path] = None,
) -> None:
    """
    Configure logging for the application.

    Args:
        level: Log level (DEBUG, INFO, WARNING, ERROR)
        format: Output format ("human" for development, "json" for production)
        log_file: Optional file path for logging
    """
    root_logger = logging.getLogger()
    root_logger.setLevel(getattr(logging, level.upper()))

    # Remove existing handlers
    root_logger.handlers.clear()

    # Choose formatter
    if format == "json":
        formatter = StructuredFormatter()
    else:
        formatter = HumanReadableFormatter()

    # Console handler
    console_handler = logging.StreamHandler(sys.stderr)
    console_handler.setFormatter(formatter)
    root_logger.addHandler(console_handler)

    # File handler (always JSON for parsing)
    if log_file:
        log_file.parent.mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(log_file)
        file_handler.setFormatter(StructuredFormatter())
        root_logger.addHandler(file_handler)


def get_logger(name: str) -> logging.Logger:
    """Get a logger with the given name."""
    return logging.getLogger(name)


# =============================================================================
# LLM INTERACTION LOGGING
# =============================================================================

# PII patterns to mask in logs
PII_PATTERNS = [
    (r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b", "[EMAIL]"),  # Email
    (r"\b\d{3}[-.]?\d{3}[-.]?\d{4}\b", "[PHONE]"),  # Phone
    (r"\b\d{3}-\d{2}-\d{4}\b", "[SSN]"),  # SSN
    (r"\b\d{16}\b", "[CARD]"),  # Credit card (simple)
]

_COMPILED_PII = [(re.compile(p), r) for p, r in PII_PATTERNS]


def mask_pii(text: str) -> str:
    """Mask personally identifiable information in text."""
    if not text:
        return text

    for pattern, replacement in _COMPILED_PII:
        text = pattern.sub(replacement, text)

    return text


def truncate_for_logging(
    text: str,
    max_length: int = 1000,
    suffix: str = "...[truncated]",
) -> str:
    """Truncate text for logging while preserving usefulness."""
    if not text or len(text) <= max_length:
        return text

    return text[:max_length - len(suffix)] + suffix


@dataclass
class LLMInteraction:
    """
    Complete record of an LLM interaction for debugging and auditing.

    This captures everything needed to reproduce and debug LLM behavior.
    """
    # Identification
    interaction_id: str = field(default_factory=generate_request_id)
    timestamp: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    # Request context
    request_id: Optional[str] = None
    trace_id: Optional[str] = None
    operation: str = ""
    company_id: Optional[str] = None

    # Model configuration
    model: str = ""
    temperature: float = 0.0
    max_tokens: Optional[int] = None
    model_config_name: Optional[str] = None

    # Prompts (stored with masking)
    system_prompt: Optional[str] = None
    system_prompt_hash: Optional[str] = None
    user_prompt: Optional[str] = None
    user_prompt_hash: Optional[str] = None

    # Response
    response: Optional[str] = None
    response_hash: Optional[str] = None

    # Metrics
    tokens_in: int = 0
    tokens_out: int = 0
    latency_ms: int = 0

    # Status
    success: bool = True
    error_type: Optional[str] = None
    error_message: Optional[str] = None

    # Validation
    validation_passed: bool = True
    validation_warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        """Convert to dictionary for storage/logging."""
        return asdict(self)

    def to_log_dict(self, include_prompts: bool = False) -> dict:
        """
        Convert to dictionary suitable for logging.

        Args:
            include_prompts: Whether to include full prompt content
        """
        data = {
            "interaction_id": self.interaction_id,
            "timestamp": self.timestamp,
            "request_id": self.request_id,
            "trace_id": self.trace_id,
            "operation": self.operation,
            "company_id": self.company_id,
            "model": self.model,
            "temperature": self.temperature,
            "tokens_in": self.tokens_in,
            "tokens_out": self.tokens_out,
            "latency_ms": self.latency_ms,
            "success": self.success,
        }

        if include_prompts:
            data["system_prompt"] = truncate_for_logging(
                mask_pii(self.system_prompt or ""), 500
            )
            data["user_prompt"] = truncate_for_logging(
                mask_pii(self.user_prompt or ""), 1000
            )
            data["response"] = truncate_for_logging(
                mask_pii(self.response or ""), 1000
            )
        else:
            data["system_prompt_hash"] = self.system_prompt_hash
            data["user_prompt_hash"] = self.user_prompt_hash
            data["response_hash"] = self.response_hash

        if not self.success:
            data["error_type"] = self.error_type
            data["error_message"] = self.error_message

        if self.validation_warnings:
            data["validation_warnings"] = self.validation_warnings

        return data


def compute_content_hash(content: Optional[str]) -> Optional[str]:
    """Compute a hash of content for comparison without storing full content."""
    if not content:
        return None
    return hashlib.sha256(content.encode()).hexdigest()[:16]


# Global storage for recent interactions (for debugging)
_recent_interactions: list[LLMInteraction] = []
_max_recent_interactions = 100


def log_llm_interaction(
    operation: str,
    model: str,
    system_prompt: Optional[str] = None,
    user_prompt: Optional[str] = None,
    response: Optional[str] = None,
    tokens_in: int = 0,
    tokens_out: int = 0,
    latency_ms: int = 0,
    success: bool = True,
    error_type: Optional[str] = None,
    error_message: Optional[str] = None,
    temperature: float = 0.0,
    max_tokens: Optional[int] = None,
    model_config_name: Optional[str] = None,
    company_id: Optional[str] = None,
    validation_passed: bool = True,
    validation_warnings: Optional[list[str]] = None,
    store_prompts: bool = True,
    log_prompts: bool = False,
) -> LLMInteraction:
    """
    Log an LLM interaction with full context.

    This is the main entry point for logging LLM calls. It:
    1. Creates a structured interaction record
    2. Stores in memory for debugging
    3. Logs to the logging system
    4. Optionally persists to database

    Args:
        operation: Type of operation (briefing, summarization, etc.)
        model: Model used
        system_prompt: Full system prompt
        user_prompt: Full user prompt
        response: LLM response
        tokens_in: Input tokens
        tokens_out: Output tokens
        latency_ms: Request latency in ms
        success: Whether the call succeeded
        error_type: Type of error if failed
        error_message: Error message if failed
        temperature: Temperature setting
        max_tokens: Max tokens setting
        model_config_name: Name of model config used
        company_id: Company being processed
        validation_passed: Whether output validation passed
        validation_warnings: Any validation warnings
        store_prompts: Whether to store full prompts in memory
        log_prompts: Whether to include prompts in log output

    Returns:
        LLMInteraction record
    """
    logger = get_logger("llm.interaction")

    # Create interaction record
    interaction = LLMInteraction(
        request_id=get_request_id(),
        trace_id=get_trace_id(),
        operation=operation,
        company_id=company_id or get_context_data().get("company_id"),
        model=model,
        temperature=temperature,
        max_tokens=max_tokens,
        model_config_name=model_config_name,
        system_prompt=system_prompt if store_prompts else None,
        system_prompt_hash=compute_content_hash(system_prompt),
        user_prompt=user_prompt if store_prompts else None,
        user_prompt_hash=compute_content_hash(user_prompt),
        response=response if store_prompts else None,
        response_hash=compute_content_hash(response),
        tokens_in=tokens_in,
        tokens_out=tokens_out,
        latency_ms=latency_ms,
        success=success,
        error_type=error_type,
        error_message=error_message,
        validation_passed=validation_passed,
        validation_warnings=validation_warnings or [],
    )

    # Store in memory for debugging
    _recent_interactions.append(interaction)
    if len(_recent_interactions) > _max_recent_interactions:
        _recent_interactions.pop(0)

    # Log the interaction
    log_data = interaction.to_log_dict(include_prompts=log_prompts)

    if success:
        logger.info(
            f"LLM call completed: {operation} ({model}) "
            f"- {tokens_in}+{tokens_out} tokens, {latency_ms}ms",
            extra={"llm_interaction": log_data},
        )
    else:
        logger.error(
            f"LLM call failed: {operation} ({model}) - {error_type}: {error_message}",
            extra={"llm_interaction": log_data},
        )

    return interaction


def get_recent_interactions(
    operation: Optional[str] = None,
    company_id: Optional[str] = None,
    limit: int = 10,
) -> list[LLMInteraction]:
    """
    Get recent LLM interactions for debugging.

    Args:
        operation: Filter by operation type
        company_id: Filter by company
        limit: Maximum number to return

    Returns:
        List of recent interactions (newest first)
    """
    interactions = _recent_interactions.copy()

    if operation:
        interactions = [i for i in interactions if i.operation == operation]

    if company_id:
        interactions = [i for i in interactions if i.company_id == company_id]

    return list(reversed(interactions[-limit:]))


def get_interaction_by_id(interaction_id: str) -> Optional[LLMInteraction]:
    """Get a specific interaction by ID."""
    for interaction in _recent_interactions:
        if interaction.interaction_id == interaction_id:
            return interaction
    return None


# =============================================================================
# FUNCTION TRACING DECORATOR
# =============================================================================

def trace_function(
    operation: Optional[str] = None,
    log_args: bool = False,
    log_result: bool = False,
):
    """
    Decorator to trace function execution.

    Args:
        operation: Operation name (defaults to function name)
        log_args: Whether to log function arguments
        log_result: Whether to log function result

    Example:
        @trace_function(operation="fetch_company")
        def fetch_company_data(company_id: str) -> dict:
            ...
    """
    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        @wraps(func)
        def wrapper(*args, **kwargs) -> T:
            logger = get_logger(func.__module__)
            op_name = operation or func.__name__

            # Create span
            parent_span = get_span_id()
            new_span = generate_span_id()
            _span_id.set(new_span)

            start_time = time.time()

            # Log entry
            log_extra = {
                "span_id": new_span,
                "parent_span_id": parent_span,
                "operation": op_name,
            }
            if log_args:
                log_extra["args"] = str(args)[:200]
                log_extra["kwargs"] = str(kwargs)[:200]

            logger.debug(f"Starting {op_name}", extra=log_extra)

            try:
                result = func(*args, **kwargs)
                duration_ms = int((time.time() - start_time) * 1000)

                log_extra["duration_ms"] = duration_ms
                log_extra["success"] = True
                if log_result:
                    log_extra["result"] = str(result)[:200]

                logger.debug(f"Completed {op_name} in {duration_ms}ms", extra=log_extra)

                return result

            except Exception as e:
                duration_ms = int((time.time() - start_time) * 1000)

                log_extra["duration_ms"] = duration_ms
                log_extra["success"] = False
                log_extra["error"] = str(e)

                logger.error(
                    f"Failed {op_name} after {duration_ms}ms: {e}",
                    extra=log_extra,
                    exc_info=True,
                )
                raise

            finally:
                # Restore parent span
                _span_id.set(parent_span)

        return wrapper
    return decorator


# =============================================================================
# AUDIT LOGGING
# =============================================================================

@dataclass
class AuditEvent:
    """An auditable event in the system."""
    event_id: str = field(default_factory=generate_request_id)
    timestamp: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    event_type: str = ""
    actor: Optional[str] = None  # User or system
    resource_type: Optional[str] = None  # company, briefing, etc.
    resource_id: Optional[str] = None
    action: str = ""  # create, read, update, delete
    details: dict = field(default_factory=dict)
    request_id: Optional[str] = None
    ip_address: Optional[str] = None
    user_agent: Optional[str] = None


_audit_log: list[AuditEvent] = []
_max_audit_events = 1000


def log_audit_event(
    event_type: str,
    action: str,
    resource_type: Optional[str] = None,
    resource_id: Optional[str] = None,
    actor: Optional[str] = None,
    details: Optional[dict] = None,
    ip_address: Optional[str] = None,
    user_agent: Optional[str] = None,
) -> AuditEvent:
    """
    Log an auditable event.

    Args:
        event_type: Type of event (access, modification, security, etc.)
        action: Action performed (create, read, update, delete)
        resource_type: Type of resource affected
        resource_id: ID of resource affected
        actor: Who performed the action
        details: Additional details
        ip_address: Client IP address
        user_agent: Client user agent

    Returns:
        AuditEvent record
    """
    logger = get_logger("audit")

    event = AuditEvent(
        event_type=event_type,
        action=action,
        resource_type=resource_type,
        resource_id=resource_id,
        actor=actor or get_context_data().get("user"),
        details=details or {},
        request_id=get_request_id(),
        ip_address=ip_address,
        user_agent=user_agent,
    )

    _audit_log.append(event)
    if len(_audit_log) > _max_audit_events:
        _audit_log.pop(0)

    logger.info(
        f"AUDIT: {event_type}/{action} on {resource_type}/{resource_id}",
        extra={"audit_event": asdict(event)},
    )

    return event


def get_audit_log(
    event_type: Optional[str] = None,
    resource_type: Optional[str] = None,
    resource_id: Optional[str] = None,
    limit: int = 100,
) -> list[AuditEvent]:
    """Get recent audit events with optional filtering."""
    events = _audit_log.copy()

    if event_type:
        events = [e for e in events if e.event_type == event_type]
    if resource_type:
        events = [e for e in events if e.resource_type == resource_type]
    if resource_id:
        events = [e for e in events if e.resource_id == resource_id]

    return list(reversed(events[-limit:]))

"""
Tests for Observability Module (core/observability.py)
======================================================

Tests request context, structured logging, LLM interaction logging, and audit events.
"""

import json
import logging
import pytest
from unittest.mock import patch

from core.observability import (
    # Request context
    generate_request_id,
    generate_trace_id,
    generate_span_id,
    get_request_id,
    get_trace_id,
    get_span_id,
    get_context_data,
    set_request_context,
    clear_request_context,
    LogContext,
    # Logging
    StructuredFormatter,
    HumanReadableFormatter,
    get_logger,
    # LLM interaction logging
    mask_pii,
    truncate_for_logging,
    LLMInteraction,
    compute_content_hash,
    log_llm_interaction,
    get_recent_interactions,
    get_interaction_by_id,
    # Function tracing
    trace_function,
    # Audit logging
    AuditEvent,
    log_audit_event,
    get_audit_log,
)


# =============================================================================
# TEST: Request Context Management
# =============================================================================

class TestRequestContext:
    """Tests for request context management."""

    def setup_method(self):
        clear_request_context()

    def teardown_method(self):
        clear_request_context()

    def test_generate_request_id_unique(self):
        """Generated request IDs are unique."""
        ids = [generate_request_id() for _ in range(50)]
        assert len(set(ids)) == 50

    def test_generate_trace_id_format(self):
        """Trace IDs are 16 hex characters."""
        trace_id = generate_trace_id()
        assert len(trace_id) == 16
        assert all(c in "0123456789abcdef" for c in trace_id)

    def test_generate_span_id_format(self):
        """Span IDs are 8 hex characters."""
        span_id = generate_span_id()
        assert len(span_id) == 8

    def test_set_request_context_generates_ids(self):
        """set_request_context generates IDs if not provided."""
        set_request_context()
        assert get_request_id() is not None
        assert get_trace_id() is not None

    def test_set_request_context_uses_provided_ids(self):
        """set_request_context uses provided IDs."""
        set_request_context(request_id="req-123", trace_id="trace-456")
        assert get_request_id() == "req-123"
        assert get_trace_id() == "trace-456"

    def test_set_request_context_extra_data(self):
        """Extra context data is stored."""
        set_request_context(company_id="stripe.com", user="ana")
        context = get_context_data()
        assert context["company_id"] == "stripe.com"
        assert context["user"] == "ana"

    def test_clear_request_context(self):
        """clear_request_context removes all context."""
        set_request_context(company_id="stripe.com")
        clear_request_context()
        assert get_request_id() is None
        assert get_context_data() == {}

    def test_log_context_manager(self):
        """LogContext context manager sets context."""
        with LogContext(company_id="stripe.com", user="ana"):
            assert get_context_data()["company_id"] == "stripe.com"


# =============================================================================
# TEST: Structured Logging
# =============================================================================

class TestStructuredFormatter:
    """Tests for JSON structured formatter."""

    def setup_method(self):
        clear_request_context()

    def test_formats_as_json(self):
        """Formatter outputs valid JSON."""
        formatter = StructuredFormatter()
        record = logging.LogRecord(
            name="test", level=logging.INFO, pathname="test.py",
            lineno=10, msg="Test message", args=(), exc_info=None,
        )
        output = formatter.format(record)
        parsed = json.loads(output)
        assert parsed["message"] == "Test message"
        assert parsed["level"] == "INFO"

    def test_includes_request_context(self):
        """JSON includes request context when set."""
        set_request_context(company_id="stripe.com")
        formatter = StructuredFormatter(include_context=True)
        record = logging.LogRecord(
            name="test", level=logging.INFO, pathname="test.py",
            lineno=10, msg="Test", args=(), exc_info=None,
        )
        output = formatter.format(record)
        parsed = json.loads(output)
        assert "request_id" in parsed
        assert parsed["context"]["company_id"] == "stripe.com"
        clear_request_context()


class TestHumanReadableFormatter:
    """Tests for human-readable formatter."""

    def test_formats_readable_output(self):
        """Formatter outputs human-readable text."""
        formatter = HumanReadableFormatter(use_colors=False)
        record = logging.LogRecord(
            name="test.module", level=logging.INFO, pathname="test.py",
            lineno=10, msg="Test message", args=(), exc_info=None,
        )
        output = formatter.format(record)
        assert "INFO" in output
        assert "Test message" in output


# =============================================================================
# TEST: PII Masking
# =============================================================================

class TestPIIMasking:
    """Tests for PII masking in logs."""

    def test_masks_email_addresses(self):
        """Email addresses are masked."""
        text = "Contact john.doe@example.com for help"
        masked = mask_pii(text)
        assert "[EMAIL]" in masked
        assert "john.doe@example.com" not in masked

    def test_masks_phone_numbers(self):
        """Phone numbers are masked."""
        text = "Call me at 555-123-4567"
        masked = mask_pii(text)
        assert "[PHONE]" in masked

    def test_masks_ssn(self):
        """Social security numbers are masked."""
        text = "SSN: 123-45-6789"
        masked = mask_pii(text)
        assert "[SSN]" in masked

    def test_preserves_non_pii(self):
        """Non-PII text is preserved."""
        text = "The company raised $50M in Series B"
        assert mask_pii(text) == text

    def test_handles_empty_string(self):
        """Empty string returns empty."""
        assert mask_pii("") == ""


# =============================================================================
# TEST: Text Truncation
# =============================================================================

class TestTextTruncation:
    """Tests for text truncation."""

    def test_short_text_unchanged(self):
        """Short text is not truncated."""
        assert truncate_for_logging("Short", max_length=100) == "Short"

    def test_long_text_truncated(self):
        """Long text is truncated with suffix."""
        text = "A" * 1000
        result = truncate_for_logging(text, max_length=100)
        assert len(result) == 100
        assert result.endswith("...[truncated]")

    def test_handles_none(self):
        """None input returns None."""
        assert truncate_for_logging(None, max_length=100) is None


# =============================================================================
# TEST: LLM Interaction Logging
# =============================================================================

class TestLLMInteractionLogging:
    """Tests for LLM interaction logging."""

    def setup_method(self):
        clear_request_context()
        from core.observability import _recent_interactions
        _recent_interactions.clear()

    def test_compute_content_hash(self):
        """Content hash is consistent."""
        h1 = compute_content_hash("Test")
        h2 = compute_content_hash("Test")
        assert h1 == h2
        assert len(h1) == 16

    def test_compute_content_hash_different(self):
        """Different content has different hash."""
        assert compute_content_hash("A") != compute_content_hash("B")

    def test_llm_interaction_dataclass(self):
        """LLMInteraction stores all fields."""
        i = LLMInteraction(operation="briefing", model="gpt-4o", tokens_in=100)
        assert i.operation == "briefing"
        assert i.tokens_in == 100

    def test_log_llm_interaction_returns_record(self):
        """log_llm_interaction returns LLMInteraction."""
        i = log_llm_interaction(operation="briefing", model="gpt-4o")
        assert isinstance(i, LLMInteraction)
        assert i.operation == "briefing"

    def test_log_llm_interaction_stores_in_memory(self):
        """Interactions are stored for debugging."""
        log_llm_interaction(operation="briefing", model="gpt-4o", company_id="stripe.com")
        interactions = get_recent_interactions()
        assert len(interactions) >= 1

    def test_get_interaction_by_id(self):
        """Can retrieve interaction by ID."""
        i = log_llm_interaction(operation="briefing", model="gpt-4o")
        retrieved = get_interaction_by_id(i.interaction_id)
        assert retrieved.interaction_id == i.interaction_id

    def test_log_llm_interaction_with_error(self):
        """Failed interactions are logged."""
        i = log_llm_interaction(
            operation="briefing", model="gpt-4o", success=False,
            error_type="APIError", error_message="Rate limit"
        )
        assert i.success is False
        assert i.error_type == "APIError"


# =============================================================================
# TEST: Function Tracing
# =============================================================================

class TestFunctionTracing:
    """Tests for function tracing decorator."""

    def setup_method(self):
        clear_request_context()

    def test_trace_function_success(self):
        """Traced function returns correct result."""
        @trace_function(operation="test_op")
        def add(a, b):
            return a + b
        assert add(2, 3) == 5

    def test_trace_function_preserves_exception(self):
        """Traced function re-raises exceptions."""
        @trace_function(operation="test_op")
        def failing():
            raise ValueError("Test error")
        with pytest.raises(ValueError, match="Test error"):
            failing()


# =============================================================================
# TEST: Audit Logging
# =============================================================================

class TestAuditLogging:
    """Tests for audit event logging."""

    def setup_method(self):
        from core.observability import _audit_log
        _audit_log.clear()
        clear_request_context()

    def test_log_audit_event_returns_event(self):
        """log_audit_event returns AuditEvent."""
        e = log_audit_event(event_type="access", action="read", resource_id="stripe.com")
        assert isinstance(e, AuditEvent)
        assert e.action == "read"

    def test_audit_event_has_id_and_timestamp(self):
        """Audit events have unique IDs and timestamps."""
        e1 = log_audit_event(event_type="test", action="create")
        e2 = log_audit_event(event_type="test", action="create")
        assert e1.event_id != e2.event_id
        assert e1.timestamp is not None

    def test_audit_event_includes_request_id(self):
        """Audit events include request ID from context."""
        set_request_context(request_id="req-123")
        e = log_audit_event(event_type="test", action="create")
        assert e.request_id == "req-123"
        clear_request_context()

    def test_get_audit_log_returns_events(self):
        """get_audit_log returns logged events."""
        log_audit_event(event_type="test1", action="create")
        log_audit_event(event_type="test2", action="update")
        events = get_audit_log()
        assert len(events) >= 2

    def test_get_audit_log_filters(self):
        """get_audit_log filters by event type."""
        log_audit_event(event_type="access", action="read")
        log_audit_event(event_type="modification", action="update")
        access_events = get_audit_log(event_type="access")
        assert all(e.event_type == "access" for e in access_events)


# =============================================================================
# TEST: Integration
# =============================================================================

class TestObservabilityIntegration:
    """Integration tests for observability components."""

    def setup_method(self):
        clear_request_context()
        from core.observability import _recent_interactions, _audit_log
        _recent_interactions.clear()
        _audit_log.clear()

    def test_full_request_lifecycle(self):
        """Test complete request lifecycle with all observability features."""
        with LogContext(company_id="stripe.com", user="ana"):
            interaction = log_llm_interaction(
                operation="briefing", model="gpt-4o-mini",
                tokens_in=100, tokens_out=500, latency_ms=1500, success=True,
            )
            audit = log_audit_event(
                event_type="briefing", action="create",
                resource_id="stripe.com", details={"tokens": 600},
            )

        assert interaction.company_id == "stripe.com"
        assert audit.actor == "ana"
        assert len(get_recent_interactions(company_id="stripe.com")) >= 1

"""
Tests for API Resilience Utilities
==================================

Tests retry logic, circuit breakers, and error classification.
"""

import time
import pytest
from unittest.mock import Mock, patch

from core.resilience import (
    ErrorCategory,
    classify_error,
    is_retryable_error,
    calculate_backoff_delay,
    retry_with_backoff,
    RetryConfig,
    RateLimitHandler,
    CircuitBreaker,
    CircuitState,
    get_circuit_breaker,
    resilient_call,
)


# =============================================================================
# TEST: Error Classification
# =============================================================================

class TestErrorClassification:
    """Tests for error classification logic."""

    def test_classify_429_as_rate_limit(self):
        """429 status code is classified as rate limit."""
        exc = Exception("Too many requests")
        category = classify_error(exc, status_code=429)
        assert category == ErrorCategory.RATE_LIMIT

    def test_classify_503_as_transient(self):
        """503 status code is classified as transient."""
        exc = Exception("Service unavailable")
        category = classify_error(exc, status_code=503)
        assert category == ErrorCategory.TRANSIENT

    def test_classify_500_as_transient(self):
        """500 status code is classified as transient."""
        exc = Exception("Internal server error")
        category = classify_error(exc, status_code=500)
        assert category == ErrorCategory.TRANSIENT

    def test_classify_401_as_permanent(self):
        """401 status code is classified as permanent."""
        exc = Exception("Unauthorized")
        category = classify_error(exc, status_code=401)
        assert category == ErrorCategory.PERMANENT

    def test_classify_404_as_permanent(self):
        """404 status code is classified as permanent."""
        exc = Exception("Not found")
        category = classify_error(exc, status_code=404)
        assert category == ErrorCategory.PERMANENT

    def test_classify_timeout_exception_as_transient(self):
        """Timeout exceptions are classified as transient."""

        class TimeoutError(Exception):
            pass

        exc = TimeoutError("Request timed out")
        category = classify_error(exc)
        assert category == ErrorCategory.TRANSIENT

    def test_classify_connection_exception_as_transient(self):
        """Connection exceptions are classified as transient."""

        class ConnectionError(Exception):
            pass

        exc = ConnectionError("Connection refused")
        category = classify_error(exc)
        assert category == ErrorCategory.TRANSIENT

    def test_classify_rate_limit_message_as_rate_limit(self):
        """Exceptions with 'rate limit' in message are classified."""
        exc = Exception("Rate limit exceeded, try again later")
        category = classify_error(exc)
        assert category == ErrorCategory.RATE_LIMIT

    def test_is_retryable_for_transient(self):
        """Transient errors are retryable."""
        exc = Exception("timeout")
        assert is_retryable_error(exc, status_code=503) is True

    def test_is_retryable_for_rate_limit(self):
        """Rate limit errors are retryable."""
        exc = Exception("rate limit")
        assert is_retryable_error(exc, status_code=429) is True

    def test_is_not_retryable_for_permanent(self):
        """Permanent errors are not retryable."""
        exc = Exception("not found")
        assert is_retryable_error(exc, status_code=404) is False


# =============================================================================
# TEST: Backoff Calculation
# =============================================================================

class TestBackoffCalculation:
    """Tests for exponential backoff delay calculation."""

    def test_first_attempt_uses_base_delay(self):
        """First attempt (0) uses base delay."""
        delay = calculate_backoff_delay(0, base_delay=1.0, jitter=False)
        assert delay == 1.0

    def test_exponential_growth(self):
        """Delay grows exponentially."""
        delay0 = calculate_backoff_delay(0, base_delay=1.0, jitter=False)
        delay1 = calculate_backoff_delay(1, base_delay=1.0, jitter=False)
        delay2 = calculate_backoff_delay(2, base_delay=1.0, jitter=False)

        assert delay0 == 1.0
        assert delay1 == 2.0
        assert delay2 == 4.0

    def test_respects_max_delay(self):
        """Delay is capped at max_delay."""
        delay = calculate_backoff_delay(
            10,  # Would be 1024 without cap
            base_delay=1.0,
            max_delay=30.0,
            jitter=False,
        )
        assert delay == 30.0

    def test_jitter_adds_variance(self):
        """Jitter adds randomness to delay."""
        delays = [
            calculate_backoff_delay(1, base_delay=1.0, jitter=True)
            for _ in range(10)
        ]
        # With jitter, not all delays should be identical
        assert len(set(delays)) > 1


# =============================================================================
# TEST: Retry Decorator
# =============================================================================

class TestRetryDecorator:
    """Tests for retry_with_backoff decorator."""

    def test_success_on_first_try(self):
        """Successful first attempt returns immediately."""
        call_count = 0

        @retry_with_backoff(max_retries=3)
        def always_succeeds():
            nonlocal call_count
            call_count += 1
            return "success"

        result = always_succeeds()
        assert result == "success"
        assert call_count == 1

    def test_retries_on_transient_failure(self):
        """Transient failures trigger retries."""
        call_count = 0

        class TransientError(Exception):
            status_code = 503

        @retry_with_backoff(max_retries=3, base_delay=0.01)
        def fails_then_succeeds():
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise TransientError("temporary failure")
            return "success"

        result = fails_then_succeeds()
        assert result == "success"
        assert call_count == 3

    def test_raises_after_max_retries(self):
        """Raises exception after exhausting retries."""

        class TransientError(Exception):
            status_code = 503

        @retry_with_backoff(max_retries=2, base_delay=0.01)
        def always_fails():
            raise TransientError("always fails")

        with pytest.raises(TransientError):
            always_fails()

    def test_no_retry_on_permanent_error(self):
        """Permanent errors are not retried."""
        call_count = 0

        class PermanentError(Exception):
            status_code = 404

        @retry_with_backoff(max_retries=3, base_delay=0.01)
        def permanent_failure():
            nonlocal call_count
            call_count += 1
            raise PermanentError("not found")

        with pytest.raises(PermanentError):
            permanent_failure()

        assert call_count == 1  # No retries

    def test_retry_on_specific_exceptions(self):
        """retry_on parameter limits which exceptions are retried."""

        class RetryableError(Exception):
            pass

        class NonRetryableError(Exception):
            pass

        call_count = 0

        @retry_with_backoff(max_retries=3, base_delay=0.01, retry_on=(RetryableError,))
        def selective_retry():
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise RetryableError("retry me")
            return "success"

        result = selective_retry()
        assert result == "success"
        assert call_count == 2

    def test_on_retry_callback(self):
        """on_retry callback is called before each retry."""
        retries = []

        class TransientError(Exception):
            status_code = 503

        def on_retry(exc, attempt):
            retries.append((type(exc).__name__, attempt))

        @retry_with_backoff(max_retries=2, base_delay=0.01, on_retry=on_retry)
        def fails_twice():
            if len(retries) < 2:
                raise TransientError("fail")
            return "success"

        result = fails_twice()
        assert result == "success"
        assert len(retries) == 2
        assert retries[0] == ("TransientError", 1)
        assert retries[1] == ("TransientError", 2)


# =============================================================================
# TEST: Rate Limit Handler
# =============================================================================

class TestRateLimitHandler:
    """Tests for RateLimitHandler."""

    def test_wait_enforces_rps_limit(self):
        """wait_if_needed enforces rate limit."""
        handler = RateLimitHandler(default_rps=100)  # 10ms between requests

        start = time.time()
        handler.wait_if_needed("test")
        handler.wait_if_needed("test")
        elapsed = time.time() - start

        # Should have waited at least 10ms
        assert elapsed >= 0.01

    def test_record_429_sets_retry_after(self):
        """Recording 429 response sets retry_after."""
        handler = RateLimitHandler()

        handler.record_response(
            "test",
            status_code=429,
            headers={"Retry-After": "5"},
        )

        stats = handler.get_stats("test")
        assert stats["retry_after"] is not None

    def test_per_service_limits(self):
        """Different services can have different limits."""
        handler = RateLimitHandler(default_rps=10)
        handler.set_limit("fast", 100)
        handler.set_limit("slow", 1)

        stats_fast = handler.get_stats("fast")
        stats_slow = handler.get_stats("slow")

        assert stats_fast["rps_limit"] == 100
        assert stats_slow["rps_limit"] == 1


# =============================================================================
# TEST: Circuit Breaker
# =============================================================================

class TestCircuitBreaker:
    """Tests for CircuitBreaker."""

    def test_starts_closed(self):
        """Circuit breaker starts in closed state."""
        cb = CircuitBreaker("test")
        assert cb.is_closed
        assert not cb.is_open

    def test_opens_after_failure_threshold(self):
        """Circuit opens after reaching failure threshold."""
        cb = CircuitBreaker("test", failure_threshold=3)

        cb.record_failure()
        cb.record_failure()
        assert cb.is_closed

        cb.record_failure()
        assert cb.is_open

    def test_rejects_requests_when_open(self):
        """Open circuit rejects requests."""
        cb = CircuitBreaker("test", failure_threshold=1)
        cb.record_failure()

        assert cb.is_open
        assert not cb.allow_request()

    def test_transitions_to_half_open_after_timeout(self):
        """Circuit transitions to half-open after timeout."""
        cb = CircuitBreaker("test", failure_threshold=1, timeout=0.1)
        cb.record_failure()

        assert cb.is_open

        time.sleep(0.15)
        assert cb.state == CircuitState.HALF_OPEN

    def test_closes_after_successes_in_half_open(self):
        """Circuit closes after successful requests in half-open."""
        cb = CircuitBreaker(
            "test",
            failure_threshold=1,
            success_threshold=2,
            timeout=0.1,
        )
        cb.record_failure()
        time.sleep(0.15)

        assert cb.state == CircuitState.HALF_OPEN

        cb.record_success()
        cb.record_success()

        assert cb.is_closed

    def test_reopens_on_failure_in_half_open(self):
        """Circuit reopens on failure in half-open state."""
        cb = CircuitBreaker("test", failure_threshold=1, timeout=0.1)
        cb.record_failure()
        time.sleep(0.15)

        assert cb.state == CircuitState.HALF_OPEN

        cb.record_failure()
        assert cb.is_open

    def test_reset(self):
        """Manual reset closes the circuit."""
        cb = CircuitBreaker("test", failure_threshold=1)
        cb.record_failure()
        assert cb.is_open

        cb.reset()
        assert cb.is_closed

    def test_success_resets_failure_count(self):
        """Success in closed state resets failure count."""
        cb = CircuitBreaker("test", failure_threshold=3)

        cb.record_failure()
        cb.record_failure()
        cb.record_success()  # Resets count
        cb.record_failure()
        cb.record_failure()

        # Should still be closed (count was reset)
        assert cb.is_closed


# =============================================================================
# TEST: Circuit Breaker Registry
# =============================================================================

class TestCircuitBreakerRegistry:
    """Tests for circuit breaker registry."""

    def test_get_returns_same_instance(self):
        """get_circuit_breaker returns same instance for same name."""
        cb1 = get_circuit_breaker("test_service")
        cb2 = get_circuit_breaker("test_service")
        assert cb1 is cb2

    def test_different_names_different_instances(self):
        """Different service names get different circuit breakers."""
        cb1 = get_circuit_breaker("service_a")
        cb2 = get_circuit_breaker("service_b")
        assert cb1 is not cb2


# =============================================================================
# TEST: Resilient Call
# =============================================================================

class TestResilientCall:
    """Tests for resilient_call wrapper."""

    def test_success_returns_result(self):
        """Successful call returns result."""

        def success_func():
            return "result"

        result = resilient_call(
            success_func,
            service_name="test_resilient",
            use_circuit_breaker=False,
        )
        assert result == "result"

    def test_uses_fallback_on_failure(self):
        """Falls back when all retries fail."""

        class PermanentError(Exception):
            status_code = 500

        call_count = 0

        def failing_func():
            nonlocal call_count
            call_count += 1
            raise PermanentError("always fails")

        def fallback():
            return "fallback_result"

        result = resilient_call(
            failing_func,
            service_name="test_fallback",
            max_retries=2,
            use_circuit_breaker=False,
            fallback=fallback,
        )
        assert result == "fallback_result"

    def test_raises_without_fallback(self):
        """Raises exception when no fallback provided."""

        class PermanentError(Exception):
            status_code = 404  # Permanent, won't retry

        def failing_func():
            raise PermanentError("not found")

        with pytest.raises(PermanentError):
            resilient_call(
                failing_func,
                service_name="test_no_fallback",
                max_retries=0,
                use_circuit_breaker=False,
            )

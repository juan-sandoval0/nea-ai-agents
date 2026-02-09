"""
API Resilience Utilities
========================

Provides retry logic, circuit breakers, and graceful degradation for API calls.

Why this is crucial:
1. APIs fail transiently - retries with backoff recover most failures
2. Rate limits need proper handling - respecting Retry-After prevents bans
3. Circuit breakers prevent cascading failures when services are down
4. Without resilience, temporary issues become permanent user-facing errors

Usage:
    from core.resilience import (
        retry_with_backoff,
        RateLimitHandler,
        CircuitBreaker,
        is_retryable_error,
    )

    # Decorator for automatic retries
    @retry_with_backoff(max_retries=3)
    def call_api():
        return requests.get(url)

    # Rate limit handler
    rate_limiter = RateLimitHandler()
    rate_limiter.wait_if_needed("harmonic")
    response = requests.get(url)
    rate_limiter.record_response("harmonic", response)

    # Circuit breaker
    breaker = CircuitBreaker("harmonic", failure_threshold=5)
    if breaker.is_open:
        return cached_result  # Fast fail
    try:
        result = call_api()
        breaker.record_success()
    except Exception as e:
        breaker.record_failure()
        raise
"""

from __future__ import annotations

import logging
import random
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from functools import wraps
from threading import Lock
from typing import Any, Callable, Optional, Type, TypeVar, Union

logger = logging.getLogger(__name__)

T = TypeVar("T")


# =============================================================================
# ERROR CLASSIFICATION
# =============================================================================

class ErrorCategory(str, Enum):
    """Categories of API errors for handling decisions."""
    TRANSIENT = "transient"      # Retry with backoff (timeout, 503, 429)
    RATE_LIMIT = "rate_limit"    # Retry after delay (429 with Retry-After)
    PERMANENT = "permanent"      # Don't retry (401, 404, 400)
    UNKNOWN = "unknown"          # Depends on context


# Status codes that indicate transient failures (should retry)
TRANSIENT_STATUS_CODES = {
    408,  # Request Timeout
    429,  # Too Many Requests (rate limit)
    500,  # Internal Server Error
    502,  # Bad Gateway
    503,  # Service Unavailable
    504,  # Gateway Timeout
}

# Status codes that indicate permanent failures (don't retry)
PERMANENT_STATUS_CODES = {
    400,  # Bad Request
    401,  # Unauthorized
    403,  # Forbidden
    404,  # Not Found
    405,  # Method Not Allowed
    410,  # Gone
    422,  # Unprocessable Entity
}


def classify_error(
    exception: Exception,
    status_code: Optional[int] = None,
) -> ErrorCategory:
    """
    Classify an error to determine handling strategy.

    Args:
        exception: The exception that occurred
        status_code: HTTP status code if available

    Returns:
        ErrorCategory indicating how to handle the error
    """
    # Check status code first
    if status_code:
        if status_code == 429:
            return ErrorCategory.RATE_LIMIT
        if status_code in TRANSIENT_STATUS_CODES:
            return ErrorCategory.TRANSIENT
        if status_code in PERMANENT_STATUS_CODES:
            return ErrorCategory.PERMANENT

    # Check exception type
    exception_name = type(exception).__name__.lower()

    # Network/connection errors are transient
    transient_patterns = [
        "timeout", "connection", "temporary", "unavailable",
        "reset", "refused", "network", "socket",
    ]
    if any(pattern in exception_name for pattern in transient_patterns):
        return ErrorCategory.TRANSIENT

    # Check exception message
    message = str(exception).lower()
    if any(pattern in message for pattern in transient_patterns):
        return ErrorCategory.TRANSIENT

    if "rate limit" in message or "too many requests" in message:
        return ErrorCategory.RATE_LIMIT

    if "unauthorized" in message or "forbidden" in message:
        return ErrorCategory.PERMANENT

    return ErrorCategory.UNKNOWN


def is_retryable_error(
    exception: Exception,
    status_code: Optional[int] = None,
) -> bool:
    """
    Check if an error should be retried.

    Args:
        exception: The exception that occurred
        status_code: HTTP status code if available

    Returns:
        True if the error is likely transient and worth retrying
    """
    category = classify_error(exception, status_code)
    return category in (ErrorCategory.TRANSIENT, ErrorCategory.RATE_LIMIT)


# =============================================================================
# RETRY WITH EXPONENTIAL BACKOFF
# =============================================================================

@dataclass
class RetryConfig:
    """Configuration for retry behavior."""
    max_retries: int = 3
    base_delay: float = 1.0        # Initial delay in seconds
    max_delay: float = 60.0        # Maximum delay between retries
    exponential_base: float = 2.0  # Multiplier for each retry
    jitter: bool = True            # Add randomness to prevent thundering herd
    retry_on: tuple = ()           # Exception types to retry (empty = all retryable)


def calculate_backoff_delay(
    attempt: int,
    base_delay: float = 1.0,
    max_delay: float = 60.0,
    exponential_base: float = 2.0,
    jitter: bool = True,
) -> float:
    """
    Calculate delay for exponential backoff.

    Args:
        attempt: Current attempt number (0-indexed)
        base_delay: Initial delay in seconds
        max_delay: Maximum delay cap
        exponential_base: Multiplier for each attempt
        jitter: Whether to add random jitter

    Returns:
        Delay in seconds before next retry
    """
    # Exponential backoff: base_delay * (exponential_base ^ attempt)
    delay = base_delay * (exponential_base ** attempt)

    # Cap at maximum
    delay = min(delay, max_delay)

    # Add jitter (±25%) to prevent thundering herd
    if jitter:
        jitter_range = delay * 0.25
        delay = delay + random.uniform(-jitter_range, jitter_range)

    return max(0, delay)


def retry_with_backoff(
    max_retries: int = 3,
    base_delay: float = 1.0,
    max_delay: float = 60.0,
    exponential_base: float = 2.0,
    jitter: bool = True,
    retry_on: tuple[Type[Exception], ...] = (),
    on_retry: Optional[Callable[[Exception, int], None]] = None,
):
    """
    Decorator that retries a function with exponential backoff.

    Why: Transient failures (network blips, temporary overload) often
    succeed on retry. Exponential backoff prevents overwhelming the service.

    Args:
        max_retries: Maximum number of retry attempts
        base_delay: Initial delay between retries (seconds)
        max_delay: Maximum delay between retries (seconds)
        exponential_base: Multiplier for delay each retry
        jitter: Add randomness to delays (prevents thundering herd)
        retry_on: Tuple of exception types to retry (empty = use is_retryable_error)
        on_retry: Optional callback(exception, attempt) called before each retry

    Returns:
        Decorated function with retry logic

    Example:
        @retry_with_backoff(max_retries=3)
        def call_api():
            return requests.get(url)
    """
    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        @wraps(func)
        def wrapper(*args, **kwargs) -> T:
            last_exception: Optional[Exception] = None

            for attempt in range(max_retries + 1):
                try:
                    return func(*args, **kwargs)

                except Exception as e:
                    last_exception = e

                    # Check if we should retry this exception
                    should_retry = False
                    if retry_on:
                        should_retry = isinstance(e, retry_on)
                    else:
                        # Extract status code if available
                        status_code = getattr(e, "status_code", None)
                        should_retry = is_retryable_error(e, status_code)

                    # Don't retry on last attempt or non-retryable errors
                    if attempt >= max_retries or not should_retry:
                        raise

                    # Calculate delay
                    delay = calculate_backoff_delay(
                        attempt,
                        base_delay=base_delay,
                        max_delay=max_delay,
                        exponential_base=exponential_base,
                        jitter=jitter,
                    )

                    # Check for Retry-After header in the exception
                    retry_after = getattr(e, "retry_after", None)
                    if retry_after and retry_after > delay:
                        delay = min(retry_after, max_delay)

                    # Call retry callback if provided
                    if on_retry:
                        on_retry(e, attempt + 1)
                    else:
                        logger.warning(
                            f"Retry {attempt + 1}/{max_retries} for {func.__name__} "
                            f"after {delay:.1f}s: {type(e).__name__}: {e}"
                        )

                    time.sleep(delay)

            # Should never reach here, but just in case
            if last_exception:
                raise last_exception
            raise RuntimeError("Retry loop exited unexpectedly")

        return wrapper
    return decorator


# =============================================================================
# RATE LIMIT HANDLER
# =============================================================================

@dataclass
class RateLimitState:
    """Tracks rate limit state for a service."""
    requests_made: int = 0
    window_start: float = field(default_factory=time.time)
    retry_after: Optional[float] = None  # Timestamp when we can retry
    last_request: float = 0.0


class RateLimitHandler:
    """
    Handles rate limiting for API calls.

    Features:
    - Client-side rate limiting (requests per second)
    - Retry-After header parsing
    - Per-service tracking

    Why: Proper rate limit handling prevents 429 errors and API bans.
    Respecting Retry-After headers shows good API citizenship.
    """

    def __init__(self, default_rps: float = 10.0):
        """
        Initialize rate limit handler.

        Args:
            default_rps: Default requests per second limit
        """
        self.default_rps = default_rps
        self._states: dict[str, RateLimitState] = {}
        self._rps_limits: dict[str, float] = {}
        self._lock = Lock()

    def set_limit(self, service: str, rps: float) -> None:
        """Set rate limit for a specific service."""
        self._rps_limits[service] = rps

    def _get_state(self, service: str) -> RateLimitState:
        """Get or create state for a service."""
        if service not in self._states:
            self._states[service] = RateLimitState()
        return self._states[service]

    def wait_if_needed(self, service: str) -> float:
        """
        Wait if necessary to respect rate limits.

        Args:
            service: Service name (e.g., "harmonic", "openai")

        Returns:
            Seconds waited (0 if no wait needed)
        """
        with self._lock:
            state = self._get_state(service)
            now = time.time()
            waited = 0.0

            # Check if we're in a Retry-After period
            if state.retry_after and now < state.retry_after:
                wait_time = state.retry_after - now
                logger.info(
                    f"Rate limit: waiting {wait_time:.1f}s for {service} "
                    f"(Retry-After)"
                )
                time.sleep(wait_time)
                waited = wait_time
                state.retry_after = None

            # Enforce RPS limit
            rps = self._rps_limits.get(service, self.default_rps)
            min_interval = 1.0 / rps
            elapsed = now - state.last_request

            if elapsed < min_interval:
                wait_time = min_interval - elapsed
                time.sleep(wait_time)
                waited += wait_time

            state.last_request = time.time()
            state.requests_made += 1

            return waited

    def record_response(
        self,
        service: str,
        status_code: int,
        headers: Optional[dict] = None,
    ) -> None:
        """
        Record API response to update rate limit state.

        Args:
            service: Service name
            status_code: HTTP status code
            headers: Response headers (for Retry-After)
        """
        with self._lock:
            state = self._get_state(service)

            if status_code == 429:
                # Parse Retry-After header
                retry_after = self._parse_retry_after(headers)
                if retry_after:
                    state.retry_after = time.time() + retry_after
                    logger.warning(
                        f"Rate limit hit for {service}. "
                        f"Retry after {retry_after:.1f}s"
                    )
                else:
                    # Default backoff if no Retry-After header
                    state.retry_after = time.time() + 60
                    logger.warning(
                        f"Rate limit hit for {service}. "
                        f"Using default 60s backoff"
                    )

    def _parse_retry_after(self, headers: Optional[dict]) -> Optional[float]:
        """
        Parse Retry-After header value.

        Handles both seconds format and HTTP-date format.
        """
        if not headers:
            return None

        retry_after = headers.get("Retry-After") or headers.get("retry-after")
        if not retry_after:
            return None

        try:
            # Try parsing as seconds
            return float(retry_after)
        except ValueError:
            pass

        try:
            # Try parsing as HTTP-date
            from email.utils import parsedate_to_datetime
            dt = parsedate_to_datetime(retry_after)
            return max(0, (dt - datetime.now(dt.tzinfo)).total_seconds())
        except Exception:
            pass

        return None

    def get_stats(self, service: str) -> dict:
        """Get rate limit stats for a service."""
        state = self._get_state(service)
        return {
            "requests_made": state.requests_made,
            "retry_after": state.retry_after,
            "rps_limit": self._rps_limits.get(service, self.default_rps),
        }


# =============================================================================
# CIRCUIT BREAKER
# =============================================================================

class CircuitState(str, Enum):
    """Circuit breaker states."""
    CLOSED = "closed"      # Normal operation
    OPEN = "open"          # Failing, reject requests
    HALF_OPEN = "half_open"  # Testing if service recovered


@dataclass
class CircuitBreaker:
    """
    Circuit breaker to prevent cascading failures.

    Why: When a service is down, continuing to send requests:
    - Wastes resources
    - Increases latency
    - Can make recovery harder
    Circuit breakers "fail fast" and give services time to recover.

    States:
    - CLOSED: Normal operation, requests flow through
    - OPEN: Service is failing, reject requests immediately
    - HALF_OPEN: Testing if service recovered, allow limited requests
    """
    name: str
    failure_threshold: int = 5       # Failures before opening
    success_threshold: int = 2       # Successes in half-open to close
    timeout: float = 60.0            # Seconds before trying half-open
    half_open_max_calls: int = 3     # Max calls in half-open state

    # State tracking (not in __init__ params)
    _state: CircuitState = field(default=CircuitState.CLOSED, init=False)
    _failure_count: int = field(default=0, init=False)
    _success_count: int = field(default=0, init=False)
    _last_failure_time: Optional[float] = field(default=None, init=False)
    _half_open_calls: int = field(default=0, init=False)
    _lock: Lock = field(default_factory=Lock, init=False)

    @property
    def state(self) -> CircuitState:
        """Get current circuit state, checking for timeout transition."""
        with self._lock:
            if self._state == CircuitState.OPEN:
                # Check if timeout has passed
                if self._last_failure_time:
                    elapsed = time.time() - self._last_failure_time
                    if elapsed >= self.timeout:
                        self._transition_to_half_open()
            return self._state

    @property
    def is_open(self) -> bool:
        """Check if circuit is open (should reject requests)."""
        return self.state == CircuitState.OPEN

    @property
    def is_closed(self) -> bool:
        """Check if circuit is closed (normal operation)."""
        return self.state == CircuitState.CLOSED

    def allow_request(self) -> bool:
        """
        Check if a request should be allowed.

        Returns:
            True if request is allowed, False if circuit is open
        """
        state = self.state  # Triggers timeout check

        if state == CircuitState.CLOSED:
            return True

        if state == CircuitState.OPEN:
            return False

        # Half-open: allow limited requests
        with self._lock:
            if self._half_open_calls < self.half_open_max_calls:
                self._half_open_calls += 1
                return True
            return False

    def record_success(self) -> None:
        """Record a successful request."""
        with self._lock:
            if self._state == CircuitState.HALF_OPEN:
                self._success_count += 1
                if self._success_count >= self.success_threshold:
                    self._transition_to_closed()
            elif self._state == CircuitState.CLOSED:
                # Reset failure count on success
                self._failure_count = 0

    def record_failure(self, exception: Optional[Exception] = None) -> None:
        """Record a failed request."""
        with self._lock:
            self._failure_count += 1
            self._last_failure_time = time.time()

            if self._state == CircuitState.HALF_OPEN:
                # Any failure in half-open reopens the circuit
                self._transition_to_open()
            elif self._state == CircuitState.CLOSED:
                if self._failure_count >= self.failure_threshold:
                    self._transition_to_open()

    def _transition_to_open(self) -> None:
        """Transition to open state."""
        logger.warning(
            f"Circuit breaker '{self.name}' OPENED after "
            f"{self._failure_count} failures"
        )
        self._state = CircuitState.OPEN
        self._success_count = 0
        self._half_open_calls = 0

    def _transition_to_half_open(self) -> None:
        """Transition to half-open state."""
        logger.info(
            f"Circuit breaker '{self.name}' transitioning to HALF-OPEN "
            f"after {self.timeout}s timeout"
        )
        self._state = CircuitState.HALF_OPEN
        self._success_count = 0
        self._half_open_calls = 0

    def _transition_to_closed(self) -> None:
        """Transition to closed state."""
        logger.info(
            f"Circuit breaker '{self.name}' CLOSED after "
            f"{self._success_count} successes"
        )
        self._state = CircuitState.CLOSED
        self._failure_count = 0
        self._success_count = 0
        self._half_open_calls = 0

    def reset(self) -> None:
        """Manually reset the circuit breaker."""
        with self._lock:
            self._state = CircuitState.CLOSED
            self._failure_count = 0
            self._success_count = 0
            self._last_failure_time = None
            self._half_open_calls = 0

    def get_stats(self) -> dict:
        """Get circuit breaker statistics."""
        return {
            "name": self.name,
            "state": self.state.value,
            "failure_count": self._failure_count,
            "success_count": self._success_count,
            "last_failure": self._last_failure_time,
        }


# =============================================================================
# CIRCUIT BREAKER REGISTRY
# =============================================================================

class CircuitBreakerRegistry:
    """Registry of circuit breakers for different services."""

    def __init__(self):
        self._breakers: dict[str, CircuitBreaker] = {}
        self._lock = Lock()

    def get(
        self,
        name: str,
        failure_threshold: int = 5,
        timeout: float = 60.0,
    ) -> CircuitBreaker:
        """Get or create a circuit breaker for a service."""
        with self._lock:
            if name not in self._breakers:
                self._breakers[name] = CircuitBreaker(
                    name=name,
                    failure_threshold=failure_threshold,
                    timeout=timeout,
                )
            return self._breakers[name]

    def get_all_stats(self) -> dict[str, dict]:
        """Get stats for all circuit breakers."""
        return {name: cb.get_stats() for name, cb in self._breakers.items()}


# Global registry
_circuit_registry: Optional[CircuitBreakerRegistry] = None


def get_circuit_breaker(
    name: str,
    failure_threshold: int = 5,
    timeout: float = 60.0,
) -> CircuitBreaker:
    """Get a circuit breaker from the global registry."""
    global _circuit_registry
    if _circuit_registry is None:
        _circuit_registry = CircuitBreakerRegistry()
    return _circuit_registry.get(name, failure_threshold, timeout)


# =============================================================================
# RESILIENT API CALL WRAPPER
# =============================================================================

def resilient_call(
    func: Callable[..., T],
    *args,
    service_name: str = "default",
    max_retries: int = 3,
    use_circuit_breaker: bool = True,
    fallback: Optional[Callable[[], T]] = None,
    **kwargs,
) -> T:
    """
    Execute an API call with full resilience (retries + circuit breaker).

    This is the recommended way to make API calls that need resilience.

    Args:
        func: Function to call
        *args: Positional arguments for func
        service_name: Service name for circuit breaker
        max_retries: Maximum retry attempts
        use_circuit_breaker: Whether to use circuit breaker
        fallback: Optional fallback function if all retries fail
        **kwargs: Keyword arguments for func

    Returns:
        Result from func, or fallback result

    Raises:
        Exception: If all retries fail and no fallback provided
    """
    # Check circuit breaker
    if use_circuit_breaker:
        breaker = get_circuit_breaker(service_name)
        if not breaker.allow_request():
            logger.warning(
                f"Circuit breaker open for {service_name}, "
                f"using fallback or failing fast"
            )
            if fallback:
                return fallback()
            raise RuntimeError(
                f"Circuit breaker open for {service_name}"
            )

    last_exception: Optional[Exception] = None

    for attempt in range(max_retries + 1):
        try:
            result = func(*args, **kwargs)

            # Record success
            if use_circuit_breaker:
                breaker.record_success()

            return result

        except Exception as e:
            last_exception = e

            # Record failure
            if use_circuit_breaker:
                breaker.record_failure(e)

            # Check if retryable
            status_code = getattr(e, "status_code", None)
            if not is_retryable_error(e, status_code):
                raise

            if attempt >= max_retries:
                break

            # Calculate delay
            delay = calculate_backoff_delay(attempt)
            logger.warning(
                f"Retry {attempt + 1}/{max_retries} for {service_name} "
                f"after {delay:.1f}s: {e}"
            )
            time.sleep(delay)

    # All retries failed
    if fallback:
        logger.warning(
            f"All retries failed for {service_name}, using fallback"
        )
        return fallback()

    if last_exception:
        raise last_exception
    raise RuntimeError("Resilient call failed unexpectedly")

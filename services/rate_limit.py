"""
Upstash Redis Rate Limiting
===========================

Thin Python shim for Upstash Redis REST API rate limiting.
Falls through with a warning if UPSTASH_REDIS_REST_URL is not set.

Usage:
    from services.rate_limit import check_rate_limit, RateLimitExceeded

    # In your endpoint
    try:
        check_rate_limit(key="briefing", identifier=api_key, limit=10, window=60)
    except RateLimitExceeded as e:
        return JSONResponse(status_code=429, content={"detail": str(e)})
"""

import logging
import os
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

# Configuration from environment
UPSTASH_REDIS_REST_URL = os.getenv("UPSTASH_REDIS_REST_URL")
UPSTASH_REDIS_REST_TOKEN = os.getenv("UPSTASH_REDIS_REST_TOKEN")


class RateLimitExceeded(Exception):
    """Raised when rate limit is exceeded."""

    def __init__(self, limit: int, window: int, retry_after: int = 0):
        self.limit = limit
        self.window = window
        self.retry_after = retry_after
        super().__init__(
            f"Rate limit exceeded: {limit} requests per {window} seconds. "
            f"Retry after {retry_after} seconds."
        )


def _is_configured() -> bool:
    """Check if Upstash Redis is configured."""
    return bool(UPSTASH_REDIS_REST_URL and UPSTASH_REDIS_REST_TOKEN)


def check_rate_limit(
    key: str,
    identifier: str,
    limit: int,
    window: int = 60,
) -> bool:
    """
    Check and increment rate limit counter.

    Args:
        key: Rate limit key prefix (e.g., "briefing", "outreach")
        identifier: Unique identifier (e.g., API key, IP address)
        limit: Maximum requests allowed in window
        window: Time window in seconds (default: 60)

    Returns:
        True if request is allowed

    Raises:
        RateLimitExceeded: If rate limit is exceeded
    """
    if not _is_configured():
        logger.debug("Upstash Redis not configured, skipping rate limit check")
        return True

    # Build the rate limit key
    rate_key = f"ratelimit:{key}:{identifier}"

    try:
        # Use Upstash REST API to increment and check
        # INCR + EXPIRE pattern for sliding window
        with httpx.Client(timeout=5.0) as client:
            headers = {"Authorization": f"Bearer {UPSTASH_REDIS_REST_TOKEN}"}

            # Increment the counter
            incr_response = client.post(
                f"{UPSTASH_REDIS_REST_URL}/incr/{rate_key}",
                headers=headers,
            )
            incr_response.raise_for_status()
            current_count = incr_response.json().get("result", 0)

            # Set expiry if this is the first request in the window
            if current_count == 1:
                client.post(
                    f"{UPSTASH_REDIS_REST_URL}/expire/{rate_key}/{window}",
                    headers=headers,
                )

            # Check if limit exceeded
            if current_count > limit:
                # Get TTL for retry-after header
                ttl_response = client.post(
                    f"{UPSTASH_REDIS_REST_URL}/ttl/{rate_key}",
                    headers=headers,
                )
                ttl = ttl_response.json().get("result", window)
                raise RateLimitExceeded(limit=limit, window=window, retry_after=max(0, ttl))

            logger.debug(
                "Rate limit check: %s = %d/%d",
                rate_key, current_count, limit
            )
            return True

    except RateLimitExceeded:
        raise
    except Exception as e:
        # Log error but don't block the request if Redis fails
        logger.warning("Rate limit check failed (allowing request): %s", e)
        return True


def get_rate_limit_headers(
    key: str,
    identifier: str,
    limit: int,
    window: int = 60,
) -> dict:
    """
    Get rate limit headers for response.

    Returns headers like:
        X-RateLimit-Limit: 10
        X-RateLimit-Remaining: 7
        X-RateLimit-Reset: 1234567890
    """
    if not _is_configured():
        return {}

    rate_key = f"ratelimit:{key}:{identifier}"

    try:
        with httpx.Client(timeout=5.0) as client:
            headers = {"Authorization": f"Bearer {UPSTASH_REDIS_REST_TOKEN}"}

            # Get current count
            get_response = client.post(
                f"{UPSTASH_REDIS_REST_URL}/get/{rate_key}",
                headers=headers,
            )
            current = int(get_response.json().get("result") or 0)

            # Get TTL
            ttl_response = client.post(
                f"{UPSTASH_REDIS_REST_URL}/ttl/{rate_key}",
                headers=headers,
            )
            ttl = int(ttl_response.json().get("result") or window)

            import time
            reset_time = int(time.time()) + ttl

            return {
                "X-RateLimit-Limit": str(limit),
                "X-RateLimit-Remaining": str(max(0, limit - current)),
                "X-RateLimit-Reset": str(reset_time),
            }

    except Exception as e:
        logger.warning("Failed to get rate limit headers: %s", e)
        return {}

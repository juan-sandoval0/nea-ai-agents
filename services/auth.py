"""
Authentication utilities for Clerk JWT verification.

Phase 3.1: Replaces X-NEA-Key shared secret with proper JWT authentication.

Usage:
    from services.auth import USE_CLERK_AUTH, verify_clerk_token, get_user_id

    # In middleware:
    if USE_CLERK_AUTH:
        user_id = get_user_id(request)
        if not user_id:
            return JSONResponse(status_code=401, content={"detail": "Unauthorized"})
"""

import os
import logging
from functools import lru_cache
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

# Feature flag for Clerk authentication
USE_CLERK_AUTH = os.getenv("USE_CLERK_AUTH", "false").lower() == "true"

# Clerk JWKS URL for fetching public keys
CLERK_JWKS_URL = os.getenv("CLERK_JWKS_URL")


@lru_cache(maxsize=1)
def get_clerk_jwks() -> Optional[dict]:
    """
    Fetch Clerk JWKS (JSON Web Key Set) and cache it.

    Returns:
        JWKS dict or None if not configured/available.
    """
    if not CLERK_JWKS_URL:
        logger.warning("CLERK_JWKS_URL not set, Clerk auth will fail")
        return None

    try:
        response = httpx.get(CLERK_JWKS_URL, timeout=5.0)
        response.raise_for_status()
        return response.json()
    except httpx.HTTPError as e:
        logger.error(f"Failed to fetch Clerk JWKS: {e}")
        return None


def verify_clerk_token(token: str) -> Optional[dict]:
    """
    Verify a Clerk JWT and return its claims.

    Args:
        token: The JWT token string (without "Bearer " prefix)

    Returns:
        Dict of JWT claims if valid, None if invalid/expired.
    """
    try:
        import jwt
        from jwt.algorithms import RSAAlgorithm
    except ImportError:
        logger.error("PyJWT not installed. Run: pip install pyjwt[crypto]")
        return None

    jwks = get_clerk_jwks()
    if not jwks:
        return None

    try:
        # Get the key ID from the token header
        unverified_header = jwt.get_unverified_header(token)
        kid = unverified_header.get("kid")

        if not kid:
            logger.warning("JWT missing 'kid' header")
            return None

        # Find the matching key in JWKS
        key_data = None
        for key in jwks.get("keys", []):
            if key.get("kid") == kid:
                key_data = key
                break

        if not key_data:
            logger.warning(f"No matching key found for kid: {kid}")
            return None

        # Convert JWK to public key
        public_key = RSAAlgorithm.from_jwk(key_data)

        # Verify and decode the token
        claims = jwt.decode(
            token,
            public_key,
            algorithms=["RS256"],
            options={
                "verify_aud": False,  # Clerk tokens may not have aud claim
                "verify_iss": True,
            },
            # Clerk issuer format: https://<your-domain>.clerk.accounts.dev
            # We skip strict issuer check for flexibility
            issuer=None,
        )

        return claims

    except jwt.ExpiredSignatureError:
        logger.warning("JWT token expired")
        return None
    except jwt.InvalidTokenError as e:
        logger.warning(f"Invalid JWT token: {e}")
        return None
    except Exception as e:
        logger.error(f"Unexpected error verifying JWT: {e}")
        return None


def get_user_id(request) -> Optional[str]:
    """
    Extract user_id from request, supporting both Clerk and legacy auth.

    Args:
        request: FastAPI Request object

    Returns:
        Clerk user ID (sub claim) if authenticated, None otherwise.
    """
    if not USE_CLERK_AUTH:
        return None

    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        return None

    token = auth_header[7:]  # Remove "Bearer " prefix
    claims = verify_clerk_token(token)

    if claims:
        return claims.get("sub")  # Clerk user ID is in 'sub' claim

    return None


def get_user_id_from_state(request) -> Optional[str]:
    """
    Get user_id from request.state (set by middleware).

    This is the preferred method after middleware has run.

    Args:
        request: FastAPI Request object

    Returns:
        User ID if set by middleware, None otherwise.
    """
    return getattr(request.state, "user_id", None)

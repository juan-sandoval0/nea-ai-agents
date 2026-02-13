"""Supabase client for NEA AI Agents.

Provides a singleton Supabase client for database operations.
Uses the service role key for full write access from Python CLI.
"""

import os
from functools import lru_cache
from supabase import create_client, Client


class SupabaseConfigError(Exception):
    """Raised when Supabase configuration is missing."""
    pass


@lru_cache()
def get_supabase() -> Client:
    """
    Get a cached Supabase client instance.

    Requires environment variables:
    - SUPABASE_URL: Project URL (https://<project-id>.supabase.co)
    - SUPABASE_SERVICE_KEY: Service role key (for full write access)

    Returns:
        Supabase Client instance

    Raises:
        SupabaseConfigError: If required environment variables are missing
    """
    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_SERVICE_KEY")

    if not url:
        raise SupabaseConfigError(
            "SUPABASE_URL environment variable is not set. "
            "Set it to your Supabase project URL (e.g., https://<project-id>.supabase.co)"
        )

    if not key:
        raise SupabaseConfigError(
            "SUPABASE_SERVICE_KEY environment variable is not set. "
            "Set it to your Supabase service role key for full write access."
        )

    return create_client(url, key)


def clear_supabase_cache():
    """Clear the cached Supabase client (useful for testing)."""
    get_supabase.cache_clear()

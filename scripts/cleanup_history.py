#!/usr/bin/env python3
"""
History Cleanup Script
======================

Deletes records older than 30 days from all agent history tables.

Usage:
    # Run cleanup with default 30-day retention
    python scripts/cleanup_history.py

    # Run with custom retention period
    python scripts/cleanup_history.py --days 14

    # Dry run (show what would be deleted without deleting)
    python scripts/cleanup_history.py --dry-run

Cron setup (run daily at 2 AM):
    0 2 * * * cd /path/to/nea-ai-agents && python scripts/cleanup_history.py >> logs/cleanup.log 2>&1
"""

import argparse
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

# Load environment variables
try:
    from dotenv import load_dotenv
    load_dotenv(project_root / ".env")
except ImportError:
    pass


def get_record_counts() -> dict:
    """Get current record counts for all history tables."""
    from core.clients.supabase_client import get_supabase

    supabase = get_supabase()
    counts = {}

    tables = [
        ("briefing_history", "created_at"),
        ("digest_history", "generated_at"),
        ("stories", "created_at"),
        ("outreach_history", "created_at"),
        ("audit_logs", "created_at"),
    ]

    for table, _ in tables:
        try:
            result = supabase.table(table).select("id", count="exact").execute()
            counts[table] = result.count or 0
        except Exception:
            counts[table] = "N/A"

    return counts


def get_old_record_counts(keep_days: int) -> dict:
    """Get counts of records that would be deleted."""
    from core.clients.supabase_client import get_supabase

    supabase = get_supabase()
    cutoff = (datetime.now(timezone.utc) - timedelta(days=keep_days)).isoformat()
    counts = {}

    tables = [
        ("briefing_history", "created_at"),
        ("digest_history", "generated_at"),
        ("stories", "created_at"),
        ("outreach_history", "created_at"),
        ("audit_logs", "created_at"),
    ]

    for table, date_col in tables:
        try:
            result = supabase.table(table).select("id", count="exact").lt(date_col, cutoff).execute()
            counts[table] = result.count or 0
        except Exception:
            counts[table] = "N/A"

    return counts


def run_cleanup(keep_days: int = 30, dry_run: bool = False) -> dict:
    """Run the cleanup process."""
    from services.history import cleanup_all

    print(f"History Cleanup - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)
    print(f"Retention period: {keep_days} days")
    print(f"Cutoff date: {(datetime.now(timezone.utc) - timedelta(days=keep_days)).strftime('%Y-%m-%d')}")
    print()

    # Show current counts
    print("Current record counts:")
    current_counts = get_record_counts()
    for table, count in current_counts.items():
        print(f"  {table}: {count}")
    print()

    # Show what would be deleted
    print(f"Records older than {keep_days} days (to be deleted):")
    old_counts = get_old_record_counts(keep_days)
    for table, count in old_counts.items():
        print(f"  {table}: {count}")
    print()

    if dry_run:
        print("DRY RUN - No records deleted")
        return {"dry_run": True, "would_delete": old_counts}

    # Run cleanup
    print("Running cleanup...")
    results = cleanup_all(keep_days)

    print()
    print("Deleted records:")
    for table, count in results.items():
        print(f"  {table}: {count}")

    total = sum(results.values())
    print()
    print(f"Total records deleted: {total}")
    print("=" * 60)

    return results


def main():
    parser = argparse.ArgumentParser(
        description="Clean up old history records (default: 30 days retention)"
    )
    parser.add_argument(
        "--days",
        type=int,
        default=30,
        help="Number of days to keep (default: 30)"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be deleted without actually deleting"
    )

    args = parser.parse_args()

    if args.days < 1:
        print("Error: --days must be at least 1")
        sys.exit(1)

    try:
        results = run_cleanup(keep_days=args.days, dry_run=args.dry_run)
        sys.exit(0)
    except Exception as e:
        print(f"Error during cleanup: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()

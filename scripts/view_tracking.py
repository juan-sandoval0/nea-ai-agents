#!/usr/bin/env python3
"""
View engagement tracking stats.

Usage:
    python scripts/view_tracking.py           # Full stats
    python scripts/view_tracking.py --days 7  # Last 7 days
    python scripts/view_tracking.py --raw     # Raw table data
"""

import argparse
import json
from pathlib import Path
import sys

# Add parent to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from core.tracking import get_tracker


def print_stats(days: int = 30):
    """Print engagement stats."""
    tracker = get_tracker()
    stats = tracker.get_stats(days=days)

    print(f"\n{'='*60}")
    print(f"📊 ENGAGEMENT STATS (Last {days} days)")
    print('='*60)

    # Usage
    u = stats["usage"]
    print(f"\n📈 USAGE")
    print(f"   Total events:      {u['total_events']}")
    print(f"   Unique companies:  {u['unique_companies']}")
    print(f"   Unique users:      {u['unique_users']}")
    print(f"   Actions:")
    for action, count in u.get("by_action", {}).items():
        print(f"      - {action}: {count}")

    # Top companies
    print(f"\n🏢 TOP COMPANIES")
    for c in stats["top_companies"][:5]:
        print(f"   {c['company']}: {c['queries']} queries")

    # API stats
    print(f"\n🔌 API CALLS")
    for service, data in stats.get("api", {}).items():
        print(f"   {service}:")
        print(f"      Calls: {data['total_calls']}")
        print(f"      Tokens in: {data['total_tokens_in']:,}")
        print(f"      Tokens out: {data['total_tokens_out']:,}")
        print(f"      Total cost: ${data['total_cost']:.4f}")
        print(f"      Avg latency: {data['avg_latency_ms']:.0f}ms")

    print(f"\n{'='*60}\n")


def print_raw_tables():
    """Print raw tracking table data."""
    import sqlite3
    from core.tracking import DEFAULT_DB_PATH

    conn = sqlite3.connect(DEFAULT_DB_PATH)
    conn.row_factory = sqlite3.Row

    tables = ["usage_events", "api_calls"]

    for table in tables:
        print(f"\n{'='*60}")
        print(f"📊 TABLE: {table.upper()}")
        print('='*60)

        cursor = conn.execute(f"SELECT * FROM {table} ORDER BY id DESC LIMIT 20")
        rows = cursor.fetchall()

        if not rows:
            print("   (empty)")
            continue

        columns = [desc[0] for desc in cursor.description]

        for i, row in enumerate(rows, 1):
            print(f"\n  [{i}]")
            for col in columns:
                val = row[col]
                if val is not None and str(val).strip():
                    val_str = str(val)
                    if len(val_str) > 60:
                        val_str = val_str[:60] + "..."
                    print(f"      {col}: {val_str}")

    conn.close()


def main():
    parser = argparse.ArgumentParser(description="View engagement tracking")
    parser.add_argument("--days", type=int, default=30, help="Number of days to look back")
    parser.add_argument("--raw", action="store_true", help="Show raw table data")
    args = parser.parse_args()

    if args.raw:
        print_raw_tables()
    else:
        print_stats(args.days)


if __name__ == "__main__":
    main()

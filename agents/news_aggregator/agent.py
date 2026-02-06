"""
News Aggregator Agent - Portfolio Company Signal Tracker

Track ~40 companies (10 portfolio + 30 competitors) for key signals:
- Fundraising
- Key hires
- Product launches
- Acquisitions
- Partnerships

Usage:
    python -m agents.news_aggregator.agent --add "stripe.com" --name "Stripe" --category portfolio
    python -m agents.news_aggregator.agent --add "plaid.com" --name "Plaid" --category competitor
    python -m agents.news_aggregator.agent --list
    python -m agents.news_aggregator.agent --check
    python -m agents.news_aggregator.agent --signals
    python -m agents.news_aggregator.agent --signals --min-score 60
"""

import argparse
import os
import sys

from .database import (
    init_db, add_company, get_companies, get_signals,
    WatchedCompany, CompanySignal
)
from .detector import SignalDetector


def get_detector() -> SignalDetector:
    """Create detector with available clients."""
    harmonic = None
    parallel = None

    if os.getenv("HARMONIC_API_KEY"):
        from core.clients.harmonic import HarmonicClient
        try:
            harmonic = HarmonicClient()
            print("[+] Harmonic client initialized")
        except Exception as e:
            print(f"[-] Harmonic client failed: {e}")

    if os.getenv("PARALLEL_API_KEY"):
        from core.clients.parallel_search import ParallelSearchClient
        try:
            parallel = ParallelSearchClient()
            print("[+] Parallel Search client initialized")
        except Exception as e:
            print(f"[-] Parallel Search client failed: {e}")

    if not harmonic and not parallel:
        print("[!] Warning: No API clients available. Set HARMONIC_API_KEY or PARALLEL_API_KEY")

    return SignalDetector(harmonic_client=harmonic, parallel_client=parallel)


def cmd_add(domain: str, name: str, category: str):
    """Add a company to the watchlist."""
    if category not in ["portfolio", "competitor"]:
        print(f"Error: category must be 'portfolio' or 'competitor', got '{category}'")
        return

    company = add_company(
        company_id=domain,
        company_name=name,
        category=category
    )
    print(f"[+] Added {name} ({domain}) as {category}")
    print(f"    ID: {company.id}")


def cmd_list():
    """List all watched companies."""
    companies = get_companies()
    if not companies:
        print("No companies in watchlist. Use --add to add companies.")
        return

    print(f"\n{'='*60}")
    print(f"{'Company':<25} {'Domain':<20} {'Category':<12}")
    print(f"{'='*60}")

    for c in companies:
        print(f"{c.company_name:<25} {c.company_id:<20} {c.category:<12}")

    print(f"{'='*60}")
    print(f"Total: {len(companies)} companies\n")


def cmd_check():
    """Check for new signals across all companies."""
    companies = get_companies()
    if not companies:
        print("No companies to check. Use --add first.")
        return

    detector = get_detector()
    total_signals = 0
    all_errors = []

    print(f"\nChecking {len(companies)} companies for signals...\n")

    for company in companies:
        print(f"[*] Checking {company.company_name}...")
        result = detector.detect_all_signals(company)

        if result.signals:
            print(f"    Found {len(result.signals)} new signals")
            total_signals += len(result.signals)
            for signal in result.signals:
                print(f"      - [{signal.signal_type}] {signal.headline[:50]}... (score: {signal.relevance_score})")

        if result.errors:
            all_errors.extend(result.errors)
            for err in result.errors:
                print(f"    [!] {err}")

    print(f"\n{'='*60}")
    print(f"Scan complete. Found {total_signals} new signals.")
    if all_errors:
        print(f"Encountered {len(all_errors)} errors.")
    print()


def cmd_signals(min_score: int = None, signal_type: str = None, limit: int = 50):
    """Display stored signals."""
    signals = get_signals(min_score=min_score, signal_type=signal_type, limit=limit)

    if not signals:
        print("No signals found. Run --check to detect signals.")
        return

    companies = {c.id: c for c in get_companies(active_only=False)}

    print(f"\n{'='*80}")
    print(f"{'Score':<6} {'Type':<15} {'Company':<20} {'Headline':<35}")
    print(f"{'='*80}")

    for s in signals:
        company = companies.get(s.company_id)
        company_name = company.company_name if company else "Unknown"
        headline = s.headline[:33] + ".." if len(s.headline) > 35 else s.headline
        print(f"{s.relevance_score:<6} {s.signal_type:<15} {company_name:<20} {headline:<35}")

    print(f"{'='*80}")
    print(f"Showing {len(signals)} signals" + (f" (min score: {min_score})" if min_score else ""))
    print()


def cmd_import_file(filepath: str, category: str):
    """Import companies from a file (one per line: domain,name)."""
    if not os.path.exists(filepath):
        print(f"Error: File not found: {filepath}")
        return

    with open(filepath, 'r') as f:
        lines = f.readlines()

    count = 0
    for line in lines:
        line = line.strip()
        if not line or line.startswith('#'):
            continue

        parts = line.split(',')
        if len(parts) >= 2:
            domain = parts[0].strip()
            name = parts[1].strip()
        else:
            domain = parts[0].strip()
            name = domain.split('.')[0].title()

        add_company(company_id=domain, company_name=name, category=category)
        print(f"[+] Added {name} ({domain})")
        count += 1

    print(f"\nImported {count} companies as {category}")


def main():
    parser = argparse.ArgumentParser(description="News Aggregator - Track company signals")

    parser.add_argument("--add", metavar="DOMAIN", help="Add a company by domain")
    parser.add_argument("--name", help="Company name (for --add)")
    parser.add_argument("--category", choices=["portfolio", "competitor"], default="competitor",
                        help="Company category (default: competitor)")

    parser.add_argument("--import-file", metavar="FILE", help="Import companies from CSV file")

    parser.add_argument("--list", action="store_true", help="List watched companies")
    parser.add_argument("--check", action="store_true", help="Check for new signals")
    parser.add_argument("--signals", action="store_true", help="Show stored signals")

    parser.add_argument("--min-score", type=int, help="Minimum relevance score")
    parser.add_argument("--type", dest="signal_type", help="Filter by signal type")
    parser.add_argument("--limit", type=int, default=50, help="Max signals to show")

    args = parser.parse_args()

    init_db()

    if args.add:
        name = args.name or args.add.split('.')[0].title()
        cmd_add(args.add, name, args.category)
    elif args.import_file:
        cmd_import_file(args.import_file, args.category)
    elif args.list:
        cmd_list()
    elif args.check:
        cmd_check()
    elif args.signals:
        cmd_signals(min_score=args.min_score, signal_type=args.signal_type, limit=args.limit)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()

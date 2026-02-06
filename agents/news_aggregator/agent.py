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
    python -m agents.news_aggregator.agent --list
    python -m agents.news_aggregator.agent --check
    python -m agents.news_aggregator.agent --alerts   # <-- Show significant events only
"""

import argparse
import os
import re
import json
from datetime import datetime, timedelta

from .database import (
    init_db, add_company, get_companies, get_signals,
    WatchedCompany, CompanySignal
)
from .detector import SignalDetector

# Quality news sources (higher trust)
QUALITY_SOURCES = [
    'techcrunch', 'bloomberg', 'forbes', 'reuters', 'wsj', 'venturebeat',
    'theverge', 'wired', 'cnbc', 'businessinsider', 'ft.com', 'nytimes',
    'axios', 'theinformation', 'semafor', 'crunchbase', 'pitchbook'
]

# Significant signal types (worth alerting on)
SIGNIFICANT_TYPES = ['funding', 'acquisition', 'team_change']

# Noise patterns to filter out
NOISE_PATTERNS = [
    r'wikipedia\.org',
    r'list of.*companies',
    r'press release',
    r'blog\s*\|',
    r'product updates',
    r'\d+ fintech trends',
    r'unicorn.*list',
    r'best practices',
    r'how to',
    r'change management',
    r'strategic partnerships evolve',
    r'investor relations',
    r'press and news',
    r'techcrunch\.com/tag/',
    r'techcrunch\.com/startup-battlefield',
    r'news releases \|',
    r'linkedin\.com/pulse',
    r'forbes.*biggest.*companies',
    r'sana biotechnology',  # Filter out wrong Sana
    r'ir\.sana\.com',       # Sana Biotech investor relations
    r'merge labs.*bci',     # Filter out wrong Merge (brain computer interface)
    r'altman.*merge',       # Sam Altman's Merge Labs
    r'brains and computers',
]


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


def is_noise(headline: str, url: str) -> bool:
    """Check if a signal is noise based on patterns."""
    text = f"{headline} {url}".lower()
    for pattern in NOISE_PATTERNS:
        if re.search(pattern, text, re.IGNORECASE):
            return True
    return False


def is_quality_source(source: str, url: str) -> bool:
    """Check if source is from a quality outlet."""
    text = f"{source} {url}".lower()
    return any(qs in text for qs in QUALITY_SOURCES)


def extract_event_key(headline: str, company_name: str) -> str:
    """Extract a normalized key for deduplication."""
    h = headline.lower()
    h = h.replace(company_name.lower(), "").strip()

    # Extract funding amounts (e.g., $4B, $575M, $37.5M)
    amount_match = re.search(r'\$[\d.]+\s*[bmk](?:illion)?', h)
    if amount_match:
        # Normalize amount
        amt = amount_match.group().replace(' ', '').lower()
        return f"funding_{amt}"

    # Extract valuation (e.g., $134B valuation)
    val_match = re.search(r'\$[\d.]+\s*[bmk](?:illion)?\s*valuation', h)
    if val_match:
        return f"valuation_{val_match.group()[:10]}"

    # Extract acquisition targets
    acq_match = re.search(r'acqui\w*\s+(\w+)', h)
    if acq_match:
        return f"acquisition_{acq_match.group(1)}"

    # Extract "raises" pattern
    raises_match = re.search(r'raises?\s+\$?[\d.]+', h)
    if raises_match:
        return f"raises_{raises_match.group()}"

    # Series round
    series_match = re.search(r'series\s+[a-k]', h)
    if series_match:
        return f"series_{series_match.group()}"

    # Fallback: first 20 significant chars
    words = [w for w in h.split() if len(w) > 3][:3]
    return "_".join(words) if words else h[:20]


def cmd_alerts(days: int = 7, max_per_company: int = 4):
    """Show significant alerts only - filtered and deduplicated."""
    signals = get_signals(limit=500)
    companies = {c.id: c for c in get_companies(active_only=False)}

    if not signals:
        print("\nNo signals found. Run --check first.\n")
        return

    # Group by company, filter and deduplicate
    by_company = {}

    for s in signals:
        company = companies.get(s.company_id)
        if not company:
            continue

        # Skip non-significant types
        if s.signal_type not in SIGNIFICANT_TYPES:
            continue

        # Skip noise
        if is_noise(s.headline, s.source_url or ""):
            continue

        # Initialize company bucket
        if company.company_name not in by_company:
            by_company[company.company_name] = {}

        # Deduplicate by event key
        event_key = extract_event_key(s.headline, company.company_name)

        # Prefer quality sources
        is_quality = is_quality_source(s.source_name or "", s.source_url or "")

        if event_key not in by_company[company.company_name]:
            by_company[company.company_name][event_key] = (s, is_quality)
        elif is_quality and not by_company[company.company_name][event_key][1]:
            by_company[company.company_name][event_key] = (s, is_quality)

    if not by_company:
        print("\nNo significant alerts found.\n")
        return

    # Display
    total_events = 0
    print("\n" + "=" * 60)
    print("  KEY ALERTS")
    print("=" * 60)

    for company_name in sorted(by_company.keys()):
        events = by_company[company_name]
        if not events:
            continue

        print(f"\n## {company_name}")

        count = 0
        for event_key, (signal, is_quality) in events.items():
            if count >= max_per_company:
                break

            type_icon = {
                'funding': '💰',
                'acquisition': '🤝',
                'team_change': '👤',
            }.get(signal.signal_type, '📌')

            # Format date
            date_str = ""
            if signal.published_date:
                date_str = f" ({signal.published_date})"

            # Clean headline
            headline = signal.headline.strip()
            max_len = 50 - len(date_str)
            if len(headline) > max_len:
                headline = headline[:max_len-3] + "..."

            print(f"  {type_icon} {headline}{date_str}")
            if signal.source_url:
                print(f"     {signal.source_url}")

            count += 1
            total_events += 1

    print("\n" + "=" * 60)
    print(f"  {total_events} key events across {len(by_company)} companies")
    print("=" * 60 + "\n")


def main():
    parser = argparse.ArgumentParser(description="News Aggregator - Track company signals")

    parser.add_argument("--add", metavar="DOMAIN", help="Add a company by domain")
    parser.add_argument("--name", help="Company name (for --add)")
    parser.add_argument("--category", choices=["portfolio", "competitor"], default="competitor",
                        help="Company category (default: competitor)")

    parser.add_argument("--import-file", metavar="FILE", help="Import companies from CSV file")

    parser.add_argument("--list", action="store_true", help="List watched companies")
    parser.add_argument("--check", action="store_true", help="Check for new signals")
    parser.add_argument("--alerts", action="store_true", help="Show significant alerts only")
    parser.add_argument("--signals", action="store_true", help="Show all stored signals (raw)")

    parser.add_argument("--min-score", type=int, help="Minimum relevance score")
    parser.add_argument("--type", dest="signal_type", help="Filter by signal type")
    parser.add_argument("--limit", type=int, default=50, help="Max signals to show")
    parser.add_argument("--days", type=int, default=7, help="Days to look back for alerts")

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
    elif args.alerts:
        cmd_alerts(days=args.days)
    elif args.signals:
        cmd_signals(min_score=args.min_score, signal_type=args.signal_type, limit=args.limit)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()

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
from pathlib import Path

# Load environment variables from .env file
try:
    from dotenv import load_dotenv
    # Look for .env in project root
    env_path = Path(__file__).parent.parent.parent / ".env"
    load_dotenv(env_path)
except ImportError:
    pass  # dotenv not installed, rely on environment variables

from .database import (
    add_company, get_companies, get_signals,
    WatchedCompany, CompanySignal, get_portfolio_companies,
    get_competitors_for_company, remove_company, deactivate_company,
    get_or_create_default_investor, add_investor, get_investors,
    link_investor_to_company, unlink_investor_from_company,
    get_company_by_id, get_company_by_domain
)
from .detector import SignalDetector
from .investor_digest import generate_investor_digest

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
    # Generic M&A noise (not about company "Merge")
    r'mergers\s*(and|&)\s*acquisitions',
    r'm&a\s*(deals|data|news)',
    r'post-?merger',
    r'executive transitions.*m&a',
    r'navigating leadership.*merger',
    r'when firms merge',
    r'merger integration',
    r'merger.*breaking news',
    r'largest.*merger',
    r'managing.*after.*merger',
    r'partnerships.*evolve.*mergers',
    r'mnacommunity\.com',
    r'intellizence\.com.*merger',
    r'businesswire\.com/newsroom/subject/merger',
    r'spglobal\.com.*mergers-and-acquisitions',
    r'reuters\.com/legal/mergers-acquisitions',
    r'bain\.com.*merger',
    r'bluprintx\.com.*merger',
    r'insidepublicaccounting\.com.*merge',
    r'jrgpartners\.com.*merger',
    r'tworld\.com.*merger',
    r'unifyr\.com.*merger',
    r'mergeworld\.com',  # Different company named Merge
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


def cmd_add(domain: str, name: str, category: str, investor_id: str = None, parent_company_id: str = None):
    """Add a company to the watchlist."""
    if category not in ["portfolio", "competitor"]:
        print(f"Error: category must be 'portfolio' or 'competitor', got '{category}'")
        return

    # Get or create default investor if none specified
    if not investor_id:
        default_investor = get_or_create_default_investor()
        investor_id = default_investor.id

    company = add_company(
        company_id=domain,
        company_name=name,
        category=category,
        parent_company_id=parent_company_id
    )

    # Link investor to company
    link_investor_to_company(investor_id, company.id)

    print(f"[+] Added {name} ({domain}) as {category}")
    print(f"    ID: {company.id}")
    if parent_company_id:
        parent = get_company_by_id(parent_company_id)
        if parent:
            print(f"    Competitor of: {parent.company_name}")


def cmd_list(investor_id: str = None):
    """List all watched companies grouped by portfolio."""
    # Get portfolio companies first
    portfolio = get_portfolio_companies(investor_id)
    all_companies = get_companies(investor_id=investor_id)

    if not all_companies:
        print("No companies in watchlist. Use --add to add companies.")
        return

    print(f"\n{'='*70}")
    print(f"  WATCHED COMPANIES")
    print(f"{'='*70}")

    # Show portfolio companies with their competitors
    for p in portfolio:
        competitors = get_competitors_for_company(p.id)
        comp_refresh = ""
        if p.competitors_refreshed_at:
            comp_refresh = f" (competitors updated: {p.competitors_refreshed_at[:10]})"

        print(f"\n📊 {p.company_name} ({p.company_id}){comp_refresh}")

        if competitors:
            for c in competitors:
                print(f"   └── {c.company_name} ({c.company_id})")
        else:
            print(f"   └── (no competitors discovered yet)")

    # Show any orphan competitors (those without a parent)
    orphans = [c for c in all_companies if c.category == "competitor" and not c.parent_company_id]
    if orphans:
        print(f"\n📌 Unlinked Competitors:")
        for c in orphans:
            print(f"   • {c.company_name} ({c.company_id})")

    portfolio_count = len(portfolio)
    competitor_count = len([c for c in all_companies if c.category == "competitor"])
    print(f"\n{'='*70}")
    print(f"Total: {portfolio_count} portfolio + {competitor_count} competitors = {len(all_companies)} companies")
    print(f"{'='*70}\n")


def cmd_remove(domain: str, hard_delete: bool = False):
    """Remove a company from the watchlist."""
    # Find company by domain
    companies = get_companies(active_only=False)
    company = None
    for c in companies:
        if c.company_id == domain:
            company = c
            break

    if not company:
        print(f"Error: Company with domain '{domain}' not found.")
        return

    if hard_delete:
        success = remove_company(company.id, hard_delete=True)
        if success:
            print(f"[-] Permanently deleted {company.company_name} ({domain})")
        else:
            print(f"Error: Failed to delete {domain}")
    else:
        success = deactivate_company(company.id)
        if success:
            print(f"[-] Deactivated {company.company_name} ({domain})")
            print("    Use --hard-delete to permanently remove.")
        else:
            print(f"Error: Failed to deactivate {domain}")


def cmd_check(investor_id: str = None, refresh_competitors: bool = True, quiet: bool = False):
    """Check for new signals across all companies."""
    companies = get_companies(investor_id=investor_id)
    if not companies:
        if not quiet:
            print("No companies to check. Use --add first.")
        return

    detector = get_detector()
    total_signals = 0
    all_errors = []
    new_competitors = []

    # First, refresh competitors for portfolio companies if needed
    if refresh_competitors and detector.harmonic:
        portfolio = get_portfolio_companies(investor_id)
        if not quiet:
            print(f"\nChecking competitor discovery for {len(portfolio)} portfolio companies...")

        for p in portfolio:
            if p.competitors_need_refresh():
                if not quiet:
                    print(f"[*] Discovering competitors for {p.company_name}...")
                try:
                    discovered = detector.discover_competitors(p, investor_id=investor_id)
                    if discovered:
                        new_competitors.extend(discovered)
                        if not quiet:
                            for comp in discovered:
                                print(f"    [+] Found competitor: {comp.company_name} ({comp.company_id})")
                except Exception as e:
                    all_errors.append(f"Competitor discovery error for {p.company_name}: {str(e)}")

        if new_competitors:
            if not quiet:
                print(f"\n[+] Discovered {len(new_competitors)} new competitors")
            # Refresh companies list to include new competitors
            companies = get_companies(investor_id=investor_id)

    if not quiet:
        print(f"\nChecking {len(companies)} companies for signals...\n")
    else:
        print(f"Checking {len(companies)} companies for signals...", end=" ", flush=True)

    for company in companies:
        if not quiet:
            print(f"[*] Checking {company.company_name}...")
        result = detector.detect_all_signals(company)

        if result.signals:
            if not quiet:
                print(f"    Found {len(result.signals)} new signals")
                for signal in result.signals:
                    print(f"      - [{signal.signal_type}] {signal.headline[:50]}... (score: {signal.relevance_score})")
            total_signals += len(result.signals)

        if result.errors:
            all_errors.extend(result.errors)
            if not quiet:
                for err in result.errors:
                    print(f"    [!] {err}")

    if quiet:
        print(f"found {total_signals} new signals.")
    else:
        print(f"\n{'='*60}")
        print(f"Scan complete. Found {total_signals} new signals.")
        if new_competitors:
            print(f"Discovered {len(new_competitors)} new competitors.")
        if all_errors:
            print(f"Encountered {len(all_errors)} errors.")
        print()


def cmd_signals(min_score: int = None, signal_type: str = None, limit: int = 50, company_filter: str = None):
    """Display stored signals."""
    # Fetch more signals to account for noise filtering
    signals = get_signals(min_score=min_score, signal_type=signal_type, limit=limit * 3)

    if not signals:
        print("No signals found. Run --check to detect signals.")
        return

    companies = {c.id: c for c in get_companies(active_only=False)}

    # Group signals by company
    by_company = {}
    for s in signals:
        if is_noise(s.headline, s.source_url or ""):
            continue
        company = companies.get(s.company_id)
        if not company:
            continue
        # Apply company filter if specified
        if company_filter and company_filter.lower() not in company.company_name.lower():
            continue
        if company.company_name not in by_company:
            by_company[company.company_name] = {'category': company.category, 'signals': []}
        by_company[company.company_name]['signals'].append(s)

    if not by_company:
        print(f"No signals found" + (f" for '{company_filter}'" if company_filter else "") + ".")
        return

    print(f"\n{'='*90}")
    print(f"  NEWS AGGREGATOR - SIGNALS")
    print(f"{'='*90}")

    total_shown = 0
    # Sort: portfolio first, then alphabetically
    for company_name in sorted(by_company.keys(), key=lambda x: (by_company[x]['category'] != 'portfolio', x)):
        data = by_company[company_name]
        category = data['category']
        company_signals = data['signals']

        # Limit per company
        max_per_company = limit // len(by_company) + 5 if not company_filter else limit
        company_signals = company_signals[:max_per_company]

        icon = '📊' if category == 'portfolio' else '📌'
        print(f"\n{icon} {company_name.upper()} ({category})")
        print("-" * 70)

        for s in company_signals:
            if total_shown >= limit:
                break

            # Signal type with icon
            type_label = {
                'funding': '💰 Funding',
                'acquisition': '🤝 Acquisition',
                'product_launch': '🚀 Product Launch',
                'executive_change': '👤 Executive Change',
                'news_coverage': '📰 News',
                'partnership': '🔗 Partnership',
                'hiring_expansion': '👥 Hiring'
            }.get(s.signal_type, '📌 Signal')

            # Sentiment with icon
            sentiment_label = {
                'positive': '📈 POSITIVE',
                'negative': '📉 NEGATIVE',
                'neutral': '➖ NEUTRAL'
            }.get(s.sentiment or 'neutral', '➖ NEUTRAL')

            headline = s.headline[:75] + "..." if len(s.headline) > 75 else s.headline
            date = s.published_date or "N/A"
            source = s.source_name or "Unknown"

            print(f"\n  {type_label} | {sentiment_label}")
            print(f"  {headline}")
            print(f"  📅 {date} | 🔗 {source}")
            if s.source_url:
                print(f"  → {s.source_url}")

            total_shown += 1

        if total_shown >= limit:
            break

    print(f"\n{'='*90}")
    print(f"Showing {total_shown} signals across {len(by_company)} companies")
    print(f"{'='*90}\n")


def cmd_import_file(filepath: str, category: str, investor_id: str = None):
    """Import companies from a file (one per line: domain,name)."""
    if not os.path.exists(filepath):
        print(f"Error: File not found: {filepath}")
        return

    # Get or create default investor if none specified
    if not investor_id:
        default_investor = get_or_create_default_investor()
        investor_id = default_investor.id

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

        company = add_company(company_id=domain, company_name=name, category=category)
        link_investor_to_company(investor_id, company.id)
        print(f"[+] Added {name} ({domain})")
        count += 1

    print(f"\nImported {count} companies as {category}")


def cmd_investors(action: str = "list", name: str = None, email: str = None):
    """Manage investors."""
    if action == "list":
        investors = get_investors()
        if not investors:
            print("No investors found. Use --investors add --investor-name 'Name' to add one.")
            return

        print(f"\n{'='*50}")
        print(f"{'Name':<25} {'Email':<25}")
        print(f"{'='*50}")

        for inv in investors:
            email_str = inv.email or "-"
            print(f"{inv.name:<25} {email_str:<25}")

        print(f"{'='*50}")
        print(f"Total: {len(investors)} investors\n")

    elif action == "add":
        if not name:
            print("Error: --investor-name required")
            return

        investor = add_investor(name=name, email=email)
        print(f"[+] Created investor: {investor.name}")
        print(f"    ID: {investor.id}")

    else:
        print(f"Error: Unknown action '{action}'. Use 'list' or 'add'.")


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

    # Build parent company lookup for competitors
    parent_names = {}
    for c in companies.values():
        if c.category == "competitor" and c.parent_company_id:
            parent = companies.get(c.parent_company_id)
            if parent:
                parent_names[c.id] = parent.company_name

    # Calculate cutoff date
    cutoff_date = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")

    # Group by company, filter and deduplicate
    # Key is (company_name, parent_name or None) to keep display info
    by_company = {}

    for s in signals:
        company = companies.get(s.company_id)
        if not company:
            continue

        # Skip old news
        if s.published_date and s.published_date < cutoff_date:
            continue

        # Skip non-significant types
        if s.signal_type not in SIGNIFICANT_TYPES:
            continue

        # Skip noise
        if is_noise(s.headline, s.source_url or ""):
            continue

        # Create display key with parent info
        parent_name = parent_names.get(company.id)
        display_key = (company.company_name, parent_name)

        # Initialize company bucket
        if display_key not in by_company:
            by_company[display_key] = {}

        # Deduplicate by event key
        event_key = extract_event_key(s.headline, company.company_name)

        # Prefer quality sources
        is_quality = is_quality_source(s.source_name or "", s.source_url or "")

        if event_key not in by_company[display_key]:
            by_company[display_key][event_key] = (s, is_quality)
        elif is_quality and not by_company[display_key][event_key][1]:
            by_company[display_key][event_key] = (s, is_quality)

    if not by_company:
        print("\nNo significant alerts found.\n")
        return

    # Display
    total_events = 0
    print("\n" + "=" * 60)
    print(f"  KEY ALERTS (last {days} days)")
    print("=" * 60)

    # Sort by company name, with portfolio companies first
    sorted_keys = sorted(by_company.keys(), key=lambda x: (x[1] is not None, x[0]))

    for display_key in sorted_keys:
        events = by_company[display_key]
        if not events:
            continue

        company_name, parent_name = display_key
        if parent_name:
            print(f"\n## {company_name}  ← competitor of {parent_name}")
        else:
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


def cmd_refresh_industries(investor_id: str = None):
    """Refresh industry tags for all companies from Harmonic API."""
    companies = get_companies(investor_id=investor_id)
    if not companies:
        print("No companies to refresh. Use --add first.")
        return

    detector = get_detector()
    if not detector.harmonic:
        print("Error: Harmonic API client not available. Set HARMONIC_API_KEY.")
        return

    print(f"\nRefreshing industry tags for {len(companies)} companies...\n")

    updated = 0
    for company in companies:
        print(f"[*] {company.company_name}...", end=" ")
        try:
            tags = detector.refresh_industry_tags(company)
            if tags:
                print(f"✓ {', '.join(tags[:3])}" + ("..." if len(tags) > 3 else ""))
                updated += 1
            else:
                print("(no tags found)")
        except Exception as e:
            print(f"✗ {e}")

    print(f"\n{'='*60}")
    print(f"Updated industry tags for {updated}/{len(companies)} companies")
    print(f"{'='*60}\n")


def main():
    parser = argparse.ArgumentParser(
        description="News Aggregator - Track company signals",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Add a portfolio company
  python -m agents.news_aggregator.agent --add stripe.com --name Stripe --category portfolio

  # List all companies with competitors
  python -m agents.news_aggregator.agent --list

  # Check for signals (auto-discovers competitors)
  python -m agents.news_aggregator.agent --check

  # Show significant alerts from last 7 days
  python -m agents.news_aggregator.agent --alerts

  # Remove a company
  python -m agents.news_aggregator.agent --remove stripe.com

  # Manage investors
  python -m agents.news_aggregator.agent --investors list
  python -m agents.news_aggregator.agent --investors add --investor-name "John Doe"
"""
    )

    # Company management
    parser.add_argument("--add", metavar="DOMAIN", help="Add a company by domain")
    parser.add_argument("--name", help="Company name (for --add)")
    parser.add_argument("--category", choices=["portfolio", "competitor"], default="portfolio",
                        help="Company category (default: portfolio)")
    parser.add_argument("--remove", metavar="DOMAIN", help="Remove a company by domain")
    parser.add_argument("--hard-delete", action="store_true", help="Permanently delete (with --remove)")

    # Import
    parser.add_argument("--import-file", metavar="FILE", help="Import companies from CSV file")

    # Listing and checking
    parser.add_argument("--list", action="store_true", help="List watched companies with competitors")
    parser.add_argument("--check", action="store_true", help="Check for new signals (auto-discovers competitors)")
    parser.add_argument("--no-competitor-refresh", action="store_true",
                        help="Skip competitor discovery during --check")
    parser.add_argument("--alerts", action="store_true", help="Show significant alerts only (deprecated: use --digest)")
    parser.add_argument("--signals", action="store_true", help="Show all stored signals (deprecated: use --digest)")
    parser.add_argument("--digest", action="store_true",
                        help="Generate unified investor digest (auto-fetches new signals)")
    parser.add_argument("--no-fetch", action="store_true",
                        help="Skip fetching new signals (use cached data only)")
    parser.add_argument("--min-priority", type=float, default=40.0,
                        help="Minimum priority score for digest (default: 40)")
    parser.add_argument("--industry", metavar="TAG",
                        help="Filter by industry tag (e.g., fintech, ai_ml, healthcare)")
    parser.add_argument("--refresh-industries", action="store_true",
                        help="Refresh industry tags for all companies from Harmonic API")

    # Investor management
    parser.add_argument("--investors", nargs="?", const="list", metavar="ACTION",
                        help="Manage investors: 'list' (default) or 'add'")
    parser.add_argument("--investor-name", help="Investor name (for --investors add)")
    parser.add_argument("--investor-email", help="Investor email (for --investors add)")
    parser.add_argument("--investor-id", help="Filter by investor ID (for --list, --check, --alerts)")

    # Filtering options
    parser.add_argument("--min-score", type=int, help="Minimum relevance score")
    parser.add_argument("--type", dest="signal_type", help="Filter by signal type")
    parser.add_argument("--company", help="Filter signals by company name (e.g., --company Databricks)")
    parser.add_argument("--limit", type=int, default=50, help="Max signals to show")
    parser.add_argument("--days", type=int, default=7, help="Days to look back for alerts")

    args = parser.parse_args()

    if args.add:
        name = args.name or args.add.split('.')[0].title()
        cmd_add(args.add, name, args.category, investor_id=args.investor_id)
    elif args.remove:
        cmd_remove(args.remove, hard_delete=args.hard_delete)
    elif args.import_file:
        cmd_import_file(args.import_file, args.category, investor_id=args.investor_id)
    elif args.investors:
        cmd_investors(args.investors, name=args.investor_name, email=args.investor_email)
    elif args.list:
        cmd_list(investor_id=args.investor_id)
    elif args.check:
        cmd_check(investor_id=args.investor_id, refresh_competitors=not args.no_competitor_refresh)
    elif args.alerts:
        cmd_alerts(days=args.days)
    elif args.signals:
        cmd_signals(min_score=args.min_score, signal_type=args.signal_type, limit=args.limit, company_filter=args.company)
    elif args.digest:
        # Track job in Supabase for Lovable UI
        from services.job_manager import get_job_manager
        job_manager = get_job_manager()
        job = job_manager.create_job("news_aggregator", triggered_by="terminal")

        try:
            job_manager.start_job(job.id)
            print(f"Job {job.id[:8]}... started\n")

            # Auto-fetch new signals unless --no-fetch is specified
            if not args.no_fetch:
                print("Fetching latest signals...\n")
                cmd_check(investor_id=args.investor_id, refresh_competitors=False, quiet=True)
                print("")

            digest = generate_investor_digest(
                days=args.days,
                min_priority_score=args.min_priority,
                investor_id=args.investor_id,
                industry_filter=args.industry
            )
            print(digest.to_markdown())

            # Mark job complete
            story_count = len(digest.stories) if hasattr(digest, 'stories') else 0
            job_manager.complete_job(job.id, {"story_count": story_count, "days": args.days})
            print(f"\n✓ Job completed")

        except Exception as e:
            job_manager.fail_job(job.id, str(e))
            print(f"\n✗ Job failed: {e}")
            raise
    elif args.refresh_industries:
        cmd_refresh_industries(investor_id=args.investor_id)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()

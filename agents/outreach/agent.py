"""
Outreach Agent - Personalized Cold Outreach for VC Investors
=============================================================

Generates personalized cold outreach messages (email or LinkedIn) to founders
at target companies, using existing data infrastructure.

Usage:
    # Generate email
    python -m agents.outreach.agent --company stripe.com --format email

    # Generate LinkedIn message
    python -m agents.outreach.agent --company stripe.com --format linkedin

    # Target specific contact
    python -m agents.outreach.agent --company stripe.com --format email --contact "Patrick Collison"

    # Override investor identity
    python -m agents.outreach.agent --company stripe.com --format email \\
        --investor-name "Jane Smith" --firm-name "NEA"

    # Use cached data (skip re-ingestion)
    python -m agents.outreach.agent --company stripe.com --format email --skip-ingest

    # Preview data without generating
    python -m agents.outreach.agent --company stripe.com --preview

    # Save to file
    python -m agents.outreach.agent --company stripe.com --format email -o message.txt
"""

import argparse
import logging
from pathlib import Path

# Load environment variables from .env file
try:
    from dotenv import load_dotenv
    env_path = Path(__file__).parent.parent.parent / ".env"
    load_dotenv(env_path)
except ImportError:
    pass

from tools.company_tools import ingest_company, get_company_bundle, normalize_company_id
from .generator import generate_outreach, select_contact, format_company_context, format_contact_context


def cmd_preview(args):
    """Preview available data and selected contact without generating a message."""
    company_id = normalize_company_id(args.company)

    print(f"Previewing data for: {company_id}")
    print("=" * 60)

    # Ingest unless skipped
    if not args.skip_ingest:
        print("Ingesting company data...")
        ingest_result = ingest_company(company_id)
        print(f"  Ingestion complete: {ingest_result.get('company_name', company_id)}")
        print()

    # Get bundle
    bundle = get_company_bundle(company_id)

    if not bundle.company_core:
        print("ERROR: Company not found in database. Run without --skip-ingest.")
        return

    # Company info
    print(f"Company: {bundle.company_core.company_name}")
    print(f"  HQ: {bundle.company_core.hq or 'N/A'}")
    print(f"  Employees: {bundle.company_core.employee_count or 'N/A'}")
    if bundle.company_core.total_funding:
        print(f"  Total Funding: ${bundle.company_core.total_funding:,.0f}")
    print(f"  Products: {bundle.company_core.products or 'N/A'}")
    print()

    # Founders
    print(f"Founders ({len(bundle.founders)}):")
    if bundle.founders:
        for f in bundle.founders:
            title = f.role_title or "N/A"
            linkedin = f" | {f.linkedin_url}" if f.linkedin_url else ""
            bg = " | Has background" if f.background else " | No background"
            print(f"  - {f.name} ({title}){linkedin}{bg}")
    else:
        print("  None found")
    print()

    # Contact selection
    contact = select_contact(bundle.founders, preferred_name=args.contact)
    if contact:
        print(f"Selected Contact: {contact.name} ({contact.role_title or 'N/A'})")
        if contact.linkedin_url:
            print(f"  LinkedIn: {contact.linkedin_url}")
    else:
        print("Selected Contact: None (no founders available)")
    print()

    # Signals
    print(f"Key Signals ({len(bundle.key_signals)}):")
    for s in bundle.key_signals[:5]:
        print(f"  - [{s.signal_type.upper()}] {s.description}")
    if len(bundle.key_signals) > 5:
        print(f"  ... and {len(bundle.key_signals) - 5} more")
    print()

    # News
    print(f"News Articles ({len(bundle.news)}):")
    for n in bundle.news[:5]:
        outlet = f" ({n.outlet})" if n.outlet else ""
        print(f"  - {n.article_headline}{outlet}")
    if len(bundle.news) > 5:
        print(f"  ... and {len(bundle.news) - 5} more")


def cmd_generate(args):
    """Generate an outreach message."""
    print(f"Generating {args.format} outreach for: {args.company}")
    print("-" * 60)

    # Resolve samples_file: --no-samples → "" (disabled), --samples PATH → path, else None (auto)
    samples_file = None
    if args.no_samples:
        samples_file = ""
    elif args.samples:
        samples_file = args.samples

    result = generate_outreach(
        company_id=args.company,
        output_format=args.format,
        contact_name=args.contact,
        investor_name=args.investor_name,
        firm_name=args.firm_name,
        skip_ingest=args.skip_ingest,
        samples_file=samples_file,
    )

    if result["success"]:
        # Build output
        output_lines = []

        output_lines.append(f"Company: {result['company_name']}")
        if result["contact_name"]:
            contact_info = result["contact_name"]
            if result["contact_title"]:
                contact_info += f" ({result['contact_title']})"
            output_lines.append(f"Contact: {contact_info}")
        if result["contact_linkedin"]:
            output_lines.append(f"LinkedIn: {result['contact_linkedin']}")
        output_lines.append(f"Format: {result['output_format']}")
        output_lines.append("")
        output_lines.append("=" * 60)

        if result["subject"]:
            output_lines.append(f"Subject: {result['subject']}")
            output_lines.append("")

        output_lines.append(result["message"])
        output_lines.append("=" * 60)
        output_lines.append(f"Data sources: {result['data_sources']}")

        output_text = "\n".join(output_lines)

        if args.output:
            with open(args.output, "w") as f:
                # Write just the message content to file
                if result["subject"]:
                    f.write(f"Subject: {result['subject']}\n\n")
                f.write(result["message"])
            print(f"Message saved to: {args.output}")
            print()
            print(output_text)
        else:
            print(output_text)
    else:
        print(f"ERROR: {result['error']}")
        if "not found in database" in (result.get("error") or ""):
            print(f"\nRun without --skip-ingest to fetch data first.")


def main():
    """CLI entry point for the outreach agent."""
    parser = argparse.ArgumentParser(
        description="Generate personalized cold outreach messages for VC investors",
        epilog="""
Examples:
  %(prog)s --company stripe.com --format email
  %(prog)s --company stripe.com --format linkedin --contact "Patrick Collison"
  %(prog)s --company stripe.com --preview
  %(prog)s --company stripe.com --format email --investor-name "Jane Smith" --firm-name "NEA"
  %(prog)s --company stripe.com --format email --skip-ingest -o message.txt
        """,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    parser.add_argument(
        "--company",
        required=True,
        help="Company URL or domain (e.g., stripe.com)",
    )
    parser.add_argument(
        "--format",
        choices=["email", "linkedin"],
        default="email",
        help="Output format: email or linkedin (default: email)",
    )
    parser.add_argument(
        "--contact",
        default=None,
        help="Target contact name (default: auto-select best match)",
    )
    parser.add_argument(
        "--investor-name",
        default=None,
        help="Investor name for the message",
    )
    parser.add_argument(
        "--firm-name",
        default=None,
        help="Firm name for the message",
    )
    parser.add_argument(
        "--skip-ingest",
        action="store_true",
        help="Use cached DB data only (skip API re-ingestion)",
    )
    parser.add_argument(
        "--samples",
        default=None,
        help="Path to style samples file (default: auto-detect from docs/)",
    )
    parser.add_argument(
        "--no-samples",
        action="store_true",
        help="Disable style examples (use generic tone)",
    )
    parser.add_argument(
        "--preview",
        action="store_true",
        help="Preview available data and contact selection without generating",
    )
    parser.add_argument(
        "-o", "--output",
        default=None,
        help="Save output to file",
    )

    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO)

    if args.preview:
        cmd_preview(args)
    else:
        cmd_generate(args)


if __name__ == "__main__":
    main()

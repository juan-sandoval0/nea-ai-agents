"""Load and select NEA portfolio companies from the Harmonic export CSV."""
from __future__ import annotations

import csv
import sys
from dataclasses import dataclass
from pathlib import Path


@dataclass
class PortCo:
    name: str
    harmonic_id: str
    domain: str
    stage: str
    headcount: str


def load_portcos(csv_path: str | Path) -> list[PortCo]:
    companies = []
    with open(csv_path, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            name = row.get("Company Name", "").strip()
            harmonic_id = row.get("Company ID", "").strip()
            if not name or not harmonic_id:
                continue
            # Extract bare domain from Website URL
            domain = row.get("Website URL", "").strip()
            for prefix in ("https://", "http://", "www."):
                domain = domain.removeprefix(prefix)
            domain = domain.rstrip("/")
            companies.append(PortCo(
                name=name,
                harmonic_id=harmonic_id,
                domain=domain,
                stage=row.get("Stage", "").strip(),
                headcount=row.get("Headcount", "").strip(),
            ))
    return sorted(companies, key=lambda c: c.name.lower())


def pick_company(companies: list[PortCo]) -> PortCo:
    """Interactive picker: show numbered list, return selected company."""
    print("\nNEA Active Portfolio Companies\n")
    for i, co in enumerate(companies, 1):
        stage = co.stage.replace("_", " ").title() if co.stage else "Unknown"
        try:
            hc = f"{int(float(co.headcount)):,}" if co.headcount else "?"
        except ValueError:
            hc = "?"
        print(f"  [{i:>3}] {co.name:<35} {stage:<20} {hc} employees")

    print()
    while True:
        raw = input("Search company name (or enter number): ").strip()
        if raw.isdigit() and 1 <= int(raw) <= len(companies):
            return companies[int(raw) - 1]
        if raw:
            matches = [c for c in companies if raw.lower() in c.name.lower()]
            if len(matches) == 1:
                return matches[0]
            if matches:
                print("  Multiple matches:")
                for c in matches[:10]:
                    print(f"    {c.name}")
                print("  Be more specific.")
            else:
                print("  No match found. Try again.")

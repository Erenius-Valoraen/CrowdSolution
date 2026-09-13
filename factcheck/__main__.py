"""Terminal interface.

  python -m factcheck "unemployment is 4.1%" --said-on 2025-01-15
  python -m factcheck                 (interactive: type claims one at a time)
  python -m factcheck --list          (supported statistics)
"""
from __future__ import annotations

import argparse
import sys
from datetime import date

from . import db, parse_groq
from .catalog import Catalog
from .engine import Result, check
from .formatting import fmt
from .parse import parse_claims


def show(res: Result) -> None:
    c, m = res.claim, res.metric
    print(f'\nClaim:    "{c.text}"  (said {c.said_on})')
    summary = ""
    if m and c.value is not None:
        period = f", {c.period.label()}" if c.period else ""
        where = f", {c.state or c.city}" if (c.state or c.city) else ""
        summary = f"  ->  {m.label}{where}, {res.measure or c.measure}, {c.comparator} {c.value:,.6g}{period}"
    print(f"Parsed:   by {c.parser}{summary}")
    if m and res.series:
        print(f"Source:   {m.agency} [{res.series}], {res.where}")
    rows = [("Known when said", res.then), ("Same period today", res.revised),
            ("Latest available", res.latest), ("Today's data", res.fallback)]
    for name, fig in rows:
        if fig is not None and m is not None and res.measure:
            pub = f"published {fig.published}" if fig.published else ""
            part = "  (partial)" if not fig.complete else ""
            print(f"  {name:18} {fmt(m, res.measure, fig.value):30} {fig.label:24} {pub}{part}")
    print(f"Verdict:  {res.verdict}")
    for n in res.notes:
        print(f"  - {n}")


def run_one(text: str, said_on: date, catalog: Catalog, backend: str) -> None:
    try:
        claims, notes = parse_claims(text, said_on, catalog, backend)
    except parse_groq.GroqError as e:
        print(f"Groq error: {e}")
        return
    for n in notes:
        print(f"  note: {n}")
    for claim in claims:
        show(check(claim, catalog))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="python -m factcheck", description="Was a statistic true when it was said?")
    ap.add_argument("claim", nargs="?", help="the claim text; omit for interactive mode")
    ap.add_argument("--said-on", type=date.fromisoformat, default=date.today(), help="YYYY-MM-DD, default today")
    ap.add_argument("--parser", choices=["auto", "rules", "groq"], default="auto",
                    help="auto uses Groq when GROQ_API_KEY is set, otherwise rules")
    ap.add_argument("--list", action="store_true", help="list supported statistics and exit")
    args = ap.parse_args(argv)

    catalog = Catalog()
    if args.list:
        print(catalog.describe())
        print(f"\nCities with crime data: {', '.join(catalog.cities)}")
        return 0

    using_groq = parse_groq.available() and args.parser != "rules"
    print(f"Parser: {'Groq' if using_groq else 'rule-based'}    Data through: {catalog.data_end}")
    try:
        if args.claim:
            run_one(args.claim, args.said_on, catalog, args.parser)
            return 0
        print("Type a claim, then the date it was said. Press Enter on an empty claim to quit.")
        while True:
            text = input("\nClaim> ").strip()
            if not text:
                return 0
            raw = input("Said on (YYYY-MM-DD, blank = today)> ").strip()
            try:
                said_on = date.fromisoformat(raw) if raw else date.today()
            except ValueError:
                print("Couldn't read that date; use YYYY-MM-DD.")
                continue
            run_one(text, said_on, catalog, args.parser)
    except (KeyboardInterrupt, EOFError):
        print()
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())

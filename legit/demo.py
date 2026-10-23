"""Interactive checker: paste or type anything, press Enter, and see what holds up.

  python -m legit
"""
from __future__ import annotations

import argparse
import os
import sys
import time
from datetime import date

from rich import box
from rich.console import Console, Group
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from . import db, router
from .models import SEVERITY, Finding, Report

STATUS = {
    "red_flag": ("RED FLAG", "bold white on red3", "red3"),
    "caution": ("CAUTION", "bold black on yellow3", "yellow3"),
    "unverified": ("UNCONFIRMED", "bold white on grey42", "grey62"),
    "info": ("CONTEXT", "bold white on dodger_blue3", "dodger_blue2"),
    "ok": ("CHECKS OUT", "bold white on green4", "green3"),
}
OVERALL = {"HIGH RISK": "red3", "BE CAREFUL": "yellow3", "NO RED FLAGS FOUND": "green3",
           "COULDN'T VERIFY": "grey62", "NOTHING TO CHECK": "grey62"}
OVERALL_WORDS = {
    "HIGH RISK": "High risk. Don't send money or personal details yet.",
    "BE CAREFUL": "Some of this doesn't hold up. Look closer before you trust it.",
    "NO RED FLAGS FOUND": "Nothing we checked raised a red flag.",
    "COULDN'T VERIFY": "We couldn't confirm any of this either way.",
    "NOTHING TO CHECK": "We didn't find any facts, numbers, or offers to check in this text.",
}
DOMAIN_RESULTS = {
    "official": ("green3", "is one of its official domains"),
    "free_email": ("red3", "is a free personal email, not the organization's own domain"),
    "lookalike": ("red3", "imitates the name but is not an official domain"),
    "lookalike_unknown": ("yellow3", "contains the name, but we can't confirm who owns it"),
    "brand_match": ("yellow3", "matches the name but isn't in our records (probably official; type it yourself)"),
    "unrelated": ("yellow3", "has no visible connection to this organization"),
    "owned_by_other": ("yellow3", "belongs to a different company"),
}


def badge(status: str) -> Text:
    label, style, _ = STATUS[status]
    return Text(f" {label} ", style=style)


def color(status: str) -> str:
    return STATUS[status][2]


def worst(findings: list[Finding]) -> Finding:
    return max(findings, key=lambda f: SEVERITY[f.status])


def section(console: Console, title: str, subtitle: str) -> None:
    console.print()
    console.rule(Text(title, style="bold"), style="grey50")
    console.print(Text(subtitle, style="dim"), justify="center")


def money(v: float | None, unit: str = "usd") -> str:
    if v is None:
        return "-"
    if unit == "percent":
        return f"{v:.2f}%"
    if unit == "usd_hour":
        return f"${v:,.2f}/hr"
    if unit == "usd_month":
        return f"${v:,.0f}/mo"
    return f"${v:,.0f}"


def pct(v: float | None) -> str:
    return "-" if v is None else f"{v * 100:.0f}%"


def main_domains(domains: list[str], limit: int = 3) -> list[str]:
    """Plain .com/.org/.edu domains first; country subsidiaries like jpmorganchina.com.cn only if nothing else exists."""
    plain = [d for d in domains if d.count(".") == 1]
    return (plain or domains)[:limit]


# --- Sections ---

def header(console: Console, report: Report) -> None:
    tone = OVERALL.get(report.overall, "grey62")
    counts = Text()
    for s in ("red_flag", "caution", "ok", "info", "unverified"):
        if report.count(s):
            counts.append_text(badge(s))
            counts.append(f" {report.count(s)}   ")
    parts = [Text(report.overall, style=f"bold {tone}", justify="center"),
             Text(OVERALL_WORDS.get(report.overall, ""), style=tone, justify="center")]
    if len(counts):
        parts += [Text(""), counts]
    if report.extraction.summary:
        parts += [Text(""), Text(report.extraction.summary, style="italic")]
    console.print(Panel(Group(*parts), border_style=tone, padding=(1, 2)))


def community(console: Console, fs: list[Finding]) -> None:
    if not fs:
        return
    section(console, "Reported by other students", "Scams other students checked here before, remembered with Backboard")
    for f in fs:
        d = f.data
        grid = Table.grid(padding=(0, 2))
        grid.add_column(style="bold", no_wrap=True)
        grid.add_column()
        if d.get("matched"):
            grid.add_row("Matched", Text(", ".join(m["value"] for m in d["matched"]), style=f"bold {color(f.status)}"))
        reports = d.get("reports") or 1
        seen = Text(f"{reports} report{'s' if reports != 1 else ''}")
        if d.get("first_seen"):
            seen.append(f"  |  first {d['first_seen']}  |  last {d.get('last_seen') or d['first_seen']}", style="dim")
        grid.add_row("Reported", seen)
        if d.get("summary"):
            grid.add_row("That report", Text(d["summary"]))
        if d.get("red_flags"):
            grid.add_row("Red flags then", Text("; ".join(d["red_flags"][:4])))
        grid.add_row("", Text(""))
        grid.add_row("Bottom line", Text(f.summary.split(" Red flags in that report")[0]))
        title = Text(f" {f.title} ", style="bold")
        title.append_text(badge(f.status))
        console.print(Panel(grid, title=title, title_align="left", border_style=color(f.status), padding=(1, 2)))


def warning_signs(console: Console, fs: list[Finding]) -> None:
    if not fs:
        return
    section(console, "Warning signs", "Tactics that scammers commonly use, as described by consumer protection agencies")
    t = Table(box=box.SIMPLE_HEAVY, expand=True, show_lines=True)
    t.add_column("", no_wrap=True)
    t.add_column("Sign", style="bold", ratio=2)
    t.add_column("What it said", ratio=3)
    t.add_column("Why it matters", ratio=4)
    t.add_column("Learn more", ratio=2)
    for f in sorted(fs, key=lambda f: -SEVERITY[f.status]):
        ref = f.evidence[0] if f.evidence else None
        guidance = Text(ref.source, style=f"link {ref.url} underline") if ref and ref.url else Text("")
        t.add_row(badge(f.status), Text(f.title), Text(f'"{f.item.text}"', style="italic"),
                  Text(f.data.get("explanation") or f.summary), guidance)
    console.print(t)


def organizations(console: Console, fs: list[Finding]) -> None:
    if not fs:
        return
    section(console, "Who's behind it", "Official registries, website checks, and complaint records")
    groups: dict[int, list[Finding]] = {}
    for f in fs:
        groups.setdefault(f.item.id, []).append(f)
    for group in groups.values():
        name = group[0].item.data.get("name") or group[0].item.text
        grid = Table.grid(padding=(0, 2))
        grid.add_column(style="bold", no_wrap=True)
        grid.add_column()
        for f in group:
            d = f.data
            kind = d.get("type")
            if kind in ("bank", "company", "adviser", "charity"):
                if kind == "bank":
                    reg = (f"{d['registered_name']}  |  {d.get('entity_type')}  |  FDIC #{d.get('fdic_cert') or '-'}  |  "
                           f"{'active' if d.get('active') else 'no longer active'}")
                elif kind == "adviser":
                    reg = f"{d['registered_name']}  |  SEC registration: {d.get('status')}"
                elif kind == "charity":
                    reg = f"{d['registered_name']}  |  EIN {d.get('ein')}  |  latest filing {d.get('tax_year')}"
                else:
                    reg = d.get("registered_name") or "No matching company on record"
                grid.add_row("Registered as", Text(reg))
                if d.get("official_domains"):
                    grid.add_row("Official websites", Text(", ".join(main_domains(d["official_domains"]))))
                if d.get("claimed_domain") and d.get("domain_result") in DOMAIN_RESULTS:
                    style, words = DOMAIN_RESULTS[d["domain_result"]]
                    grid.add_row("This message uses", Text(f"{d['claimed_domain']}  ", style=f"bold {style}").append(words, style=style))
            elif kind == "complaints":
                timely_style = "green3" if d["timely_pct"] >= 90 else "red3"
                line = Text(f"{d['complaints']:,} consumer complaints in a year  |  ")
                line.append(f"{d['timely_pct']}% answered on time", style=timely_style)
                line.append(f"  |  most common: {d['top_issue']}")
                grid.add_row("Complaints", line)
            elif f.checker == "web":
                grid.add_row("Online", Text(f.summary))
                for s in d.get("sources", [])[:3]:
                    grid.add_row("", Text(s["title"], style=f"link {s['url']} underline dim"))
        top = worst(group)
        grid.add_row("", Text(""))
        bottom = top.summary.split(". ")[-1] if top.checker == "registry" and top.status != "ok" else top.summary
        grid.add_row("Bottom line", Text(bottom))
        title = Text(f" {name} ", style="bold")
        title.append_text(badge(top.status))
        console.print(Panel(grid, title=title, title_align="left", border_style=color(top.status), padding=(1, 2)))


def bar_rows(rows: list[tuple[str, float, str, str]]) -> Table:
    grid = Table.grid(padding=(0, 2))
    grid.add_column(no_wrap=True)
    grid.add_column(no_wrap=True)
    grid.add_column(justify="right", no_wrap=True)
    top = max(v for _, v, _, _ in rows) or 1
    for label, value, style, shown in rows:
        grid.add_row(Text(label), Text("█" * max(1, round(36 * value / top)), style=style), Text(shown, style="bold"))
    return grid


def prices(console: Console, fs: list[Finding]) -> None:
    if not fs:
        return
    section(console, "Is the price normal?", "Compared with what's typical, from official data")
    titles = {"rent": "Rent", "wage": "Pay", "savings_rate": "Savings rate", "loan_rate": "Loan rate",
              "credit_card_rate": "Credit card rate", "rent_trend": "Rent"}
    for f in fs:
        d = f.data
        kind = d.get("type")
        if kind in ("rent", "wage", "savings_rate", "loan_rate", "credit_card_rate"):
            unit = d["unit"]
            listed = "This listing" if kind == "rent" else "This offer"
            body = Group(
                bar_rows([(listed, d["amount"], color(f.status), money(d["amount"], unit)),
                          (d["benchmark_label"], d["benchmark"], "grey62", money(d["benchmark"], unit))]),
                Text(""),
                Text(f.summary),
            )
        elif kind == "rent_trend":
            body = Group(Text(f"Rents in {d['province']}: {d['change_pct']:+.1f}% vs a year earlier ({d['month']})", style="bold"),
                         Text(""), Text(f.summary.split(". Our data")[0] + "."))
        else:
            body = Group(Text(f.summary), *[Text(s["title"], style=f"link {s['url']} underline dim")
                                            for s in d.get("sources", [])[:3]])
        title = Text(f" {titles.get(kind, 'Price')}: \"{f.item.text}\" ", style="bold")
        title.append_text(badge(f.status))
        console.print(Panel(body, title=title, title_align="left", border_style=color(f.status), padding=(1, 2)))


SCHOOL_ROWS = [
    ("Admission rate", "admission_rate", pct),
    ("In-state tuition", "tuition_in_state", money),
    ("Out-of-state tuition", "tuition_out_of_state", money),
    ("Average net price", "net_price", money),
    ("Graduation rate", "graduation_rate", pct),
    ("Median earnings, 10 yrs", "earnings_10yr", money),
    ("Median debt", "median_debt", money),
    ("Undergraduates", "undergrads", lambda v: "-" if v is None else f"{v:,.0f}"),
    ("Research papers", "research_works", lambda v: "-" if v is None else f"{v:,.0f}"),
    ("Research h-index", "h_index", lambda v: "-" if v is None else f"{v}"),
]
METRIC_ROW = {"admission_rate": "admission_rate", "tuition_in_state": "tuition_in_state",
              "tuition_out_of_state": "tuition_out_of_state", "net_price": "net_price", "graduation_rate": "graduation_rate",
              "median_earnings_10yr": "earnings_10yr", "median_debt": "median_debt", "undergrad_enrollment": "undergrads"}


def schools(console: Console, fs: list[Finding]) -> None:
    if not fs:
        return
    section(console, "Schools and majors", "Official US Department of Education numbers, plus research output")
    all_schools: dict[str, dict] = {}
    programs: dict[tuple, dict] = {}
    claimed_rows: dict[str, str] = {}
    for f in fs:
        for s in f.data.get("schools", []):
            all_schools.setdefault(s["name"], {}).update({k: v for k, v in s.items() if v is not None})
        for p in f.data.get("programs", []):
            programs[(p["school"], p["program"], p["credential"])] = p
        claim = f.data.get("claim")
        if claim and claim.get("metric") in METRIC_ROW:
            claimed_rows[METRIC_ROW[claim["metric"]]] = claim.get("result", "info")

    if all_schools:
        t = Table(box=box.ROUNDED, expand=True, title="Side by side", title_style="bold")
        t.add_column("", style="bold", no_wrap=True)
        for name, s in all_schools.items():
            where = ", ".join(x for x in (s.get("city"), s.get("state")) if x)
            t.add_column(Text(name + (f"\n{where}" if where else ""), justify="center"), justify="center")
        for label, key, fn in SCHOOL_ROWS:
            values = [s.get(key) for s in all_schools.values()]
            if all(v is None for v in values):
                continue
            style = f"bold {color(claimed_rows[key])}" if key in claimed_rows else ""
            marker = "  <- mentioned" if key in claimed_rows else ""
            t.add_row(Text(label + marker, style=style), *[Text(fn(v), style=style) for v in values])
        console.print(t)

    if programs:
        t = Table(box=box.ROUNDED, expand=True, title="What graduates earn", title_style="bold")
        for col in ("School", "Major", "Degree", "Graduates", "1 yr after", "4 yrs after", "5 yrs after", "Median debt"):
            t.add_column(col, justify="right" if col not in ("School", "Major", "Degree") else "left")
        for p in programs.values():
            t.add_row(Text(p["school"]), Text(p["program"]), Text(p["credential"]),
                      "-" if p.get("graduates") is None else f"{p['graduates']:,}",
                      money(p.get("earnings_1yr")), money(p.get("earnings_4yr")), money(p.get("earnings_5yr")),
                      money(p.get("median_debt")))
        console.print(t)

    t = Table(box=box.SIMPLE_HEAVY, expand=True, title="What was claimed", title_style="bold", show_lines=True)
    t.add_column("", no_wrap=True)
    t.add_column("What it said", ratio=3)
    t.add_column("Checked", ratio=3)
    t.add_column("Claimed", justify="right", ratio=2)
    t.add_column("Actual", justify="right", ratio=2)
    for f in fs:
        claim = f.data.get("claim")
        if f.checker == "web":
            t.add_row(badge(f.status), Text(f'"{f.item.text}"', style="italic"), Text("Online sources"), Text("-"), Text(f.summary))
        elif claim:
            t.add_row(badge(f.status), Text(f'"{f.item.text}"', style="italic"), Text(claim["label"]),
                      Text(claim["claimed"]), Text(claim["official"], style="bold"))
        elif f.data.get("opinion"):
            t.add_row(badge(f.status), Text(f'"{f.item.text}"', style="italic"),
                      Text("This is an opinion"), Text("-"), Text("Compare the numbers above"))
        else:
            t.add_row(badge(f.status), Text(f'"{f.item.text}"', style="italic"), Text(f.title), Text("-"),
                      Text(f.summary.split(". College Scorecard")[0]))
    console.print(t)


def statistics(console: Console, fs: list[Finding]) -> None:
    if not fs:
        return
    section(console, "Official numbers", "What the government had published when this was said, and what it says now")
    t = Table(box=box.ROUNDED, expand=True, show_lines=True)
    t.add_column("", no_wrap=True)
    t.add_column("What it said", ratio=3)
    t.add_column("Statistic", ratio=2)
    t.add_column("When it was said", ratio=2)
    t.add_column("Revised since", ratio=2)
    t.add_column("Latest", ratio=2)
    for f in fs:
        d = f.data
        figs = d.get("figures", {})

        def cell(key: str) -> Text:
            fig = figs.get(key)
            if not fig:
                return Text("-", style="dim")
            out = Text(fig["value"], style="bold")
            out.append(f"\n{fig['period']}", style="dim")
            return out

        when = cell("when_said") if "when_said" in figs else cell("today")
        revised = cell("revised")
        if figs.get("revised") and figs.get("when_said") and figs["revised"]["value"] != figs["when_said"]["value"]:
            revised.stylize("yellow3")
        t.add_row(badge(f.status), Text(f'"{f.item.text}"', style="italic"), Text(f"{d.get('label')}\n{d.get('agency')}"),
                  when, revised, cell("latest"))
    console.print(t)


def web_claims(console: Console, fs: list[Finding]) -> None:
    if not fs:
        return
    section(console, "Other claims", "Checked against sources found online")
    for f in fs:
        body = Group(Text(f.summary), *[Text(s["title"], style=f"link {s['url']} underline dim") for s in f.data.get("sources", [])[:3]])
        title = Text(f' "{f.item.text}" ', style="bold italic")
        title.append_text(badge(f.status))
        console.print(Panel(body, title=title, title_align="left", border_style=color(f.status), padding=(0, 2)))


def unconfirmed(console: Console, fs: list[Finding]) -> None:
    if not fs:
        return
    section(console, "Couldn't confirm", "We found no reliable record of these, so check them yourself")
    for f in fs:
        console.print(Text("  - ").append(f'"{f.item.text}"', style="italic"))


def render(report: Report, *, console: Console | None = None, **_ignored) -> None:
    console = console or Console()
    fs = report.findings
    by_checker = lambda *names: [f for f in fs if f.checker in names]  # noqa: E731
    web_for = lambda *kinds: [f for f in fs if f.checker == "web" and f.item.kind in kinds]  # noqa: E731

    header(console, report)
    community(console, by_checker("community"))
    warning_signs(console, by_checker("patterns"))
    organizations(console, by_checker("registry", "reputation") + web_for("entity"))
    prices(console, by_checker("benchmark") + web_for("price"))
    schools(console, by_checker("college") + web_for("school"))
    statistics(console, by_checker("statistic"))
    web_claims(console, web_for("claim", "statistic"))
    unconfirmed(console, by_checker("router"))
    console.print()
    console.print(Text("A screening tool, not legal or financial advice. Open the sources before you act.", style="dim italic"),
                  justify="center")


# --- Input ---

def _more_pasted_lines() -> list[str]:
    """After the first line, collect any other lines that arrived in the same paste."""
    lines: list[str] = []
    time.sleep(0.15)
    if os.name == "nt":
        import msvcrt

        while True:
            if msvcrt.kbhit():
                lines.append(input())
                continue
            time.sleep(0.12)
            if not msvcrt.kbhit():
                break
    else:
        import select

        while select.select([sys.stdin], [], [], 0.15)[0]:
            line = sys.stdin.readline()
            if not line:
                break
            lines.append(line.rstrip("\n"))
    return lines


def read_text(console: Console) -> str | None:
    """Returns the pasted or typed text, or None to quit."""
    while True:
        console.print(Text("Paste or type anything, then press Enter.", style="bold cyan"))
        try:
            first = console.input("[bold cyan]> [/]")
        except EOFError:
            return None
        if first.strip().lower() in ("q", "quit", "exit"):
            return None
        text = "\n".join([first] + _more_pasted_lines()).strip()
        if text:
            return text


def check(console: Console, text: str, offline: bool) -> None:
    with console.status("[bold]Reading...", spinner="dots") as status:
        report = router.run(text, date.today(), offline=offline, progress=lambda msg: status.update(f"[bold]{msg}"))
    render(report, console=console)


def main(argv=None) -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(prog="python -m legit", description="Paste anything and see what holds up.")
    ap.add_argument("--text", help=argparse.SUPPRESS)
    ap.add_argument("--offline", action="store_true", help=argparse.SUPPRESS)
    args = ap.parse_args(argv)
    console = Console()

    console.print(Panel(Text.assemble(("Is this legit?", "bold"), "\n",
                                      ("Paste a listing, a job offer, a message, a post, or a video transcript. "
                                       "We'll check what it says.", "dim")),
                        border_style="cyan", padding=(1, 2)))
    try:
        if args.text:
            check(console, args.text, args.offline)
            return 0
        while True:
            text = read_text(console)
            if text is None:
                return 0
            check(console, text, args.offline)
            console.print()
            console.rule(style="grey35")
            console.print()
    except KeyboardInterrupt:
        console.print()
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())

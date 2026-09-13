"""Run every item through official-data checkers first, then send anything unresolved to the web."""
from __future__ import annotations

import re
import sys
from datetime import date

from . import extract
from .checkers import benchmark, college, patterns, registry, reputation, statistic, web
from .models import Extraction, Finding, Item, Report

OFFICIAL = {
    "entity": [registry.check, reputation.check],
    "price": [benchmark.check],
    "statistic": [statistic.check],
    "pattern": [patterns.check],
    "school": [college.check],
    "claim": [],
}
SETTLING = {"ok", "caution", "red_flag"}


def shorten(text: str, limit: int = 70) -> str:
    """Trim to a word boundary so titles don't end mid-word."""
    text = " ".join(text.split())
    if len(text) <= limit:
        return text
    return text[:limit].rsplit(" ", 1)[0].rstrip(",;:") + "..."


def _progress(msg: str) -> None:
    print(msg, file=sys.stderr, flush=True)


def check_official(ext: Extraction, notes: list[str]) -> tuple[list[Finding], list[Item]]:
    """Official-data checks for every item. Returns findings and the items that still need the web."""
    findings: list[Finding] = []
    needs_web: list[Item] = []
    for item in ext.items:
        got: list[Finding] = []
        for fn in OFFICIAL.get(item.kind, []):
            try:
                f = fn(item, ext)
            except Exception as e:  # noqa: BLE001  one broken checker shouldn't sink the report
                notes.append(f"{fn.__module__.rsplit('.', 1)[-1]} check failed for item {item.id}: {e}")
                continue
            if f is not None:
                got.append(f)
        findings.extend(got)
        # College facts settle an item even as "info": showing the official numbers is the answer.
        settled = any((f.status in SETTLING or f.checker == "college") and f.checker != "reputation" for f in got)
        followup = any(f.web_followup for f in got)
        unbenchmarkable = item.kind == "price" and (item.data.get("category") or "") in ("fee", "other")
        if item.kind != "pattern" and not unbenchmarkable and (not settled or followup):
            needs_web.append(item)
    return findings, needs_web


def finish(ext: Extraction, findings: list[Finding], needs_web: list[Item], notes: list[str], *,
           offline: bool, progress=_progress) -> Report:
    """Web fallback for unresolved items, then mark anything still unchecked as unverified."""
    if needs_web and not offline:
        progress(f"Searching the web for {len(needs_web)} item(s) without official records (this can take a minute)...")
        web_findings, web_notes = web.verify(needs_web, ext)
        findings.extend(web_findings)
        notes.extend(web_notes)
    elif needs_web:
        notes.append(f"{len(needs_web)} item(s) had no official record; run without --offline to search the web.")

    covered = {f.item.id for f in findings}
    for item in needs_web:
        if item.id not in covered:
            label = item.data.get("name") or item.data.get("claim") or item.text
            findings.append(Finding(item, "unverified", f"No record found: {shorten(str(label))}",
                                    "Nothing in official data or web results confirmed this. Verify it yourself before acting.",
                                    "router"))
    return Report(ext, dedupe(findings), notes)


def dedupe(findings: list[Finding]) -> list[Finding]:
    """Merge findings that say exactly the same thing about different quotes, e.g. one school profile per sentence."""
    first: dict[tuple, Finding] = {}
    extra_quotes: dict[tuple, list[str]] = {}
    out: list[Finding] = []
    for f in findings:
        key = (f.checker, f.status, f.title, f.summary)
        if key not in first:
            first[key] = f
            extra_quotes[key] = []
            out.append(f)
        elif f.item.text and f.item.text != first[key].item.text:
            extra_quotes[key].append(f.item.text)
    for key, quotes in extra_quotes.items():
        if quotes:
            first[key].summary += " Also applies to: " + "; ".join(f'"{q}"' for q in quotes) + "."
    return out


LONG_TEXT = 3500
PART_CHARS = 3000
LONG_HINT = ("This is part of a long text, such as an article, a post thread, or a video transcript. It may be spoken "
             "language without punctuation. Extract checkable factual claims, statistics, prices and rates, claims about "
             "specific schools and majors, and offers. Skip predictions, opinions, greetings, and sponsor reads.")


def split_text(text: str, max_chars: int = PART_CHARS) -> list[str]:
    """Split long text at sentence or line breaks into parts small enough for one extraction call."""
    pieces = [p.strip() for p in re.split(r"(?<=[.!?])\s+|\n+", text) if p.strip()]
    parts, current = [], ""
    for piece in pieces:
        if current and len(current) + len(piece) + 1 > max_chars:
            parts.append(current)
            current = piece
        else:
            current = f"{current} {piece}".strip()
    if current:
        parts.append(current)
    out = []
    for part in parts:  # transcripts often have no punctuation at all
        while len(part) > max_chars:
            cut = part.rfind(" ", 0, max_chars)
            cut = cut if cut > 0 else max_chars
            out.append(part[:cut].strip())
            part = part[cut:].strip()
        if part:
            out.append(part)
    return out


def run(text: str, said_on: date, *, offline: bool = False, progress=_progress, hint: str | None = None) -> Report:
    if len(text) > LONG_TEXT:
        return run_long(text, said_on, offline=offline, progress=progress, hint=hint)
    progress("Reading the text...")
    ext, notes = extract.extract(text, said_on, hint=hint)
    progress("Checking official data...")
    findings, needs_web = check_official(ext, notes)
    return finish(ext, findings, needs_web, notes, offline=offline, progress=progress)


def run_long(text: str, said_on: date, *, offline: bool = False, progress=_progress, hint: str | None = None) -> Report:
    """Long text (articles, transcripts): read it in parts, check each part, then combine into one report."""
    from .youtube import _skip_in_video  # local import: youtube imports this module

    parts = split_text(text)
    combined = Extraction(said_on=said_on)
    findings: list[Finding] = []
    needs_web: list[Item] = []
    notes: list[str] = []
    next_id = 1
    for n, part in enumerate(parts, start=1):
        progress(f"Reading part {n} of {len(parts)}...")
        ext, ext_notes = extract.extract(part, said_on, hint=hint or LONG_HINT)
        notes.extend(ext_notes)
        ext.items = [i for i in ext.items if not _skip_in_video(i)]
        extract.demote_subgroup_statistics(ext, text)  # full text, so context split across parts still counts
        for item in ext.items:
            if item.kind == "price" and (item.data.get("category") or "") in ("hourly_wage", "salary"):
                item.kind, item.data = "claim", {"claim": item.text}  # a salary in an article is a claim, not an offer
            item.id = next_id
            next_id += 1
        combined.items.extend(ext.items)
        combined.parser = ext.parser
        combined.summary = combined.summary or ext.summary
        if combined.context == "other":
            combined.context = ext.context
        if not combined.location.label() and ext.location.label():
            combined.location = ext.location
        part_findings, part_needs = check_official(ext, notes)
        findings.extend(part_findings)
        needs_web.extend(part_needs)
    return finish(combined, findings, needs_web, notes, offline=offline, progress=progress)

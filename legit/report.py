"""Render a report for the terminal, or as JSON for a future UI."""
from __future__ import annotations

import dataclasses
import json
import textwrap
from datetime import date

from .models import SEVERITY, Report

TAGS = {"red_flag": "RED FLAG", "caution": "CAUTION", "unverified": "UNVERIFIED", "info": "INFO", "ok": "OK"}
KIND_LABELS = {"official": "official data", "web": "web", "guidance": "official guidance", "ai": "AI reading",
               "community": "student reports"}
WIDTH = 100


def _wrap(text: str, indent: str) -> list[str]:
    return textwrap.wrap(text, WIDTH, initial_indent=indent, subsequent_indent=indent) or [indent.rstrip()]


def render(report: Report) -> str:
    ext = report.extraction
    counts = ", ".join(f"{report.count(s)} {TAGS[s].lower()}" for s in ("red_flag", "caution", "unverified")
                       if report.count(s))
    lines = [f"Overall:  {report.overall}" + (f"  ({counts})" if counts else "")]
    if ext.summary:
        lines += _wrap(f"About:    {ext.summary}", "")
    place = ext.location.label()
    lines.append(f"Context:  {ext.context}{'  |  ' + place if place else ''}  |  read by {ext.parser}  |  seen {ext.said_on}")

    for f in sorted(report.findings, key=lambda f: (-SEVERITY[f.status], f.item.id)):
        lines.append("")
        lines.append(f"[{TAGS[f.status]}] {f.title}")
        if f.item.text:
            lines += _wrap(f'"{f.item.text}"', "    ")
        if f.summary:
            lines += _wrap(f.summary, "    ")
        for ev in f.evidence:
            url = f" {ev.url}" if ev.url else ""
            lines += _wrap(f"- {ev.source} [{KIND_LABELS.get(ev.kind, ev.kind)}]: {ev.detail}{url}", "      ")

    if report.notes:
        lines.append("")
        lines += [f"Note: {n}" for n in report.notes]
    lines.append("")
    lines += _wrap("This is a screening tool, not legal or financial advice. Official data runs through mid-June 2026; "
                   "web results can be wrong, so open the sources.", "")
    return "\n".join(lines)


def to_json(report: Report) -> str:
    def default(o):
        if isinstance(o, date):
            return o.isoformat()
        raise TypeError(type(o).__name__)

    payload = dataclasses.asdict(report)
    payload["overall"] = report.overall
    return json.dumps(payload, default=default, indent=2)

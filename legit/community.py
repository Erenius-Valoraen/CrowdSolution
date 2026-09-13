"""Shared scam memory across students, stored as Backboard.io assistant memories.

Every check with red flags is remembered: the scammer's emails, suspicious domains, and phone numbers, plus the red
flags, a summary, and a short excerpt. Nothing about the student is stored. Later checks look for:

- exact matches on an email, domain, or phone number -> RED FLAG "flagged before by other students"
- a near-identical message                           -> RED FLAG, counted as the same report
- a closely similar message (semantic search)        -> CAUTION "looks like a scam other students flagged"

Backboard search scores are distances: lower means more similar (a real match scored 0.46, unrelated text 0.77+).
Set COMMUNITY_MEMORY=off to disable. Failures never break a check; they only add a note."""
from __future__ import annotations

import json
import re
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from datetime import date

from . import config
from .checkers.common import FREE_EMAIL_DOMAINS, domain_of
from .models import Evidence, Extraction, Finding, Item, Report

BASE_URL = "https://app.backboard.io/api"
SOURCE = "CrowdSolution community scam memory (Backboard.io)"
SAME_REPORT_MAX_DISTANCE = 0.25   # near-identical text: treat as the same scam
SIMILAR_MAX_DISTANCE = 0.45       # close match: warn, but don't call it the same scam
PAGE_SIZE = 100
MAX_PAGES = 5
TIMEOUT = 15

EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
PHONE = re.compile(r"(?<![\d$])(?:\+?1[\s.-]?)?\(?(\d{3})\)?[\s.-]?(\d{3})[\s.-]?(\d{4})(?!\d)")
DOMAIN = re.compile(r"\b(?:https?://)?(?:www\.)?((?:[a-z0-9-]+\.)+(?:com|ca|org|net|io|co|info|biz|us|app|xyz|online|site|shop|top|live))\b",
                    re.I)
# Big platforms show up in honest and scam messages alike, so they never count as scam indicators.
COMMON_PLATFORMS = {
    "facebook.com", "instagram.com", "tiktok.com", "reddit.com", "youtube.com", "google.com", "gmail.com", "zillow.com",
    "kijiji.ca", "craigslist.org", "rentals.ca", "padmapper.com", "apartments.com", "indeed.com", "linkedin.com",
    "zelle.com", "paypal.com", "venmo.com", "interac.ca", "wa.me", "whatsapp.com", "t.me", "telegram.org",
}
SAFE_DOMAIN_RESULTS = {"official", "brand_match"}
MATCHABLE = ("email", "domain", "phone")


class CommunityError(RuntimeError):
    pass


def enabled() -> bool:
    return config.COMMUNITY_MEMORY and bool(config.BACKBOARD_KEY)


# --- Backboard REST ---

def _call(method: str, path: str, body: dict | None = None) -> dict | list | None:
    key = config.BACKBOARD_KEY
    req = urllib.request.Request(BASE_URL + path, method=method,
                                 data=None if body is None else json.dumps(body).encode("utf-8"),
                                 headers={"X-API-Key": key, "Content-Type": "application/json", "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            raw = resp.read().decode("utf-8")
            return json.loads(raw) if raw else None
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", "replace")[:200].replace(key, "***")
        raise CommunityError(f"Backboard HTTP {e.code}: {detail}") from None
    except (urllib.error.URLError, TimeoutError, ValueError) as e:
        raise CommunityError(f"Backboard unreachable: {e}") from None


_assistant_id: str | None = None


def assistant_id() -> str:
    """The shared assistant that holds community memories: from config, found by name, or created once."""
    global _assistant_id
    if _assistant_id:
        return _assistant_id
    if config.BACKBOARD_COMMUNITY_ASSISTANT_ID:
        _assistant_id = config.BACKBOARD_COMMUNITY_ASSISTANT_ID
        return _assistant_id
    name = config.BACKBOARD_COMMUNITY_ASSISTANT
    rows = _call("GET", "/assistants?" + urllib.parse.urlencode({"name": name, "limit": 5}))
    if isinstance(rows, dict):
        rows = rows.get("assistants") or rows.get("data") or []
    for row in rows or []:
        if row.get("name") == name and row.get("assistant_id"):
            _assistant_id = row["assistant_id"]
            return _assistant_id
    created = _call("POST", "/assistants", {
        "name": name,
        "system_prompt": "Shared memory of scams that university students reported through CrowdSolution. "
                         "Stores scammer contact details, red flags, and short excerpts. Never stores student details.",
    })
    _assistant_id = created["assistant_id"]
    return _assistant_id


def list_memories(aid: str) -> list[dict]:
    out: list[dict] = []
    for page in range(1, MAX_PAGES + 1):
        data = _call("GET", f"/assistants/{aid}/memories?" + urllib.parse.urlencode({"page": page, "page_size": PAGE_SIZE}))
        batch = (data or {}).get("memories") or []
        out.extend(batch)
        if len(batch) < PAGE_SIZE:
            break
    return out


def search_memories(aid: str, query: str, limit: int = 3) -> list[dict]:
    data = _call("POST", f"/assistants/{aid}/memories/search", {"query": query[:1000], "limit": limit})
    return (data or {}).get("memories") or []


# --- Indicators and memory format (pure, unit tested) ---

def normalize_phone(area: str, exchange: str, line: str) -> str:
    return f"{area}{exchange}{line}"


def extract_indicators(text: str, ext: Extraction, findings: list[Finding]) -> list[tuple[str, str]]:
    """Scammer contact details worth remembering or matching. Official and big-platform domains are left out."""
    safe = {f.data.get("claimed_domain") for f in findings if f.data.get("domain_result") in SAFE_DOMAIN_RESULTS}
    found: list[tuple[str, str]] = []

    def add(kind: str, value: str | None) -> None:
        if value and (kind, value) not in found:
            found.append((kind, value))

    for email in EMAIL.findall(text):
        add("email", email.lower().rstrip("."))
    for m in PHONE.finditer(text):
        add("phone", normalize_phone(*m.groups()))
    candidates = [domain_of(e) for kind, e in found if kind == "email"]
    candidates += [domain_of(m.group(1)) for m in DOMAIN.finditer(text)]
    for item in ext.items:
        if item.kind == "entity":
            candidates += [domain_of(item.data.get("website")), domain_of(item.data.get("email_domain"))]
    for d in candidates:
        if d and d not in FREE_EMAIL_DOMAINS and d not in COMMON_PLATFORMS and d not in safe:
            add("domain", d)
    for item in ext.items:
        if item.kind == "entity" and item.data.get("name"):
            add("name", str(item.data["name"]).strip())
    return found[:12]


def format_memory(ext: Extraction, indicators: list[tuple[str, str]], red_flags: list[str], text: str, reports: int,
                  first_seen: str, last_seen: str) -> tuple[str, dict]:
    excerpt = " ".join(text.split())[:240]
    lines = [
        f"SCAM REPORT | context: {ext.context} | reports: {reports} | first seen: {first_seen} | last seen: {last_seen}",
        "Indicators: " + ("; ".join(f"{k}={v}" for k, v in indicators) or "none"),
        "Red flags: " + ("; ".join(red_flags) or "none"),
        f"Summary: {ext.summary or 'n/a'}",
        f'Excerpt: "{excerpt}"',
    ]
    # Backboard rejects nested lists in metadata (HTTP 500), so indicators are stored as flat "kind=value" strings.
    metadata = {"kind": "scam_report", "context": ext.context, "reports": reports, "first_seen": first_seen,
                "last_seen": last_seen, "indicators": [f"{k}={v}" for k, v in indicators], "red_flags": red_flags,
                "summary": ext.summary or ""}
    return "\n".join(lines), metadata


def _indicator(value) -> tuple[str, str] | None:
    """"email=a@b.site" or ["email", "a@b.site"] -> ("email", "a@b.site")."""
    if isinstance(value, str) and "=" in value:
        kind, _, rest = value.partition("=")
        return kind, rest
    if isinstance(value, (list, tuple)) and len(value) == 2:
        return str(value[0]), str(value[1])
    return None


def parse_memory(memory: dict) -> dict:
    """A stored report as a dict. Uses metadata when the API returns it, otherwise parses the text."""
    meta = memory.get("metadata") or {}
    content = memory.get("content") or ""
    if meta.get("kind") == "scam_report":
        record = dict(meta)
        record["indicators"] = [_indicator(x) for x in meta.get("indicators", []) if _indicator(x)]
    else:
        def field_of(label: str) -> str:
            m = re.search(rf"^{label}: (.*)$", content, re.M)
            return m.group(1).strip() if m else ""

        head = content.splitlines()[0] if content else ""
        header = dict(part.split(": ", 1) for part in head.split(" | ")[1:] if ": " in part)
        indicators = []
        raw = field_of("Indicators")
        if raw and raw != "none":
            indicators = [tuple(p.split("=", 1)) for p in raw.split("; ") if "=" in p]
        flags = field_of("Red flags")
        record = {"kind": "scam_report" if head.startswith("SCAM REPORT") else "other",
                  "context": header.get("context", ""), "reports": int(header.get("reports", "1") or 1),
                  "first_seen": header.get("first seen", ""), "last_seen": header.get("last seen", ""),
                  "indicators": indicators, "red_flags": [] if flags in ("", "none") else flags.split("; "),
                  "summary": field_of("Summary")}
    record["id"] = memory.get("id") or memory.get("memory_id")
    record["score"] = memory.get("score")
    return record


def merge_indicators(a: list[tuple[str, str]], b: list[tuple[str, str]]) -> list[tuple[str, str]]:
    out = list(a)
    for x in b:
        if x not in out:
            out.append(x)
    return out[:20]


# --- Check and remember ---

@dataclass
class Lookup:
    checked: bool = False
    findings: list[Finding] = field(default_factory=list)
    same: dict | None = None          # the stored report this scan belongs to, if any


def check(ext: Extraction, text: str, findings: list[Finding], notes: list[str], progress=None) -> Lookup:
    if not enabled():
        return Lookup()
    if progress:
        progress("Checking what other students reported...")
    try:
        aid = assistant_id()
        indicators = extract_indicators(text, ext, findings)
        wanted = {x for x in indicators if x[0] in MATCHABLE}
        exact = []
        if wanted:
            for m in list_memories(aid):
                record = parse_memory(m)
                hits = [x for x in record["indicators"] if tuple(x) in wanted]
                if record["kind"] == "scam_report" and hits:
                    exact.append((record, hits))
        similar = None
        if not exact:
            query = ext.summary or text
            results = [parse_memory(m) for m in search_memories(aid, f"{query}\n{text[:400]}")]
            results = [r for r in results if r["kind"] == "scam_report" and r["score"] is not None]
            if results:
                best = min(results, key=lambda r: r["score"])
                if best["score"] <= SIMILAR_MAX_DISTANCE:
                    similar = best
    except CommunityError as e:
        notes.append(f"Community memory unavailable: {e}")
        return Lookup()

    next_id = max([i.id for i in ext.items] + [f.item.id for f in findings] + [0]) + 1
    lookup = Lookup(checked=True)
    for record, hits in exact:
        lookup.findings.append(_finding(next_id, record, "exact", hits))
        next_id += 1
    if exact:
        lookup.same = exact[0][0]
    elif similar is not None:
        same = similar["score"] <= SAME_REPORT_MAX_DISTANCE
        lookup.findings.append(_finding(next_id, similar, "same_message" if same else "similar", []))
        if same:
            lookup.same = similar
    return lookup


def _finding(item_id: int, record: dict, match: str, hits: list) -> Finding:
    reports = int(record.get("reports") or 1)
    times = f"{reports} time{'s' if reports != 1 else ''}"
    when = f", most recently on {record['last_seen']}" if record.get("last_seen") else ""
    flags = record.get("red_flags") or []
    if match == "exact":
        values = ", ".join(v for _, v in hits)
        title = "Flagged before by other students"
        quote = values
        summary = f"{values} appeared in scam reports from other students {times}{when}."
        status = "red_flag"
    elif match == "same_message":
        title = "This message was reported before"
        quote = record.get("summary") or ""
        summary = f"Other students reported an almost identical message {times}{when}."
        status = "red_flag"
    else:
        title = "Looks like a scam other students flagged"
        quote = record.get("summary") or ""
        summary = f"This closely resembles a scam other students reported {times}{when}. Compare the details carefully."
        status = "caution"
    if flags:
        summary += " Red flags in that report: " + "; ".join(flags[:4]) + "."
    evidence = [Evidence(SOURCE, record.get("summary") or "Earlier student report", "community")]
    data = {"type": "community", "match": match, "matched": [{"kind": k, "value": v} for k, v in hits],
            "reports": reports, "first_seen": record.get("first_seen"), "last_seen": record.get("last_seen"),
            "context": record.get("context"), "red_flags": flags, "summary": record.get("summary"),
            "distance": record.get("score")}
    return Finding(Item(item_id, "community", quote, {}), status, title, summary, "community", evidence, data=data)


def remember(report: Report, text: str, lookup: Lookup, notes: list[str]) -> None:
    """Save a scan with red flags to the shared memory, or count it again if it's a scam already on file."""
    if not enabled() or not lookup.checked:
        return
    red = [f for f in report.findings if f.status == "red_flag" and f.checker != "community"]
    if not red:
        return
    today = date.today().isoformat()
    ext = report.extraction
    indicators = extract_indicators(text, ext, report.findings)
    red_flags = list(dict.fromkeys(f.title for f in red))[:6]
    try:
        aid = assistant_id()
        if lookup.same and lookup.same.get("id"):
            prev = lookup.same
            content, metadata = format_memory(
                ext, merge_indicators(list(prev.get("indicators") or []), indicators),
                list(dict.fromkeys(list(prev.get("red_flags") or []) + red_flags))[:8], text,
                int(prev.get("reports") or 1) + 1, prev.get("first_seen") or today, today)
            _call("PUT", f"/assistants/{aid}/memories/{prev['id']}", {"content": content, "metadata": metadata})
        else:
            content, metadata = format_memory(ext, indicators, red_flags, text, 1, today, today)
            _call("POST", f"/assistants/{aid}/memories", {"content": content, "metadata": metadata})
    except CommunityError as e:
        notes.append(f"Couldn't save to community memory: {e}")

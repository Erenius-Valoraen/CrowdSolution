"""Data types: extracted items, evidence, findings, and the final report."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

SEVERITY = {"red_flag": 4, "caution": 3, "unverified": 2, "info": 1, "ok": 0}

CANADIAN_REGIONS = {
    "ontario", "on", "quebec", "qc", "british columbia", "bc", "alberta", "ab", "manitoba", "mb",
    "saskatchewan", "sk", "nova scotia", "ns", "new brunswick", "nb", "newfoundland and labrador", "nl",
    "prince edward island", "pe", "yukon", "yt", "northwest territories", "nt", "nunavut", "nu",
}


@dataclass
class Location:
    city: str | None = None
    region: str | None = None       # US state or Canadian province
    country: str | None = None

    @property
    def is_canada(self) -> bool:
        country = (self.country or "").strip().lower()
        region = (self.region or "").strip().lower()
        return country in ("ca", "can", "canada") or region in CANADIAN_REGIONS

    def label(self) -> str:
        return ", ".join(p for p in (self.city, self.region, self.country) if p)


@dataclass
class Item:
    """One checkable thing pulled out of the text.

    kind is entity, price, statistic, pattern, or claim. `data` holds the kind-specific fields."""

    id: int
    kind: str
    text: str
    data: dict = field(default_factory=dict)


@dataclass
class Evidence:
    source: str
    detail: str
    kind: str = "official"          # official | web | guidance | ai
    url: str | None = None


@dataclass
class Finding:
    item: Item
    status: str                     # red_flag | caution | unverified | info | ok
    title: str
    summary: str
    checker: str
    evidence: list[Evidence] = field(default_factory=list)
    web_followup: bool = False      # official data was partial; also search the web
    data: dict = field(default_factory=dict)  # structured numbers for tables, charts, and the JSON output


@dataclass
class Extraction:
    said_on: date
    context: str = "other"          # housing | job | finance | school | health | everyday | other
    summary: str = ""
    location: Location = field(default_factory=Location)
    items: list[Item] = field(default_factory=list)
    parser: str = "groq"


@dataclass
class Report:
    extraction: Extraction
    findings: list[Finding]
    notes: list[str] = field(default_factory=list)

    def count(self, status: str) -> int:
        return sum(1 for f in self.findings if f.status == status)

    @property
    def overall(self) -> str:
        if not self.findings:
            return "NOTHING TO CHECK"
        if self.count("red_flag"):
            return "HIGH RISK"
        if self.count("caution"):
            return "BE CAREFUL"
        if all(f.status == "unverified" for f in self.findings):
            return "COULDN'T VERIFY"
        return "NO RED FLAGS FOUND"

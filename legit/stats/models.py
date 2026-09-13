"""Plain data types shared by the parser, lookups, and verdict logic."""
from __future__ import annotations

import calendar
from dataclasses import dataclass, field
from datetime import date


@dataclass(frozen=True)
class Period:
    """A calendar period a claim refers to: a year, a quarter, or a month."""

    year: int
    month: int | None = None
    quarter: int | None = None

    def contains(self, d: date) -> bool:
        if d.year != self.year:
            return False
        if self.month is not None and d.month != self.month:
            return False
        if self.quarter is not None and (d.month - 1) // 3 + 1 != self.quarter:
            return False
        return True

    def start(self) -> date:
        if self.month:
            return date(self.year, self.month, 1)
        if self.quarter:
            return date(self.year, 3 * self.quarter - 2, 1)
        return date(self.year, 1, 1)

    def end(self) -> date:
        if self.month:
            return date(self.year, self.month, calendar.monthrange(self.year, self.month)[1])
        if self.quarter:
            m = 3 * self.quarter
            return date(self.year, m, calendar.monthrange(self.year, m)[1])
        return date(self.year, 12, 31)

    def label(self) -> str:
        if self.month:
            return f"{calendar.month_name[self.month]} {self.year}"
        if self.quarter:
            return f"Q{self.quarter} {self.year}"
        return str(self.year)

    @staticmethod
    def from_dict(d: dict | None) -> Period | None:
        if not d or not d.get("year"):
            return None
        month = int(d["month"]) if d.get("month") else None
        quarter = int(d["quarter"]) if d.get("quarter") else None
        return Period(int(d["year"]), month, quarter)


@dataclass
class Claim:
    """One checkable statistical claim.

    `value` is in display units: percentages as percent numbers (4.1 means 4.1%),
    counts and dollars as full numbers."""

    text: str
    said_on: date
    metric_id: str | None = None
    measure: str | None = None          # level | change | yoy_pct | annual_total
    value: float | None = None
    precision: float | None = None      # half the smallest unit the speaker stated
    period: Period | None = None
    state: str | None = None
    city: str | None = None
    comparator: str = "about"           # about | over | under | nearly
    parser: str = "rules"
    notes: list[str] = field(default_factory=list)


@dataclass
class Obs:
    """One raw data point as stored, or as it was known on some date."""

    period_end: date
    value: float
    published: date | None
    complete: bool = True


@dataclass
class Figure:
    """A computed number ready to compare with a claim, in display units."""

    value: float
    period_end: date
    published: date | None
    label: str
    complete: bool = True


def half_step(value: float) -> float:
    """Half the smallest unit implied by how a number is written.

    4.1 -> 0.05, 4 -> 0.5, 200000 -> 50000, 227000 -> 500."""
    if value == 0:
        return 0.5
    s = f"{abs(value):.6f}".rstrip("0").rstrip(".")
    if "." in s:
        return 0.5 * 10 ** -len(s.split(".")[1])
    zeros = len(s) - len(s.rstrip("0"))
    return 0.5 * 10 ** zeros

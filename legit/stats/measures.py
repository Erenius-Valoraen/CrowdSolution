"""Turn raw observations into numbers people quote: a level, a change, a yearly % change, or a yearly total."""
from __future__ import annotations

import calendar
from datetime import date, timedelta

from .catalog import Metric
from .models import Figure, Obs, Period


def to_display(metric: Metric, raw: float) -> float:
    return raw * 100 if metric.scale == "fraction" else raw


def period_label(metric: Metric, d: date) -> str:
    if metric.frequency == "monthly":
        return f"{calendar.month_name[d.month]} {d.year}"
    if metric.frequency == "quarterly":
        return f"Q{(d.month - 1) // 3 + 1} {d.year}"
    if metric.frequency == "annual":
        return str(d.year)
    if metric.frequency == "weekly":
        return f"week ending {d.isoformat()}"
    return d.isoformat()


def _latest(*dates: date | None) -> date | None:
    ds = [d for d in dates if d]
    return max(ds) if ds else None


def _year_ago(points: list[tuple], d: date, frequency: str):
    if frequency in ("monthly", "quarterly", "annual"):
        for p in points:
            if p[0].year == d.year - 1 and (frequency == "annual" or p[0].month == d.month):
                return p
        return None
    target = d - timedelta(days=364)
    near = [p for p in points if abs((p[0] - target).days) <= 4]
    return min(near, key=lambda p: abs((p[0] - target).days)) if near else None


def compute_series(metric: Metric, measure: str, obs: list[Obs]) -> list[Figure]:
    """Every figure of the requested measure that these observations support."""
    pts = [(o.period_end, to_display(metric, o.value), o.published, o.complete) for o in obs]
    out: list[Figure] = []
    for i, (d, v, pub, complete) in enumerate(pts):
        label = period_label(metric, d)
        if measure in ("level", "annual_total"):
            out.append(Figure(v, d, pub, label, complete))
        elif measure == "change" and i > 0:
            _, prev_v, prev_pub, prev_complete = pts[i - 1]
            out.append(Figure(v - prev_v, d, _latest(pub, prev_pub), label, complete and prev_complete))
        elif measure == "yoy_pct":
            prev = _year_ago(pts[:i], d, metric.frequency)
            if prev and prev[1]:
                out.append(Figure(100 * (v / prev[1] - 1), d, _latest(pub, prev[2]), label, complete and prev[3]))
    return out


def select(figures: list[Figure], period: Period | None, before: date | None = None) -> Figure | None:
    """The figure a claim refers to: the last one inside `period`, or the latest complete one."""
    cands = [f for f in figures if before is None or f.period_end <= before]
    if period is not None:
        inside = [f for f in cands if period.contains(f.period_end)]
        return inside[-1] if inside else None
    complete = [f for f in cands if f.complete]
    pool = complete or cands
    return pool[-1] if pool else None


def same_period(figures: list[Figure], period_end: date) -> Figure | None:
    for f in figures:
        if f.period_end == period_end:
            return f
    return None

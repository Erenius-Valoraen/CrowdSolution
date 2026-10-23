"""Verdict rules. No database access, so these are easy to unit test."""
from __future__ import annotations

from datetime import date, timedelta

from .catalog import Metric
from .formatting import fmt
from .models import Claim, Figure, half_step

ACCURATE = "ACCURATE WHEN SAID"
OUTDATED_WHEN_SAID = "OUTDATED WHEN SAID"
WRONG = "WRONG WHEN SAID"
NOT_YET_PUBLISHED = "NOT YET PUBLISHED WHEN SAID"
MATCHES_TODAY = "MATCHES TODAY'S DATA"
MISMATCH_TODAY = "DOESN'T MATCH TODAY'S DATA"
CANT_VERIFY = "CAN'T VERIFY"

# How far back an older figure can be and still explain a claim as "outdated" rather than "wrong".
STALE_WINDOW = timedelta(days=366)


def is_percent_like(metric: Metric, measure: str) -> bool:
    return measure == "yoy_pct" or metric.kind == "rate" or metric.scale in ("fraction", "percent")


def tolerance(metric: Metric, measure: str, claim: Claim) -> float:
    """How far off a claim can be and still count, respecting the speaker's rounding.

    Percentages: at least 0.1 points, up to 0.5 when the speaker rounded to a whole number.
    Counts and dollars: at least 2%, up to 10% when the speaker rounded heavily."""
    claimed = claim.value or 0.0
    step = claim.precision if claim.precision is not None else half_step(claimed)
    if is_percent_like(metric, measure):
        return max(0.1, min(step, 0.5))
    return max(0.02 * abs(claimed), min(step, 0.10 * abs(claimed)))


def strict_slack(metric: Metric, measure: str, claim: Claim) -> float:
    """Small margin for "over" and "under" claims, where rounding generosity would be misleading."""
    if is_percent_like(metric, measure):
        return 0.05
    return 0.005 * abs(claim.value or 0.0)


def within(metric: Metric, measure: str, claim: Claim, actual: float) -> bool:
    claimed = claim.value
    eps = 1e-9 * max(1.0, abs(claimed), abs(actual))  # absorb floating-point noise like 4.2 - 4.1
    if claim.comparator == "over":
        return actual >= claimed - strict_slack(metric, measure, claim) - eps
    if claim.comparator == "under":
        return actual <= claimed + strict_slack(metric, measure, claim) + eps
    tol = tolerance(metric, measure, claim)
    if claim.comparator == "nearly":
        return claimed - 2 * tol - eps <= actual <= claimed + strict_slack(metric, measure, claim) + eps
    return abs(actual - claimed) <= tol + eps


def decide(claim: Claim, metric: Metric, measure: str, *, then: Figure | None, revised: Figure | None,
           latest: Figure | None, known_before: list[Figure], fallback: Figure | None,
           history_from: date | None, data_end: date) -> tuple[str, list[str]]:
    """Return (verdict, notes)."""
    show = lambda f: fmt(metric, measure, f.value)  # noqa: E731
    notes: list[str] = []
    if claim.said_on > data_end:
        notes.append(f"Our free data ends {data_end}; anything published after that is missing.")

    if history_from is None or claim.said_on < history_from:
        when = f"before {history_from}" if history_from else "for this series"
        notes.append(f"No record of what was published {when}; compared with today's revised data instead.")
        if fallback is None:
            return CANT_VERIFY, notes + ["No figure for that period in today's data."]
        return (MATCHES_TODAY if within(metric, measure, claim, fallback.value) else MISMATCH_TODAY), notes

    if then is None:
        if claim.period is not None:
            return NOT_YET_PUBLISHED, notes + [f"No {claim.period.label()} figure had been published by {claim.said_on}."]
        return CANT_VERIFY, notes + ["No figure had been published by that date."]

    if within(metric, measure, claim, then.value):
        if revised is not None and not within(metric, measure, claim, revised.value):
            notes.append(f"Revised since: the {revised.label} figure is now {show(revised)}.")
        if latest is not None and latest.period_end > then.period_end and not within(metric, measure, claim, latest.value):
            notes.append(f"Outdated now: the latest figure ({latest.label}) is {show(latest)}.")
        if not then.complete:
            notes.append(f"{then.label} was only partly reported at the time.")
        return ACCURATE, notes

    recent = [f for f in known_before if f.period_end >= then.period_end - STALE_WINDOW]
    for older in reversed(recent):
        if within(metric, measure, claim, older.value):
            notes.append(f"Matches the older {older.label} figure ({show(older)}), "
                         f"but the {then.label} figure ({show(then)}) was already out.")
            return OUTDATED_WHEN_SAID, notes

    notes.append(f"The latest figure at the time was {show(then)} for {then.label}.")
    if revised is not None and within(metric, measure, claim, revised.value):
        pub = f", published {revised.published}" if revised.published else ""
        notes.append(f"It does match the revised {revised.label} figure ({show(revised)}{pub}), "
                     f"which came out after the claim.")
    return WRONG, notes

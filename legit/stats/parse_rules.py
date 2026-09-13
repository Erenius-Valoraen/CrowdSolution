"""Rule-based claim parser. Works offline with no API key; the Groq parser takes over when a key is set."""
from __future__ import annotations

import re
from datetime import date

from .catalog import Catalog
from .models import Claim, Period

MONTHS = {name: i for i, name in enumerate(
    ["january", "february", "march", "april", "may", "june", "july", "august",
     "september", "october", "november", "december"], start=1)}
MONTHS.update({name[:3]: i for name, i in list(MONTHS.items())})
MONTHS["sept"] = 9

STATES = ["Alabama", "Alaska", "Arizona", "Arkansas", "California", "Colorado", "Connecticut", "Delaware",
          "District of Columbia", "Florida", "Georgia", "Hawaii", "Idaho", "Illinois", "Indiana", "Iowa", "Kansas",
          "Kentucky", "Louisiana", "Maine", "Maryland", "Massachusetts", "Michigan", "Minnesota", "Mississippi",
          "Missouri", "Montana", "Nebraska", "Nevada", "New Hampshire", "New Jersey", "New Mexico", "New York",
          "North Carolina", "North Dakota", "Ohio", "Oklahoma", "Oregon", "Pennsylvania", "Rhode Island",
          "South Carolina", "South Dakota", "Tennessee", "Texas", "Utah", "Vermont", "Virginia", "Washington",
          "West Virginia", "Wisconsin", "Wyoming"]

MULTIPLIERS = {"k": 1e3, "thousand": 1e3, "m": 1e6, "mn": 1e6, "million": 1e6, "b": 1e9, "bn": 1e9,
               "billion": 1e9, "t": 1e12, "tn": 1e12, "trillion": 1e12}

NUMBER = re.compile(
    r"(?<![\w.])(?P<dollar>\$)?(?P<num>\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?)"
    r"(?:\s*(?P<suffix>%|percent\b|per cent\b|percentage points?\b|thousand\b|million\b|billion\b|trillion\b"
    r"|mn\b|bn\b|tn\b|k\b|m\b|b\b|t\b))?", re.I)
MONTH_YEAR = re.compile(
    r"\b(" + "|".join(sorted(MONTHS, key=len, reverse=True)) + r")\.?,?\s+(?:of\s+)?(\d{4})\b", re.I)
QUARTER = re.compile(r"\b(?:q([1-4])|(first|second|third|fourth)\s+quarter)\s*(?:of\s+)?(\d{4})\b", re.I)
CHANGE_UP = re.compile(r"\b(added|adds|adding|created?|creates|creating|gained|gains)\b", re.I)
CHANGE_DOWN = re.compile(r"\b(lost|loses|losing|shed|cut|eliminated)\b", re.I)
DIRECTION = re.compile(
    r"\b(up|down|rose|rises?|rising|fell|falls?|falling|increased?|decreased?|grew|grows?|jumped|dropped|"
    r"declined?|surged|plunged|higher|lower|more|fewer|less)\b", re.I)
NEGATIVE = re.compile(r"\b(down|fell|falls?|falling|decreased?|dropped|declined?|plunged|lower|fewer|less)\b", re.I)
TO_LEVEL = re.compile(r"\b(to|at|is|was|hit|reached|stands at|stood at)\s+\$?\d", re.I)


def _half_step_text(raw: str) -> float:
    digits = raw.replace(",", "")
    if "." in digits:
        return 0.5 * 10 ** -len(digits.split(".")[1])
    return 0.5 * 10 ** (len(digits) - len(digits.rstrip("0")))


def _numbers(text: str):
    values, years = [], []
    for m in NUMBER.finditer(text):
        raw = m.group("num")
        suffix = (m.group("suffix") or "").lower().strip()
        n = float(raw.replace(",", ""))
        if not suffix and not m.group("dollar") and re.fullmatch(r"\d{4}", raw) and 1900 <= n <= 2100:
            years.append(int(n))
            continue
        pct = suffix.startswith(("%", "percent", "per cent"))
        mult = 1.0 if pct else MULTIPLIERS.get(suffix, 1.0)
        values.append({"value": n * mult, "step": _half_step_text(raw) * mult, "pct": pct})
    return values, years


def _period(text: str, said_on: date, years: list[int]) -> Period | None:
    if m := MONTH_YEAR.search(text):
        return Period(int(m.group(2)), MONTHS[m.group(1).lower()])
    if m := QUARTER.search(text):
        q = int(m.group(1)) if m.group(1) else ["first", "second", "third", "fourth"].index(m.group(2).lower()) + 1
        return Period(int(m.group(3)), quarter=q)
    low = text.lower()
    if "last month" in low:
        if said_on.month > 1:
            return Period(said_on.year, said_on.month - 1)
        return Period(said_on.year - 1, 12)
    if "last year" in low:
        return Period(said_on.year - 1)
    if "this year" in low:
        return Period(said_on.year)
    return Period(years[0]) if years else None


def _comparator(low: str) -> str:
    if re.search(r"\b(over|more than|above|at least|exceeds?|exceeded|greater than)\b", low):
        return "over"
    if re.search(r"\b(under|less than|below|fewer than|at most)\b", low):
        return "under"
    if re.search(r"\b(nearly|almost|close to|approaching)\b", low):
        return "nearly"
    return "about"


def parse(text: str, said_on: date, catalog: Catalog) -> Claim:
    low = text.lower()
    claim = Claim(text=text, said_on=said_on, parser="rules", comparator=_comparator(low))
    city = catalog.find_city(text)
    metric = catalog.match_metric(text, city)
    if metric is None:
        claim.notes.append("No supported statistic recognized in the claim.")
        return claim
    claim.metric_id = metric.id
    if metric.needs_city:
        claim.city = city
    else:
        for state in sorted(STATES, key=len, reverse=True):
            if re.search(rf"(?<!\w){re.escape(state.lower())}(?!\w)", low):
                claim.state = state
                break

    values, years = _numbers(text)
    claim.period = _period(text, said_on, years)
    percent_like = metric.kind in ("rate", "index") or metric.scale in ("fraction", "percent")
    pick = next((v for v in values if v["pct"]), None) if percent_like else None
    pick = pick or (values[0] if values else None)
    if pick is None:
        claim.notes.append("No number found in the claim.")
        return claim
    claim.value, claim.precision = pick["value"], pick["step"]

    if metric.kind == "index":
        claim.measure = "yoy_pct"
    elif "change" in metric.measures and CHANGE_DOWN.search(low):
        claim.measure, claim.value = "change", -abs(claim.value)
    elif "change" in metric.measures and CHANGE_UP.search(low):
        claim.measure = "change"
    elif pick["pct"] and "yoy_pct" in metric.measures and DIRECTION.search(low) and not TO_LEVEL.search(low):
        claim.measure = "yoy_pct"
        if NEGATIVE.search(low):
            claim.value = -abs(claim.value)
    else:
        claim.measure = metric.default_measure
    return claim

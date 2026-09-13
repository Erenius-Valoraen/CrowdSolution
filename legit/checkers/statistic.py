"""Official statistics, checked against what was published at the time. Wraps the stats engine."""
from __future__ import annotations

import re

from ..models import Evidence, Extraction, Finding, Item
from ..stats import verdict as sv
from ..stats.engine import check as check_claim
from ..stats.formatting import fmt
from ..stats.models import Claim, Period, half_step

STATUS = {
    sv.ACCURATE: "ok",
    sv.MATCHES_TODAY: "ok",
    sv.OUTDATED_WHEN_SAID: "caution",
    sv.MISMATCH_TODAY: "caution",
    sv.WRONG: "caution",
    sv.NOT_YET_PUBLISHED: "unverified",
}


MONTHLY = re.compile(r"\b(for the month|month[- ]over[- ]month|m/m|monthly|from the (?:prior|previous) month)\b", re.I)
MISREAD_RATIO = 8  # official figures this far from the claim usually mean a different measure was read, not a wrong claim


# Our statistics are US series. A claim about Canada can't be settled with them, so the web check handles it.
NON_US = re.compile(r"\b(canada|canadian|canadians|ontario|quebec|british columbia|alberta|manitoba|saskatchewan|nova scotia|"
                    r"toronto|vancouver|montreal|ottawa|calgary|edmonton|waterloo|statistics canada|statcan|bank of canada|"
                    r"cad|u\.?k\.?|britain|british|england|australia|india)\b", re.I)


def looks_misread(claimed: float, official: float | None, measure: str | None, text: str) -> bool:
    """True when the claim was probably matched to the wrong measure, e.g. a monthly 0.3% raise checked against
    the yearly change, or a monthly job gain checked against total jobs. The web check handles those instead."""
    if measure == "yoy_pct" and MONTHLY.search(text or ""):
        return True
    if official is None or claimed <= 0 or official <= 0:
        return False
    return max(claimed, official) / min(claimed, official) >= MISREAD_RATIO


SUBGROUP = re.compile(
    r"\b(recent grads?|graduates|majors?|degree holders|nurs\w*|engineer\w*|teachers?|developers?|doctors?|industry|"
    r"industries|sector|occupations?|construction|among|for (?:young|black|white|hispanic|asian|women|men|teens?)"
    r"|in (?:tech|healthcare|construction|retail|manufacturing))\b", re.I)


def check(item: Item, ext: Extraction) -> Finding | None:
    if item.kind != "statistic":
        return None
    if SUBGROUP.search(item.text or ""):
        return None  # a figure for one group isn't the national statistic; let the web check it
    if NON_US.search(item.text or "") or ext.location.is_canada:
        return None  # US series can't settle a claim about another country; let the web check it
    from ..extract import stats_catalog  # local import avoids a cycle at module load
    catalog = stats_catalog()
    d = item.data
    metric = catalog.get(d.get("metric_id"))
    if metric is None or d.get("value") is None:
        return None
    try:
        value = float(d["value"])
        period = Period.from_dict(d.get("period"))
    except (TypeError, ValueError):
        return None
    claim = Claim(text=item.text, said_on=ext.said_on, metric_id=metric.id, measure=d.get("measure"), value=value,
                  precision=half_step(value), period=period,
                  state=d.get("state") if metric.state_variable else None,
                  city=catalog.canonical_city(d.get("city")) if metric.needs_city else None,
                  comparator=d.get("comparator") if d.get("comparator") in ("about", "over", "under", "nearly") else "about")
    res = check_claim(claim, catalog)
    status = STATUS.get(res.verdict)
    if status is None or res.measure is None:
        return None
    official = next((fig.value for fig in (res.then, res.fallback, res.latest) if fig is not None and fig.value is not None), None)
    if status != "ok" and looks_misread(value, official, res.measure, item.text):
        return None

    evidence = []
    figures = {}
    for key, label, fig in (("when_said", "Published by the date seen", res.then), ("revised", "Same period, revised", res.revised),
                            ("latest", "Latest available", res.latest), ("today", "Today's data", res.fallback)):
        if fig is not None:
            pub = f", published {fig.published}" if fig.published else ""
            evidence.append(Evidence(f"{metric.agency} (via Snowflake Public Data)",
                                     f"{label}: {fmt(metric, res.measure, fig.value)} for {fig.label}{pub}"))
            figures[key] = {"value": fmt(metric, res.measure, fig.value), "period": fig.label,
                            "published": fig.published.isoformat() if fig.published else None}
    data = {"type": "statistic", "label": metric.label, "where": res.where, "agency": metric.agency,
            "verdict": res.verdict, "claimed": item.text, "figures": figures}
    summary = f"{res.verdict.capitalize()}."
    if res.notes:
        summary += " " + " ".join(res.notes)
    if ext.location.is_canada:
        summary += " Note: this is a US statistic."
    # US data can't settle a claim made in a Canadian context, so also look it up online.
    return Finding(item, status, f"{metric.label}: {res.where}", summary, "statistic", evidence,
                   web_followup=ext.location.is_canada, data=data)

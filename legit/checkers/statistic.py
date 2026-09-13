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


SUBGROUP = re.compile(
    r"\b(recent grads?|graduates|majors?|degree holders|nurs\w*|engineer\w*|teachers?|developers?|doctors?|industry|"
    r"industries|sector|occupations?|construction|among|for (?:young|black|white|hispanic|asian|women|men|teens?)"
    r"|in (?:tech|healthcare|construction|retail|manufacturing))\b", re.I)


def check(item: Item, ext: Extraction) -> Finding | None:
    if item.kind != "statistic":
        return None
    if SUBGROUP.search(item.text or ""):
        return None  # a figure for one group isn't the national statistic; let the web check it
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
    return Finding(item, status, f"{metric.label}: {res.where}", summary, "statistic", evidence, data=data)

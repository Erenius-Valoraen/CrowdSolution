"""Check one parsed claim against the database."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta

from . import lookup, measures, verdict
from .catalog import Catalog, Metric
from .models import Claim, Figure


@dataclass
class Result:
    claim: Claim
    metric: Metric | None = None
    measure: str | None = None
    where: str = ""
    series: str = ""
    then: Figure | None = None
    revised: Figure | None = None
    latest: Figure | None = None
    fallback: Figure | None = None
    history_from: date | None = None
    verdict: str = verdict.CANT_VERIFY
    notes: list[str] = field(default_factory=list)


def check(claim: Claim, catalog: Catalog) -> Result:
    res = Result(claim=claim, notes=list(claim.notes))
    metric = catalog.get(claim.metric_id)
    if metric is None:
        res.notes.append("Supported statistics:\n" + catalog.describe())
        return res
    res.metric = metric
    if claim.value is None:
        return res

    measure = claim.measure if claim.measure in metric.measures else metric.default_measure
    if claim.measure and claim.measure != measure:
        res.notes.append(f"'{claim.measure}' isn't available for {metric.label}; checked {measure} instead.")
    res.measure = measure

    variable, geo_id, city, where = metric.variable, metric.geo, None, "United States"
    if metric.needs_city:
        if not claim.city:
            res.notes.append(f"Name a city with crime data: {', '.join(catalog.cities)}.")
            return res
        city, geo_id, where = claim.city, None, claim.city
    elif claim.state:
        state_geo = lookup.state_geo_id(claim.state) if metric.state_variable else None
        if state_geo:
            variable, geo_id, where = metric.state_variable, state_geo, claim.state
        elif metric.state_variable:
            res.notes.append(f"Couldn't find state '{claim.state}'; used the national figure.")
        else:
            res.notes.append(f"{metric.label} is national only; used the US figure, not {claim.state}.")
    res.where, res.series = where, f"{metric.table}.{variable}"

    anchor = claim.period.start() if claim.period else claim.said_on
    since = min(anchor, claim.said_on) - timedelta(days=800)

    res.history_from = lookup.history_start(metric, variable, geo_id, city)
    current = measures.compute_series(
        metric, measure, lookup.observations(metric, variable, geo_id, city, None, since))
    res.latest = measures.select(current, None)

    known: list[Figure] = []
    if res.history_from and claim.said_on >= res.history_from:
        known = measures.compute_series(
            metric, measure, lookup.observations(metric, variable, geo_id, city, claim.said_on, since))
        res.then = measures.select(known, claim.period)
        if res.then:
            res.revised = measures.same_period(current, res.then.period_end)
    else:
        res.fallback = measures.select(current, claim.period, before=None if claim.period else claim.said_on)

    known_before = [f for f in known if res.then and f.period_end < res.then.period_end]
    res.verdict, notes = verdict.decide(
        claim, metric, measure, then=res.then, revised=res.revised, latest=res.latest,
        known_before=known_before, fallback=res.fallback, history_from=res.history_from,
        data_end=catalog.data_end)
    res.notes.extend(notes)
    return res

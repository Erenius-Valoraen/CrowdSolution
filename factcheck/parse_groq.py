"""Groq-backed claim parser, used automatically when GROQ_API_KEY is set (environment or repo .env).

Groq exposes an OpenAI-compatible chat completions API. The model only extracts structured claims
from text. Every number it returns is checked against the database, never trusted on its own."""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from datetime import date

from . import config
from .catalog import Catalog
from .models import Claim, Period, half_step

API_URL = "https://api.groq.com/openai/v1/chat/completions"


class GroqError(RuntimeError):
    pass


def available() -> bool:
    return bool(os.environ.get("GROQ_API_KEY"))


def system_prompt(catalog: Catalog) -> str:
    lines = []
    for m in catalog.metrics.values():
        line = f'- "{m.id}": {m.label}. measures: {", ".join(m.measures)} (default {m.default_measure}).'
        if m.needs_city:
            line += " Requires a city."
        if m.state_variable:
            line += " Supports US states."
        lines.append(line)
    metrics = "\n".join(lines)
    return f"""You extract checkable statistical claims from text for a fact-checking tool.
Return JSON only, shaped as:
{{"claims": [{{"metric_id": str, "measure": str, "value": number,
  "period": {{"year": int, "month": int or null, "quarter": int or null}} or null,
  "state": str or null, "city": str or null, "comparator": "about" | "over" | "under" | "nearly"}}]}}

Supported metrics. Use these ids exactly, and skip claims that fit none:
{metrics}

Cities with crime data: {", ".join(catalog.cities)}.

Measures:
- level: the stated value itself. "unemployment is 4.1%" -> 4.1. "the debt is $39 trillion" -> 39000000000000.
- change: change from the previous period. "added 200,000 jobs" -> 200000. "lost 50,000 jobs" -> -50000.
- yoy_pct: percent change from a year earlier. "inflation is 3%" -> 3. "homicides fell 20%" -> -20.
- annual_total: a yearly count. "Chicago had 568 homicides in 2024" -> 568.

Rules:
- value uses display units: percentages as percent numbers (4.1, not 0.041); counts and dollars as full numbers.
- period is the time the statistic describes, only if stated or clearly implied. Resolve "last year" and
  "last month" using the date said. Otherwise null.
- comparator: "over" for over, more than, at least; "under" for under, less than; "nearly" for nearly, almost; else "about".
- state only for a named US state. city only for one of the listed cities.
- If nothing is checkable, return {{"claims": []}}."""


def parse(text: str, said_on: date, catalog: Catalog) -> list[Claim]:
    key = os.environ.get("GROQ_API_KEY")
    if not key:
        raise GroqError("GROQ_API_KEY is not set")
    body = {
        "model": config.GROQ_MODEL,
        "temperature": 0,
        "response_format": {"type": "json_object"},
        "messages": [
            {"role": "system", "content": system_prompt(catalog)},
            {"role": "user", "content": f"Date said: {said_on.isoformat()}\nText: {text}"},
        ],
    }
    req = urllib.request.Request(API_URL, data=json.dumps(body).encode("utf-8"), method="POST", headers={
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
        "User-Agent": "crowdsolution-factcheck/0.1",
    })
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            payload = json.load(resp)
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", "replace")[:300]
        raise GroqError(f"HTTP {e.code}: {detail}") from None
    except (urllib.error.URLError, TimeoutError) as e:
        raise GroqError(f"network error: {e}") from None

    try:
        content = json.loads(payload["choices"][0]["message"]["content"])
    except (KeyError, IndexError, TypeError, json.JSONDecodeError) as e:
        raise GroqError(f"unexpected response: {e}") from None

    claims = []
    for c in content.get("claims", []):
        metric = catalog.get(c.get("metric_id"))
        if metric is None or c.get("value") is None:
            continue
        try:
            value = float(c["value"])
            period = Period.from_dict(c.get("period"))
        except (TypeError, ValueError):
            continue
        measure = c.get("measure") if c.get("measure") in metric.measures else metric.default_measure
        comparator = c.get("comparator") if c.get("comparator") in ("about", "over", "under", "nearly") else "about"
        claims.append(Claim(
            text=text, said_on=said_on, metric_id=metric.id, measure=measure, value=value,
            precision=half_step(value), period=period,
            state=c.get("state") if metric.state_variable else None,
            city=catalog.canonical_city(c.get("city")) if metric.needs_city else None,
            comparator=comparator, parser=f"groq:{config.GROQ_MODEL}"))
    return claims

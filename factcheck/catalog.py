"""Curated statistics the concept can check, loaded from headline_series.json."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

PATH = Path(__file__).with_name("headline_series.json")


@dataclass
class Metric:
    id: str
    label: str
    aliases: list[str]
    source: str                 # pit | vintage | city_crime
    table: str                  # table prefix, e.g. FINANCIAL_ECONOMIC_INDICATORS
    variable: str
    scale: str                  # fraction (0.043 = 4.3%) | percent (4.3 = 4.3%) | raw
    kind: str                   # rate | count | usd | index | score
    frequency: str              # daily | weekly | monthly | quarterly | annual
    measures: list[str]
    default_measure: str
    agency: str
    geo: str = "country/USA"
    state_variable: str | None = None
    unit_label: str = ""
    note: str = ""
    extra: dict = field(default_factory=dict)

    @property
    def needs_city(self) -> bool:
        return self.source == "city_crime"


def _has_phrase(text: str, phrase: str) -> bool:
    return re.search(rf"(?<!\w){re.escape(phrase)}(?!\w)", text) is not None


class Catalog:
    def __init__(self, path: Path = PATH):
        raw = json.loads(path.read_text(encoding="utf-8"))
        self.data_end = date.fromisoformat(raw["data_end"])
        self.cities: dict[str, list[str]] = raw["cities"]
        self.metrics: dict[str, Metric] = {}
        known = set(Metric.__dataclass_fields__)
        for m in raw["metrics"]:
            fields = {k: v for k, v in m.items() if k in known}
            fields["extra"] = {k: v for k, v in m.items() if k not in known}
            self.metrics[m["id"]] = Metric(**fields)

    def get(self, metric_id: str | None) -> Metric | None:
        return self.metrics.get(metric_id or "")

    def canonical_city(self, name: str | None) -> str | None:
        if not name:
            return None
        low = name.lower().strip()
        for city, aliases in self.cities.items():
            if low == city.lower() or low in aliases:
                return city
        return None

    def find_city(self, text: str) -> str | None:
        low = text.lower()
        best, best_len = None, 0
        for city, aliases in self.cities.items():
            for a in aliases + [city.lower()]:
                if len(a) > best_len and _has_phrase(low, a):
                    best, best_len = city, len(a)
        return best

    def match_metric(self, text: str, city: str | None) -> Metric | None:
        """Pick the metric whose longest alias appears in the text.

        Crime aliases prefer city data when a city is named, national FBI data otherwise."""
        low = text.lower()
        best, best_score = None, 0
        for m in self.metrics.values():
            for a in m.aliases:
                if _has_phrase(low, a):
                    score = len(a) * 10
                    if m.extra.get("crime") and (city is not None) == m.needs_city:
                        score += 5
                    if score > best_score:
                        best, best_score = m, score
        return best

    def describe(self) -> str:
        return "\n".join(f"  {m.id:26} {m.label}" for m in self.metrics.values())

"""Choose a parser: Groq when a key is available, the rule-based parser otherwise."""
from __future__ import annotations

from datetime import date

from . import parse_groq, parse_rules
from .catalog import Catalog
from .models import Claim


def parse_claims(text: str, said_on: date, catalog: Catalog, backend: str = "auto") -> tuple[list[Claim], list[str]]:
    """Return (claims, notes). backend is auto, rules, or groq."""
    notes: list[str] = []
    if backend == "groq" and not parse_groq.available():
        raise parse_groq.GroqError("GROQ_API_KEY is not set")
    if backend in ("auto", "groq") and parse_groq.available():
        try:
            claims = parse_groq.parse(text, said_on, catalog)
            if claims:
                return claims, notes
            notes.append("Groq found no checkable statistic; tried the rule-based parser.")
        except parse_groq.GroqError as e:
            if backend == "groq":
                raise
            notes.append(f"Groq failed ({e}); used the rule-based parser.")
    return [parse_rules.parse(text, said_on, catalog)], notes

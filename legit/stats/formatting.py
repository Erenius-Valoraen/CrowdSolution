"""Human-readable numbers, shared by the terminal output and verdict notes."""
from __future__ import annotations

from .catalog import Metric


def fmt(metric: Metric, measure: str, v: float) -> str:
    unit = f" {metric.unit_label}" if metric.unit_label else ""
    if measure == "yoy_pct":
        return f"{v:+.2f}% vs a year earlier"
    if metric.kind == "rate" or metric.scale in ("fraction", "percent"):
        return f"{v:.2f}%{unit}"
    if metric.kind == "score":
        return f"{v:.1f}{unit}"
    sign = "+" if measure == "change" and v > 0 else ("-" if v < 0 else "")
    prefix = "$" if metric.kind == "usd" else ""
    a = abs(v)
    if a >= 1e12:
        body = f"{a / 1e12:.2f} trillion"
    elif a >= 1e9:
        body = f"{a / 1e9:.2f} billion"
    elif a >= 1e6:
        body = f"{a / 1e6:.3f} million"
    elif metric.kind == "usd" and a < 1000:
        body = f"{a:,.2f}"
    else:
        body = f"{a:,.0f}"
    return f"{sign}{prefix}{body}{unit}"

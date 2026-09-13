"""What problems do people report with this financial company? CFPB consumer complaints."""
from __future__ import annotations

from datetime import date

from .. import db
from ..models import Evidence, Extraction, Finding, Item
from .common import like_pattern, name_matches

FINANCIAL_TYPES = {"bank", "credit_union", "lender", "loan_servicer", "credit_card", "investment_adviser"}
DATA_END = date(2026, 6, 14)
SOURCE = "Consumer Financial Protection Bureau complaint database (via Snowflake Public Data)"
HIGH_VOLUME = 1000
MIN_TIMELY_PCT = 90


def check(item: Item, ext: Extraction) -> Finding | None:
    if item.kind != "entity" or ext.location.is_canada:
        return None
    etype = (item.data.get("entity_type") or "").lower()
    if etype not in FINANCIAL_TYPES and not (ext.context == "finance" and etype in ("company", "other")):
        return None
    name = item.data.get("name") or ""
    pattern = like_pattern(name)
    if not pattern:
        return None
    rows = db.query(f"""
        SELECT COMPANY, COUNT(*) AS N,
               COUNT_IF(TIMELY_RESPONSE::VARCHAR ILIKE 'true') AS TIMELY,
               MODE(ISSUE) AS TOP_ISSUE, MODE(PRODUCT) AS TOP_PRODUCT
        FROM {db.PUBLIC}.FINANCIAL_CFPB_COMPLAINT
        WHERE COMPANY ILIKE %(p)s AND DATE_RECEIVED > DATEADD(month, -12, %(end)s::DATE)
        GROUP BY COMPANY ORDER BY N DESC LIMIT 5""", {"p": pattern, "end": DATA_END.isoformat()})
    rows = [r for r in rows if name_matches(name, r["COMPANY"])] or rows[:1]
    if not rows:
        return None
    r = rows[0]
    n, timely = int(r["N"]), int(r["TIMELY"])
    pct = round(100 * timely / n) if n else 0
    ev = Evidence(SOURCE, f"{r['COMPANY']}: {n:,} complaints in the 12 months to {DATA_END}; most about "
                          f"{r['TOP_PRODUCT']} ({r['TOP_ISSUE']}); {pct}% answered on time")
    # Volume alone isn't a warning sign: big banks get tens of thousands of complaints. Slow responses are.
    status = "caution" if n >= 50 and pct < MIN_TIMELY_PCT else "info"
    summary = (f"{r['COMPANY']} received {n:,} consumer complaints in the last year of our data, most often about "
               f"\"{r['TOP_ISSUE']}\". {pct}% got a timely response.")
    if status == "caution":
        summary += " That response rate is low; read recent complaints before you sign up."
    elif n >= HIGH_VOLUME:
        summary += " Large companies get many complaints; the most common issue is what to watch for."
    data = {"type": "complaints", "company": r["COMPANY"], "complaints": n, "timely_pct": pct,
            "top_issue": r["TOP_ISSUE"], "top_product": r["TOP_PRODUCT"], "period_end": DATA_END.isoformat()}
    return Finding(item, status, f"{name}: complaint history", summary, "reputation", [ev], data=data)

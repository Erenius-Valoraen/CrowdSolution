"""Is this price normal? Rent, wages, and interest rates compared with official benchmarks."""
from __future__ import annotations

from .. import db
from ..models import Evidence, Extraction, Finding, Item
from ..stats import lookup as stats_lookup
from .common import province_name, us_state_name

SRC_RENT = "US Census Bureau, American Community Survey 1-year median gross rent (via Snowflake Public Data)"
SRC_WAGE = "Bureau of Labor Statistics, average hourly earnings, all private employees (via Snowflake Public Data)"
SRC_RATES = "Federal Reserve interest rate data (via Snowflake Public Data)"
SRC_STATCAN = "Statistics Canada, Consumer Price Index: Rent (via Snowflake Public Data)"

HOURS_PER_YEAR = 2080


# --- Pure classification rules, unit tested ---

def classify_rent(amount: float, median: float) -> tuple[str, float]:
    ratio = amount / median
    if ratio < 0.5:
        return "red_flag", ratio
    if ratio < 0.7:
        return "caution", ratio
    if ratio > 1.6:
        return "caution", ratio
    return "ok", ratio


def classify_wage(hourly: float, average: float, entry_level: bool | None) -> tuple[str, float]:
    ratio = hourly / average
    if entry_level and ratio >= 1.25:
        return "caution", ratio
    if ratio >= 3:
        return "caution", ratio
    return "info", ratio


def classify_savings(apy: float, policy_rate: float) -> str:
    if apy > policy_rate + 2.0:
        return "red_flag"
    if apy > policy_rate + 0.75:
        return "caution"
    return "ok"


def classify_loan(apr: float, average: float) -> str:
    if apr > 36:
        return "red_flag"
    if apr > average * 1.35:
        return "caution"
    return "ok"


# --- Checker ---

def check(item: Item, ext: Extraction) -> Finding | None:
    if item.kind != "price":
        return None
    d = item.data
    category = (d.get("category") or "").lower()
    amount = float(d["amount"])
    if category == "rent":
        return _rent_canada(item, ext) if ext.location.is_canada else _rent_us(item, ext, amount)
    if ext.location.is_canada:
        return None
    if category in ("hourly_wage", "salary"):
        # Pay benchmarks only make sense for an offer made to the student, not for "surgeons earn $400k" claims.
        return _wage(item, ext, amount) if ext.context == "job" else None
    if category == "savings_rate":
        return _savings(item, amount)
    if category in ("loan_rate", "credit_card_rate"):
        return _loan(item, amount, category)
    return None


def _latest(table: str, variable: str, geo: str) -> dict | None:
    rows = db.query(f"""
        SELECT DATE, VALUE FROM {db.PUBLIC}.{table}
        WHERE VARIABLE = %(v)s AND GEO_ID = %(g)s ORDER BY DATE DESC LIMIT 1""", {"v": variable, "g": geo})
    return rows[0] if rows else None


def _rent_us(item: Item, ext: Extraction, amount: float) -> Finding | None:
    if (item.data.get("unit") or "per_month") != "per_month":
        return None
    beds = item.data.get("bedrooms")
    bedrooms = "all" if beds is None else ("5+" if int(beds) >= 5 else str(int(beds)))
    state = us_state_name(ext.location.region)
    state_geo = stats_lookup.state_geo_id(state) if state else None
    rows = db.query("""
        SELECT GEO_NAME, LEVEL, GEO_ID, STATE_GEO_ID, DATE, MEDIAN_RENT_USD
        FROM CROWDSOLUTION.BENCHMARKS.RENT
        WHERE BEDROOMS = %(b)s AND (
              (LEVEL = 'City' AND LOWER(GEO_NAME) = LOWER(%(city)s) AND (%(st)s IS NULL OR STATE_GEO_ID = %(st)s))
           OR (LEVEL = 'State' AND GEO_ID = %(st)s)
           OR LEVEL = 'Country')
        QUALIFY ROW_NUMBER() OVER (PARTITION BY LEVEL, GEO_ID ORDER BY DATE DESC) = 1""",
                    {"b": bedrooms, "city": ext.location.city or "", "st": state_geo})
    cities = [r for r in rows if r["LEVEL"] == "City"]
    pick = (cities[0] if len(cities) == 1 else None) or next((r for r in rows if r["LEVEL"] == "State"), None) \
        or next((r for r in rows if r["LEVEL"] == "Country"), None)
    if pick is None:
        return None
    median = float(pick["MEDIAN_RENT_USD"])
    status, ratio = classify_rent(amount, median)
    place = pick["GEO_NAME"] if pick["LEVEL"] != "Country" else "the US"
    size = "all rentals" if bedrooms == "all" else ("studios" if bedrooms == "0" else f"{bedrooms}-bedroom rentals")
    year = pick["DATE"].year
    summary = f"${amount:,.0f}/month is {ratio:.0%} of the {year} median for {size} in {place} (${median:,.0f})."
    if status == "red_flag":
        summary += " Rent far below the local norm is one of the most common signs of a rental scam."
    elif status == "caution" and ratio < 1:
        summary += " That's unusually cheap; ask why before paying anything."
    elif status == "caution":
        summary += " That's well above typical; compare other listings nearby."
    if len(cities) > 1:
        summary += f" Several cities are named {ext.location.city}; used the state figure."
    ev = Evidence(SRC_RENT, f"{place}, {size}, {year}: ${median:,.0f}/month")
    data = {"type": "rent", "amount": amount, "benchmark": median, "ratio": ratio, "place": place, "size": size,
            "year": year, "unit": "usd_month", "benchmark_label": f"Typical {size} in {place} ({year})"}
    return Finding(item, status, "Rent compared with local median", summary, "benchmark", [ev], data=data)


def _rent_canada(item: Item, ext: Extraction) -> Finding | None:
    province = province_name(ext.location.region, ext.location.city)
    if not province:
        return None
    geo = db.query(f"""
        SELECT GEO_ID FROM {db.PUBLIC}.GEOGRAPHY_INDEX
        WHERE LEVEL = 'State' AND GEO_ID LIKE 'wikidataId/%%' AND LOWER(GEO_NAME) = LOWER(%(n)s) LIMIT 1""", {"n": province})
    if not geo:
        return None
    rows = db.query(f"""
        SELECT t.DATE, t.VALUE
        FROM {db.PUBLIC}.CANADA_STATCAN_TIMESERIES t
        JOIN {db.PUBLIC}.CANADA_STATCAN_ATTRIBUTES a ON a.VARIABLE = t.VARIABLE
        WHERE a.VARIABLE_NAME = 'Consumer Price Index: Rent' AND t.GEO_ID = %(g)s
        QUALIFY ROW_NUMBER() OVER (PARTITION BY t.DATE ORDER BY t.VARIABLE) = 1
        ORDER BY t.DATE DESC LIMIT 13""", {"g": geo[0]["GEO_ID"]})
    if len(rows) < 13:
        return None
    latest, year_ago = rows[0], rows[12]
    change = 100 * (float(latest["VALUE"]) / float(year_ago["VALUE"]) - 1)
    month = latest["DATE"].strftime("%B %Y")
    summary = (f"Rents in {province} were {change:+.1f}% vs a year earlier as of {month}. Our data has no rent levels "
               "for Canadian cities, so the listed price itself is checked on the web.")
    ev = Evidence(SRC_STATCAN, f"{province} rent index {float(latest['VALUE']):.1f} in {month}, {change:+.1f}% year over year")
    data = {"type": "rent_trend", "province": province, "change_pct": change, "month": month,
            "amount": float(item.data.get("amount") or 0)}
    return Finding(item, "info", "Local rent trend", summary, "benchmark", [ev], web_followup=True, data=data)


def _wage(item: Item, ext: Extraction, amount: float) -> Finding | None:
    unit = item.data.get("unit") or "per_hour"
    hourly = amount if unit == "per_hour" else amount / HOURS_PER_YEAR if unit == "per_year" else \
        amount * 12 / HOURS_PER_YEAR if unit == "per_month" else amount * 52 / HOURS_PER_YEAR if unit == "per_week" else None
    if hourly is None:
        return None
    state = us_state_name(ext.location.region)
    state_geo = stats_lookup.state_geo_id(state) if state else None
    row, place = None, "the US"
    if state_geo:
        row, place = _latest("FINANCIAL_ECONOMIC_INDICATORS_TIMESERIES", "SMU0500000003.M", state_geo), state
    if row is None:
        row, place = _latest("FINANCIAL_ECONOMIC_INDICATORS_TIMESERIES", "CES0500000003.M_SA", "country/USA"), "the US"
    if row is None:
        return None
    average = float(row["VALUE"])
    status, ratio = classify_wage(hourly, average, item.data.get("entry_level"))
    month = row["DATE"].strftime("%B %Y")
    summary = f"${hourly:,.2f}/hour is {ratio:.1f}x the average hourly pay for all private jobs in {place} (${average:,.2f}, {month})."
    if status == "caution":
        summary += (" Pay this high for entry-level or no-experience work is a classic job-scam hook."
                    if item.data.get("entry_level") else " Unusually high pay is worth questioning.")
    ev = Evidence(SRC_WAGE, f"{place}, {month}: ${average:,.2f}/hour")
    data = {"type": "wage", "amount": hourly, "benchmark": average, "ratio": ratio, "place": place, "month": month,
            "unit": "usd_hour", "benchmark_label": f"Average pay, all private jobs in {place} ({month})",
            "entry_level": bool(item.data.get("entry_level"))}
    return Finding(item, status, "Pay compared with local average", summary, "benchmark", [ev], data=data)


def _savings(item: Item, apy: float) -> Finding | None:
    row = _latest("FINANCIAL_ECONOMIC_INDICATORS_TIMESERIES", "H15_RIFSPFF_N.M", "country/USA")
    if row is None:
        return None
    policy = float(row["VALUE"]) * 100
    status = classify_savings(apy, policy)
    month = row["DATE"].strftime("%B %Y")
    summary = f"A {apy:.2f}% savings rate compares with a {policy:.2f}% federal funds rate in {month}."
    if status == "red_flag":
        summary += " Banks can't sustainably pay far above the Fed's rate; offers like this are usually scams or carry hidden catches."
    elif status == "caution":
        summary += " That's on the high side; check that the institution is FDIC insured and read the conditions."
    ev = Evidence(SRC_RATES, f"Federal funds effective rate, {month}: {policy:.2f}%")
    data = {"type": "savings_rate", "amount": apy, "benchmark": policy, "ratio": apy / policy if policy else None,
            "month": month, "unit": "percent", "benchmark_label": f"Federal funds rate ({month})"}
    return Finding(item, status, "Savings rate compared with the Fed's rate", summary, "benchmark", [ev], data=data)


def _loan(item: Item, apr: float, category: str) -> Finding | None:
    variable, label = (("G19_TERMS_RIFSPBCICC_N.M__NSA", "credit card plans")
                       if category == "credit_card_rate" else ("G19_TERMS_RIFLPBCIPLM24_N.M__NSA", "24-month personal loans"))
    row = _latest("FINANCIAL_ECONOMIC_INDICATORS_TIMESERIES", variable, "country/USA")
    if row is None:
        return None
    average = float(row["VALUE"]) * 100
    status = classify_loan(apr, average)
    month = row["DATE"].strftime("%B %Y")
    summary = f"A {apr:.2f}% rate compares with a {average:.2f}% average for {label} at US banks ({month})."
    if status == "red_flag":
        summary += " Rates above 36% are considered predatory and are capped in many states."
    elif status == "caution":
        summary += " That's well above average; compare offers from a bank or credit union first."
    ev = Evidence(SRC_RATES, f"Average rate on {label}, {month}: {average:.2f}%")
    data = {"type": category, "amount": apr, "benchmark": average, "ratio": apr / average if average else None,
            "month": month, "unit": "percent", "benchmark_label": f"Average for {label} ({month})"}
    return Finding(item, status, "Interest rate compared with average", summary, "benchmark", [ev], data=data)

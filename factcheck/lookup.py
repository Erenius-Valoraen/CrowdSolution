"""Database lookups.

Every value is a bound parameter. Table names come only from the curated catalog, never from user text."""
from __future__ import annotations

from datetime import date

from . import db
from .catalog import Metric
from .models import Obs

# A row "was known on day D" if its validity window covers the end of that day.
# With asof NULL, only the current (never replaced) rows match.
_WINDOW = """
  (   (%(asof)s IS NULL AND _EFFECTIVE_END_TIMESTAMP IS NULL)
   OR (    _EFFECTIVE_START_TIMESTAMP <= %(asof)s::TIMESTAMP_TZ
       AND (_EFFECTIVE_END_TIMESTAMP IS NULL OR _EFFECTIVE_END_TIMESTAMP > %(asof)s::TIMESTAMP_TZ)))
"""


def _asof(d: date | None) -> str | None:
    return None if d is None else f"{d.isoformat()} 23:59:59"


def observations(metric: Metric, variable: str, geo_id: str | None, city: str | None,
                 as_of: date | None, since: date) -> list[Obs]:
    """Data points for a series as they stood on `as_of`. None means today's revised data."""
    p = {"v": variable, "g": geo_id, "city": city, "since": since.isoformat(), "asof": _asof(as_of),
         "asof_date": None if as_of is None else as_of.isoformat()}

    if metric.source == "pit":
        rows = db.query(f"""
            SELECT DATE, VALUE, _EFFECTIVE_START_TIMESTAMP::DATE AS PUBLISHED
            FROM {db.PUBLIC}.{metric.table}_TIMESERIES_PIT
            WHERE VARIABLE = %(v)s AND GEO_ID = %(g)s AND DATE >= %(since)s AND {_WINDOW}
            QUALIFY ROW_NUMBER() OVER (PARTITION BY DATE ORDER BY _EFFECTIVE_START_TIMESTAMP DESC) = 1
            ORDER BY DATE""", p)
        return [Obs(r["DATE"], float(r["VALUE"]), r["PUBLISHED"]) for r in rows if r["VALUE"] is not None]

    if metric.source == "vintage":
        rows = db.query(f"""
            SELECT DATE, VALUE, RELEASE_DATE AS PUBLISHED
            FROM {db.PUBLIC}.FINANCIAL_ECONOMIC_INDICATORS_TIMESERIES_VINTAGE
            WHERE VARIABLE = %(v)s AND GEO_ID = %(g)s AND DATE >= %(since)s
              AND (%(asof_date)s IS NULL OR RELEASE_DATE <= %(asof_date)s::DATE)
            QUALIFY ROW_NUMBER() OVER (PARTITION BY DATE ORDER BY RELEASE_DATE DESC) = 1
            ORDER BY DATE""", p)
        return [Obs(r["DATE"], float(r["VALUE"]), r["PUBLISHED"]) for r in rows if r["VALUE"] is not None]

    if metric.source == "city_crime":
        p["since"] = date(since.year, 1, 1).isoformat()
        rows = db.query(f"""
            SELECT DATE_FROM_PARTS(YEAR(DATE), 12, 31) AS PERIOD_END, SUM(VALUE) AS VALUE,
                   MAX(_EFFECTIVE_START_TIMESTAMP)::DATE AS PUBLISHED, MAX(DATE) AS LAST_DAY
            FROM {db.PUBLIC}.URBAN_CRIME_TIMESERIES_PIT
            WHERE CITY = %(city)s AND VARIABLE = %(v)s AND DATE >= %(since)s AND {_WINDOW}
            GROUP BY 1
            ORDER BY 1""", p)
        return [Obs(r["PERIOD_END"], float(r["VALUE"]), r["PUBLISHED"],
                    complete=(r["LAST_DAY"].month == 12 and r["LAST_DAY"].day >= 28)) for r in rows]

    raise ValueError(f"unknown source {metric.source}")


def history_start(metric: Metric, variable: str, geo_id: str | None, city: str | None) -> date | None:
    """The first date we have a record of what this series looked like."""
    p = {"v": variable, "g": geo_id, "city": city}
    if metric.source == "pit":
        sql = f"""SELECT MIN(_EFFECTIVE_START_TIMESTAMP)::DATE AS D FROM {db.PUBLIC}.{metric.table}_TIMESERIES_PIT
                  WHERE VARIABLE = %(v)s AND GEO_ID = %(g)s"""
    elif metric.source == "vintage":
        sql = f"""SELECT MIN(RELEASE_DATE) AS D FROM {db.PUBLIC}.FINANCIAL_ECONOMIC_INDICATORS_TIMESERIES_VINTAGE
                  WHERE VARIABLE = %(v)s AND GEO_ID = %(g)s"""
    else:
        sql = f"""SELECT MIN(_EFFECTIVE_START_TIMESTAMP)::DATE AS D FROM {db.PUBLIC}.URBAN_CRIME_TIMESERIES_PIT
                  WHERE CITY = %(city)s AND VARIABLE = %(v)s"""
    rows = db.query(sql, p)
    return rows[0]["D"] if rows else None


def state_geo_id(state_name: str) -> str | None:
    rows = db.query(f"""
        SELECT GEO_ID FROM {db.PUBLIC}.GEOGRAPHY_INDEX
        WHERE LEVEL = 'State' AND GEO_ID LIKE 'geoId/%%' AND LOWER(GEO_NAME) = LOWER(%(n)s)
        LIMIT 1""", {"n": state_name})
    return rows[0]["GEO_ID"] if rows else None

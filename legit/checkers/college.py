"""Colleges and majors: admissions, cost, graduation, earnings, and debt from the US College Scorecard,
plus research output from OpenAlex for any university, including Canadian ones."""
from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path

from .. import db
from ..models import Evidence, Extraction, Finding, Item
from ..stats.models import half_step

SRC_SCORECARD = "US Department of Education, College Scorecard, most recent cohorts (via Snowflake Marketplace)"
SRC_OPENALEX = "OpenAlex research catalog (via Snowflake Public Data)"
BENCH = "CROWDSOLUTION.BENCHMARKS"
# Hand-curated official figures for Ontario universities (Scorecard is US-only). See the file for sources and dates.
CURATED_PATH = Path(__file__).resolve().parent.parent / "data" / "ontario_universities.json"
CURATED_LABELS = {
    "earnings_2yr_median": ("Median graduate earnings 2 years after graduating", "usd"),
    "employment_related_rate": ("Graduates employed in a related field", "percent"),
    "graduation_rate": ("Graduation rate", "percent"),
    "experiential_learning": ("Students with work-integrated learning", "percent"),
    "tuition_domestic": ("First-year computer science tuition, domestic", "usd"),
    "tuition_international": ("First-year computer science tuition, international", "usd"),
    "total_students": ("Total students", "count"),
    "undergrads": ("Undergraduate students", "count"),
    "coop_share": ("Students in co-op", "percent"),
}
# What a claim's metric maps to in the curated data.
CURATED_CLAIM_METRIC = {
    "median_earnings_6yr": "earnings_2yr_median", "median_earnings_10yr": "earnings_2yr_median",
    "program_earnings_1yr": "earnings_2yr_median", "program_earnings_4yr": "earnings_2yr_median",
    "program_earnings_5yr": "earnings_2yr_median", "graduation_rate": "graduation_rate",
    "tuition_in_state": "tuition_domestic", "net_price": "tuition_domestic", "cost_of_attendance": "tuition_domestic",
    "tuition_out_of_state": "tuition_international", "undergrad_enrollment": "total_students",
}
EARNINGS_WORDS = re.compile(r"\b(earn\w*|salar\w*|make|makes|paid|pay|income)\b", re.I)

# metric -> (column, unit, label). Rates are stored as fractions.
SCHOOL_METRICS = {
    "admission_rate": ("ADMISSION_RATE", "percent", "Admission rate"),
    "tuition_in_state": ("TUITION_IN_STATE", "usd", "In-state tuition and fees"),
    "tuition_out_of_state": ("TUITION_OUT_OF_STATE", "usd", "Out-of-state tuition and fees"),
    "cost_of_attendance": ("COST_OF_ATTENDANCE", "usd", "Average yearly cost of attendance"),
    "net_price": ("NET_PRICE", "usd", "Average yearly net price after aid"),
    "graduation_rate": ("GRADUATION_RATE", "percent", "Graduation rate within 6 years"),
    "retention_rate": ("RETENTION_RATE", "percent", "First-year retention rate"),
    "median_earnings_10yr": ("EARNINGS_10YR", "usd", "Median earnings 10 years after starting"),
    "median_earnings_6yr": ("EARNINGS_6YR", "usd", "Median earnings 6 years after starting"),
    "median_debt": ("MEDIAN_DEBT", "usd", "Median debt at graduation"),
    "undergrad_enrollment": ("UNDERGRADS", "count", "Undergraduate enrollment"),
    "sat_average": ("SAT_AVG", "count", "Average SAT score of admitted students"),
}
PROGRAM_METRICS = {
    "program_earnings_1yr": ("EARNINGS_1YR", "usd", "Median earnings 1 year after graduating"),
    "program_earnings_4yr": ("EARNINGS_4YR", "usd", "Median earnings 4 years after graduating"),
    "program_earnings_5yr": ("EARNINGS_5YR", "usd", "Median earnings 5 years after graduating"),
    "program_debt": ("MEDIAN_DEBT", "usd", "Median debt for graduates"),
}
METRICS = list(SCHOOL_METRICS) + list(PROGRAM_METRICS) + ["research_output", "general"]
CREDENTIAL_LEVELS = {"certificate": 1, "associate": 2, "bachelor": 3, "post_baccalaureate": 4, "master": 5,
                     "doctoral": 6, "professional": 7}
CANADIAN_ALIASES = {
    "uoft": "University of Toronto", "u of t": "University of Toronto", "toronto": "University of Toronto",
    "ubc": "University of British Columbia", "uwaterloo": "University of Waterloo", "waterloo": "University of Waterloo",
    "mcgill": "McGill University", "western": "Western University", "uwo": "Western University",
    "queens": "Queen's University", "mcmaster": "McMaster University", "mac": "McMaster University",
    "laurier": "Wilfrid Laurier University", "wlu": "Wilfrid Laurier University", "uottawa": "University of Ottawa",
    "tmu": "Toronto Metropolitan University", "ryerson": "Toronto Metropolitan University", "york": "York University",
    "ualberta": "University of Alberta", "ucalgary": "University of Calgary", "sfu": "Simon Fraser University",
    "guelph": "University of Guelph", "concordia": "Concordia University", "dal": "Dalhousie University",
}
PROGRAM_ALIASES = {"cs": "computer", "comp sci": "computer", "compsci": "computer", "computer science": "computer science",
                   "ece": "electrical", "ee": "electrical", "econ": "economics", "psych": "psychology", "bio": "biology",
                   "mech e": "mechanical", "mechanical engineering": "mechanical engineering", "poli sci": "political"}
STOPWORDS = {"the", "of", "at", "and", "in", "for", "main", "campus"}
PROGRAM_FILLER = {"major", "majors", "degree", "degrees", "program", "programs", "studies", "grads", "graduates"}
TIMING = re.compile(r"\b(after (?:graduat\w*|college|school)|out of (?:college|school)|graduat\w*|first job|starting|"
                    r"entry[- ]level|new grads?|recent grads?|right away|years? out|\d+\s*years?)\b", re.I)


# --- Pure helpers, unit tested ---

def normalize(name: str | None) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (name or "").lower()).strip()


def search_tokens(name: str | None) -> list[str]:
    return [t for t in normalize(name).split() if t not in STOPWORDS]


def like(tokens: list[str]) -> str | None:
    return "%" + "%".join(tokens) + "%" if tokens else None


def canonical_school(name: str | None) -> str | None:
    if not name:
        return None
    key = re.sub(r"[^a-z ]", "", name.lower()).strip()
    return CANADIAN_ALIASES.get(key, name.strip())


def program_tokens(program: str | None) -> list[str]:
    text = normalize(program)
    text = PROGRAM_ALIASES.get(text, text)
    return [t for t in text.split() if len(t) >= 3 and t not in PROGRAM_FILLER and t not in STOPWORDS]


def is_graduate_earnings_claim(text: str | None) -> bool:
    """"CS grads make $110k right out of school" can be checked against graduate earnings;
    "developers earn $131k" is a career salary, which Scorecard doesn't measure."""
    return bool(TIMING.search(text or ""))


def display(value, unit: str) -> str:
    if value is None:
        return "not reported"
    value = float(value)
    if unit == "percent":
        return f"{value * 100:.0f}%"
    if unit == "usd":
        return f"${value:,.0f}"
    return f"{value:,.0f}"


def display_claim(value: float, unit: str) -> str:
    if unit == "percent":
        return f"{value:g}%"
    if unit == "usd":
        return f"${value:,.0f}"
    return f"{value:,.0f}"


def compare_direction(a: float, b: float, direction: str, unit: str) -> bool:
    """Does school A's value really sit higher (or lower) than school B's? Near-ties don't count."""
    margin = 0.005 if unit == "percent" else 0.01 * max(abs(a), abs(b))
    return a > b + margin if direction == "higher" else a < b - margin


def matches(claimed: float, actual: float, unit: str, comparator: str = "about", precision: float | None = None) -> bool:
    """claimed is in display units (29 means 29%); actual is as stored (0.29 for rates)."""
    step = precision if precision is not None else half_step(claimed)
    if unit == "percent":
        actual = actual * 100
        tol, slack = max(1.0, min(step, 5.0)), 0.5
    else:
        tol, slack = max(0.03 * abs(claimed), min(step, 0.15 * abs(claimed))), 0.01 * abs(claimed)
    eps = 1e-9 * max(1.0, abs(claimed))
    if comparator == "over":
        return actual >= claimed - slack - eps
    if comparator == "under":
        return actual <= claimed + slack + eps
    if comparator == "nearly":
        return claimed - 2 * tol - eps <= actual <= claimed + slack + eps
    return abs(actual - claimed) <= tol + eps


# --- Lookups ---

def find_school(name: str) -> dict | None:
    """Exact name or alias first (UT Austin, MIT), then all words of the name, preferring the largest school."""
    exact = db.query(f"""SELECT * FROM {BENCH}.COLLEGES WHERE CONTAINS(SEARCH_NAMES, %(t)s)
                         ORDER BY UNDERGRADS DESC NULLS LAST LIMIT 1""", {"t": f"|{normalize(name)}|"})
    if exact:
        return exact[0]
    tokens = search_tokens(name)
    if not tokens:
        return None
    rows = db.query(f"""SELECT * FROM {BENCH}.COLLEGES WHERE SEARCH_NAMES ILIKE %(p)s
                        ORDER BY UNDERGRADS DESC NULLS LAST LIMIT 50""", {"p": like(tokens)})
    for r in rows:
        words = set(r["SEARCH_NAMES"].replace("|", " ").split())
        if all(t in words for t in tokens):
            return r
    return None


def find_program(unitid: int, program: str, credlev: int | None) -> dict | None:
    tokens = program_tokens(program)
    if not tokens:
        return None
    rows = db.query(f"""SELECT * FROM {BENCH}.COLLEGE_PROGRAMS
                        WHERE UNITID = %(u)s AND PROGRAM ILIKE %(p)s AND (%(c)s IS NULL OR CREDLEV = %(c)s)
                        ORDER BY (EARNINGS_1YR IS NOT NULL) DESC, GRADUATES DESC NULLS LAST LIMIT 1""",
                    {"u": unitid, "p": like(tokens), "c": credlev})
    return rows[0] if rows else None


def find_national_program(program: str, credlev: int | None) -> dict | None:
    tokens = program_tokens(program)
    if not tokens:
        return None
    rows = db.query(f"""SELECT * FROM {BENCH}.PROGRAM_NATIONAL
                        WHERE PROGRAM ILIKE %(p)s AND (%(c)s IS NULL OR CREDLEV = %(c)s)
                        ORDER BY SCHOOLS DESC LIMIT 1""", {"p": like(tokens), "c": credlev})
    return rows[0] if rows else None


def find_research(name: str) -> dict | None:
    tokens = search_tokens(name)
    if not tokens:
        return None
    rows = db.query(f"""SELECT INSTITUTION_NAME, INSTITUTION_CITY, WORKS_COUNT, WORKS_CITED_BY_COUNT, SUMMARY_STATS
                        FROM {db.PUBLIC}.OPENALEX_INSTITUTIONS_INDEX
                        WHERE INSTITUTION_TYPE = 'education' AND INSTITUTION_NAME ILIKE %(p)s
                        ORDER BY WORKS_COUNT DESC NULLS LAST LIMIT 10""", {"p": like(tokens)})
    for r in rows:
        if all(t in set(search_tokens(r["INSTITUTION_NAME"])) for t in tokens):
            return r
    return None


# --- Formatting and structured summaries ---

def _num(value):
    return float(value) if value is not None else None


def research_summary(r: dict) -> dict:
    stats = r.get("SUMMARY_STATS")
    if isinstance(stats, str):
        try:
            stats = json.loads(stats)
        except ValueError:
            stats = {}
    return {"research_name": r["INSTITUTION_NAME"], "research_works": int(r["WORKS_COUNT"] or 0),
            "citations": int(r["WORKS_CITED_BY_COUNT"] or 0), "h_index": (stats or {}).get("h_index")}


def school_summary(s: dict, research: dict | None = None) -> dict:
    out = {"name": s["NAME"], "city": s.get("CITY"), "state": s.get("STATE"), "control": s.get("CONTROL"), "country": "US",
           "admission_rate": _num(s.get("ADMISSION_RATE")), "tuition_in_state": _num(s.get("TUITION_IN_STATE")),
           "tuition_out_of_state": _num(s.get("TUITION_OUT_OF_STATE")), "net_price": _num(s.get("NET_PRICE")),
           "graduation_rate": _num(s.get("GRADUATION_RATE")), "earnings_10yr": _num(s.get("EARNINGS_10YR")),
           "median_debt": _num(s.get("MEDIAN_DEBT")), "undergrads": _num(s.get("UNDERGRADS"))}
    if research:
        out.update(research_summary(research))
    return out


def research_only_summary(r: dict) -> dict:
    return {"name": r["INSTITUTION_NAME"], "country": None, **research_summary(r)}


def program_summary(p: dict, school: str) -> dict:
    return {"school": school, "program": p["PROGRAM"], "credential": p["CREDENTIAL"],
            "graduates": int(p["GRADUATES"]) if p.get("GRADUATES") is not None else None,
            "earnings_1yr": _num(p.get("EARNINGS_1YR")), "earnings_4yr": _num(p.get("EARNINGS_4YR")),
            "earnings_5yr": _num(p.get("EARNINGS_5YR")), "median_debt": _num(p.get("MEDIAN_DEBT")),
            "schools": int(p["SCHOOLS"]) if p.get("SCHOOLS") is not None else None}


def school_facts(s: dict) -> str:
    parts = [
        f"admission rate {display(s['ADMISSION_RATE'], 'percent')}",
        f"in-state tuition {display(s['TUITION_IN_STATE'], 'usd')}",
        f"out-of-state tuition {display(s['TUITION_OUT_OF_STATE'], 'usd')}",
        f"average net price {display(s['NET_PRICE'], 'usd')}",
        f"graduation rate {display(s['GRADUATION_RATE'], 'percent')}",
        f"median earnings 10 years after starting {display(s['EARNINGS_10YR'], 'usd')}",
        f"median debt {display(s['MEDIAN_DEBT'], 'usd')}",
    ]
    where = ", ".join(x for x in (s.get("CITY"), s.get("STATE")) if x)
    return f"{s['NAME']} ({where}; {s.get('CONTROL') or 'school'}): " + "; ".join(p for p in parts if "not reported" not in p)


def program_facts(p: dict, where: str) -> str:
    parts = [f"{label.lower()} {display(p[col], 'usd')}" for col, _, label in PROGRAM_METRICS.values() if p.get(col) is not None]
    size = f", {int(p['GRADUATES'])} graduates in the cohort" if p.get("GRADUATES") else ""
    return f"{p['PROGRAM']} ({p['CREDENTIAL']}) {where}{size}: " + "; ".join(parts)


def research_facts(r: dict) -> str:
    s = research_summary(r)
    return (f"{s['research_name']}: {s['research_works']:,} research works, cited {s['citations']:,} times"
            + (f", h-index {s['h_index']}" if s["h_index"] else ""))


def _claim(item: Item, label: str, unit: str, metric: str, claimed: str, official: str, status: str) -> dict:
    return {"text": item.text, "label": label, "unit": unit, "metric": metric, "claimed": claimed,
            "official": official, "result": status}


# --- Curated Ontario figures ---

@lru_cache(maxsize=1)
def curated_data() -> dict:
    return json.loads(CURATED_PATH.read_text(encoding="utf-8"))


def curated_school(name: str | None) -> tuple[str, dict] | None:
    """(official name, entry) when a name or alias matches a curated school exactly, e.g. "UofT" or "uwaterloo"."""
    key = normalize(name)
    if not key:
        return None
    for official, entry in curated_data()["schools"].items():
        if key in {normalize(a) for a in entry.get("aliases", [])} | {normalize(official)}:
            return official, entry
    return None


def _curated_row(official: str, entry: dict) -> dict:
    row = {"name": official, "city": entry.get("city"), "state": entry.get("province"), "country": "CA"}
    row.update({key: metric["value"] for key, metric in entry["metrics"].items()})
    if research := find_research(official):
        row.update(research_summary(research))
    return row


def _curated_evidence(official: str, entry: dict) -> list[Evidence]:
    sources = curated_data().get("sources", {})
    out = []
    for key, metric in entry["metrics"].items():
        label, unit = CURATED_LABELS.get(key, (key, "count"))
        source = sources.get(metric.get("source"), {})
        out.append(Evidence(source.get("title", "Official university data"),
                            f"{official}: {label.lower()} {display(metric['value'], unit)} ({metric.get('period', '')})",
                            "official", source.get("url")))
    return out


def _curated_comparison(item: Item, mine: tuple[str, dict], theirs: tuple[str, dict] | None, other: str | None,
                        metric: str) -> Finding:
    """Side-by-side official figures for curated schools, with a direct answer when the text compares them."""
    rows = [_curated_row(*mine)]
    evidence = _curated_evidence(*mine)
    if theirs and theirs[0] != mine[0]:
        rows.append(_curated_row(*theirs))
        evidence += _curated_evidence(*theirs)
    elif other and (research := find_research(other)):
        rows.append(research_only_summary(research))
    a = rows[0]
    b = rows[1] if len(rows) > 1 and rows[1].get("earnings_2yr_median") is not None else None

    if b:
        sentences = [
            f"{a['name']} graduates earned a median {display(a.get('earnings_2yr_median'), 'usd')} two years after graduating, "
            f"compared with {display(b.get('earnings_2yr_median'), 'usd')} at {b['name']}.",
            f"{display(a.get('employment_related_rate'), 'percent')} of {a['name']} graduates were employed in a related field, "
            f"versus {display(b.get('employment_related_rate'), 'percent')} at {b['name']} (Government of Ontario, 2023-24).",
        ]
    else:
        sentences = [f"{a['name']} graduates earned a median {display(a.get('earnings_2yr_median'), 'usd')} two years after "
                     f"graduating, and {display(a.get('employment_related_rate'), 'percent')} were employed in a related field "
                     "(Government of Ontario, 2023-24)."]

    status, claim = "info", None
    direction = item.data.get("direction") if item.data.get("direction") in ("higher", "lower") else None
    key = CURATED_CLAIM_METRIC.get(metric) or ("earnings_2yr_median" if EARNINGS_WORDS.search(item.text or "") else None)
    if b and direction and key and a.get(key) is not None and b.get(key) is not None:
        label, unit = CURATED_LABELS[key]
        holds = compare_direction(float(a[key]), float(b[key]), direction, unit)
        status = "ok" if holds else "caution"
        claim = _claim(item, label, unit, key, f"{direction} than {b['name']}", f"{display(a[key], unit)} vs {display(b[key], unit)}", status)
        sentences.insert(0, f"{'Yes' if holds else 'No'}, going by official Ontario data.")

    title = f"{a['name']} vs {b['name']}: official Ontario data" if b else f"{a['name']}: official Ontario data"
    data = {"type": "college", "schools": rows, "programs": [], "claim": claim, "opinion": claim is None and metric == "general",
            "curated": True, "currency": curated_data().get("currency"), "notes": curated_data().get("notes", [])}
    return Finding(item, status, title, " ".join(sentences), "college", evidence, data=data)


# --- Checker ---

def check(item: Item, ext: Extraction) -> Finding | None:
    if item.kind != "school":
        return None
    d = item.data
    metric = d.get("metric") if d.get("metric") in METRICS else "general"
    program = d.get("program")
    credential = (d.get("credential") or "").lower()
    credlev = CREDENTIAL_LEVELS.get(credential, 3) if program else None
    comparator = d.get("comparator") if d.get("comparator") in ("about", "over", "under", "nearly") else "about"
    value = d.get("value")
    try:
        value = float(value) if value is not None else None
    except (TypeError, ValueError):
        value = None
    name = canonical_school(d.get("school"))
    prefix = f"{comparator} " if comparator != "about" else ""

    if not name:
        if program:
            return _national_program(item, program, credlev, metric, value, comparator)
        return None

    data = {"type": "college", "schools": [], "programs": [], "claim": None, "opinion": False}
    other = canonical_school(d.get("compare_to"))
    school = find_school(name)
    research = find_research(name)
    evidence: list[Evidence] = []
    if research:
        evidence.append(Evidence(SRC_OPENALEX, research_facts(research)))

    if school is None:
        mine = curated_school(d.get("school")) or curated_school(name)
        if mine:
            theirs = curated_school(d.get("compare_to")) or curated_school(other)
            return _curated_comparison(item, mine, theirs, other, metric)
        if research is None:
            return None
        data["schools"].append(research_only_summary(research))
        other_research = find_research(other) if other else None
        if other_research:
            data["schools"].append(research_only_summary(other_research))
            evidence.append(Evidence(SRC_OPENALEX, research_facts(other_research)))
        return Finding(item, "info", f"{research['INSTITUTION_NAME']}: research profile",
                       research_facts(research) + ". College Scorecard only covers US schools, so admissions, costs, "
                                                  "and earnings claims were checked on the web.",
                       "college", evidence, web_followup=True, data=data)

    evidence.insert(0, Evidence(SRC_SCORECARD, school_facts(school)))
    data["schools"].append(school_summary(school, research))
    title = school["NAME"]
    status, summary = "info", school_facts(school) + "."
    other_school = find_school(other) if other else None
    direction = d.get("direction") if d.get("direction") in ("higher", "lower") else None

    if metric in SCHOOL_METRICS and value is None and other_school and direction:
        col, unit, label = SCHOOL_METRICS[metric]
        a, b = school.get(col), other_school.get(col)
        title = f"{school['NAME']} vs {other_school['NAME']}: {label.lower()}"
        if a is None or b is None:
            summary = f"College Scorecard doesn't report {label.lower()} for both schools."
        else:
            holds = compare_direction(float(a), float(b), direction, unit)
            status = "ok" if holds else "caution"
            summary = (f"{label}: {school['NAME']} {display(a, unit)} vs {other_school['NAME']} {display(b, unit)}. "
                       f"The claim that it is {direction} {'checks out' if holds else 'does not match the official figures'}.")
            data["claim"] = _claim(item, label, unit, metric, f"{direction} than {other_school['NAME']}",
                                   f"{display(a, unit)} vs {display(b, unit)}", status)

    elif metric in SCHOOL_METRICS and value is not None:
        col, unit, label = SCHOOL_METRICS[metric]
        actual = school.get(col)
        title = f"{school['NAME']}: {label.lower()}"
        if actual is None:
            summary = f"College Scorecard doesn't report {label.lower()} for {school['NAME']}."
        else:
            ok = matches(value, float(actual), unit, comparator)
            status = "ok" if ok else "caution"
            summary = (f"{label} is {display(actual, unit)} according to College Scorecard. The claim said "
                       f"{prefix}{display_claim(value, unit)}." + ("" if ok else " That doesn't match the official figure."))
            data["claim"] = _claim(item, label, unit, metric, prefix + display_claim(value, unit), display(actual, unit), status)

    elif program:
        row = find_program(school["UNITID"], program, credlev)
        where = f"at {school['NAME']}"
        if row is None:
            summary = f"College Scorecard has no reported earnings or debt for {program} {where}, usually because too few students graduated."
        else:
            evidence.insert(1, Evidence(SRC_SCORECARD, program_facts(row, where)))
            data["programs"].append(program_summary(row, school["NAME"]))
            title = f"{school['NAME']}: {row['PROGRAM']}"
            if (metric in PROGRAM_METRICS and value is not None and row.get(PROGRAM_METRICS[metric][0]) is not None
                    and (metric == "program_debt" or is_graduate_earnings_claim(item.text))):
                col, unit, label = PROGRAM_METRICS[metric]
                ok = matches(value, float(row[col]), unit, comparator)
                status = "ok" if ok else "caution"
                summary = (f"{label} for {row['PROGRAM']} ({row['CREDENTIAL']}) {where} is {display(row[col], unit)}. "
                           f"The claim said {prefix}{display_claim(value, unit)}."
                           + ("" if ok else " That doesn't match the official figure."))
                data["claim"] = _claim(item, f"{label}, {row['PROGRAM']}", unit, metric,
                                       prefix + display_claim(value, unit), display(row[col], unit), status)
            else:
                summary = program_facts(row, where) + "."

    if other:
        other_research = find_research(other)
        if other_school:
            evidence.append(Evidence(SRC_SCORECARD, school_facts(other_school)))
            data["schools"].append(school_summary(other_school, other_research))
            if program and (op := find_program(other_school["UNITID"], program, credlev)):
                evidence.append(Evidence(SRC_SCORECARD, program_facts(op, f"at {other_school['NAME']}")))
                data["programs"].append(program_summary(op, other_school["NAME"]))
        elif other_research:
            data["schools"].append(research_only_summary(other_research))
        if other_research:
            evidence.append(Evidence(SRC_OPENALEX, research_facts(other_research)))
        if status == "info" and metric == "general":
            title = f"{school['NAME']} vs {other_school['NAME'] if other_school else other}"
            summary = "Opinions about which school is better can't be proven true or false, so here are the official numbers side by side."
            data["opinion"] = True

    return Finding(item, status, title, summary, "college", evidence, data=data)


def _national_program(item: Item, program: str, credlev: int | None, metric: str, value: float | None,
                      comparator: str) -> Finding | None:
    row = find_national_program(program, credlev)
    if row is None:
        return None
    where = f"across {int(row['SCHOOLS'])} US schools (median of school medians)"
    ev = [Evidence(SRC_SCORECARD, program_facts(row, where))]
    data = {"type": "college", "schools": [], "programs": [program_summary(row, f"Typical across {int(row['SCHOOLS'])} US schools")],
            "claim": None, "opinion": False}
    prefix = f"{comparator} " if comparator != "about" else ""
    if metric in PROGRAM_METRICS and value is not None and not (metric == "program_debt" or is_graduate_earnings_claim(item.text)):
        data["claim"] = _claim(item, "Career salary (not measured by Scorecard)", "usd", metric,
                               prefix + display_claim(value, "usd"), "see graduate earnings", "info")
        return Finding(item, "info", f"{row['PROGRAM']}: what graduates actually earn",
                       "This sounds like a career salary, which College Scorecard doesn't measure. For context, "
                       + program_facts(row, where) + ".", "college", ev, web_followup=True, data=data)
    if metric in PROGRAM_METRICS and value is not None and row.get(PROGRAM_METRICS[metric][0]) is not None:
        col, unit, label = PROGRAM_METRICS[metric]
        ok = matches(value, float(row[col]), unit, comparator)
        status = "ok" if ok else "caution"
        summary = (f"{label} for {row['PROGRAM']} ({row['CREDENTIAL']}) is typically {display(row[col], unit)} {where}. "
                   f"The claim said {prefix}{display_claim(value, unit)}."
                   + ("" if ok else " That doesn't match the typical figure; results vary a lot by school."))
        data["claim"] = _claim(item, f"{label}, {row['PROGRAM']} (typical)", unit, metric,
                               prefix + display_claim(value, unit), display(row[col], unit), status)
        return Finding(item, status, f"{row['PROGRAM']}: typical earnings", summary, "college", ev, data=data)
    return Finding(item, "info", f"{row['PROGRAM']}: typical outcomes", program_facts(row, where) + ".", "college", ev, data=data)

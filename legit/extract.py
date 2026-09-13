"""Turn pasted text into checkable items. Uses Groq, with a much weaker offline fallback."""
from __future__ import annotations

import re
from datetime import date

from . import config, llm
from .checkers import college, patterns
from .checkers.common import GENERIC_NAME_WORDS, ONTARIO_CITIES, domain_of, normalize_name, province_name
from .models import Extraction, Item, Location
from .stats import parse_rules
from .stats.catalog import Catalog

ENTITY_TYPES = ["bank", "credit_union", "lender", "loan_servicer", "credit_card", "investment_adviser", "employer",
                "company", "landlord", "property_manager", "school", "charity", "government", "website", "other"]
PRICE_CATEGORIES = ["rent", "hourly_wage", "salary", "savings_rate", "loan_rate", "credit_card_rate", "fee",
                    "tuition", "other"]
PRICE_UNITS = ["per_month", "per_hour", "per_year", "percent", "one_time", "per_week"]

_catalog: Catalog | None = None


def stats_catalog() -> Catalog:
    global _catalog
    if _catalog is None:
        _catalog = Catalog()
    return _catalog


def system_prompt() -> str:
    metrics = "\n".join(f'  - "{m.id}": {m.label} (measures: {", ".join(m.measures)})'
                        for m in stats_catalog().metrics.values())
    pattern_list = "\n".join(f'  - "{k}": {v.title}' for k, v in patterns.PATTERNS.items())
    SCHOOL_METRIC_NAMES = college.METRICS  # noqa: N806  (used inside the f-string below)
    return f"""You help a university student who is living on their own for the first time decide whether to trust
something they read: a rental listing, a job offer, a message from a bank or lender, school or campus info,
financial advice, a social media post, or AI-generated text.

Read the text and list every checkable item. Return JSON only:
{{
  "context": "housing" | "job" | "finance" | "school" | "health" | "everyday" | "other",
  "summary": "one sentence describing what the text is",
  "location": {{"city": str or null, "region": str or null, "country": "US" | "CA" | str | null}},
  "items": [ ...items... ]
}}

Item kinds. Every item has "kind" and "text" (a short exact quote from the input):
1. entity: a named organization or person acting as one.
   {{"kind": "entity", "text": str, "name": str, "entity_type": one of {ENTITY_TYPES},
    "website": str or null, "email_domain": str or null}}
2. price: a rent, wage, salary, interest rate, fee, or tuition amount.
   {{"kind": "price", "text": str, "category": one of {PRICE_CATEGORIES}, "amount": number,
    "unit": one of {PRICE_UNITS}, "bedrooms": int or null, "entry_level": true | false | null}}
   Interest rates use "percent" with the number as a percent (5.5 means 5.5%). entry_level is true when the job
   says no experience is needed.
3. statistic: an official statistic for a whole country, state, or city that matches one of the metrics below.
   A figure about a specific group, major, occupation, or industry ("unemployment for recent grads",
   "nurses earn") is not a statistic: use "school" for majors, otherwise "claim".
{metrics}
   {{"kind": "statistic", "text": str, "metric_id": str, "measure": str, "value": number,
    "period": {{"year": int, "month": int or null, "quarter": int or null}} or null,
    "state": str or null, "city": str or null, "comparator": "about" | "over" | "under" | "nearly"}}
   Percentages as percent numbers; counts and dollars as full numbers.
4. pattern: a known scam or pressure tactic that is actually present in the text. Use one of:
{pattern_list}
   {{"kind": "pattern", "text": str, "pattern": str, "why": "one sentence tied to this text"}}
5. claim: any other factual claim worth checking on the web.
   {{"kind": "claim", "text": str, "claim": "the claim restated so it can be searched"}}
6. school: a claim about a specific college or university, a major's earnings, or a comparison between schools.
   Prefer this over "claim" for admissions, tuition, cost, graduation rates, graduate earnings, debt, or rankings.
   {{"kind": "school", "text": str, "school": "the school's official full name, or null for a major in general",
    "country": "US" | "CA" | str | null, "metric": one of {SCHOOL_METRIC_NAMES},
    "program": "field of study, e.g. computer science" or null,
    "credential": "certificate" | "associate" | "bachelor" | "master" | "doctoral" | null,
    "value": number or null, "comparator": "about" | "over" | "under" | "nearly",
    "compare_to": "another school's official full name" or null,
    "direction": "higher" | "lower" | null}}
   Percentages as percent numbers (29 means 29%); dollars as full numbers ("six figures" means over 100000).
   Examples:
   - "almost everyone graduates from UCLA" -> metric "graduation_rate", value 100, comparator "nearly".
   - "UCLA is cheaper than UT Austin for out-of-state students" -> school UCLA, metric "tuition_out_of_state",
     compare_to "The University of Texas at Austin", direction "lower", value null.
   - "Waterloo is better than UofT for CS" -> metric "general", value null, compare_to set.
   Make one item per distinct claim; don't repeat the same comparison for every sentence.

Rules:
- Only include what the text actually says. Do not invent names, numbers, or patterns.
- Include every named organization, website, or email domain, even if it seems legitimate. When an email
  address or link appears, attach its domain to the organization it claims to come from.
- The date the student saw this text is given; resolve "last year" and similar phrases from it.
- At most 12 items. If nothing is checkable, return an empty items list."""


def extract(text: str, said_on: date, hint: str | None = None) -> tuple[Extraction, list[str]]:
    """hint describes the source, e.g. that the text is a spoken YouTube transcript."""
    notes: list[str] = []
    if llm.available():
        try:
            ext = _groq_extract(text, said_on, hint)
            _merge_offline(ext, offline_extract(text, said_on), notes)
            attach_domains(ext, text)
            demote_subgroup_statistics(ext, text)
            return ext, notes
        except llm.LLMError as e:
            notes.append(f"Groq extraction unavailable ({str(e)[:160]}); used the offline extractor, which finds much less.")
    else:
        notes.append("No GROQ_API_KEY set; used the offline extractor, which finds much less.")
    ext = offline_extract(text, said_on)
    attach_domains(ext, text)
    demote_subgroup_statistics(ext, text)
    return ext, notes


def demote_subgroup_statistics(ext: Extraction, text: str) -> None:
    """Turn statistics about one group ("nursing ... unemployment is 1.42%") into plain claims, whichever extractor found them."""
    for item in ext.items:
        if item.kind == "statistic" and about_subgroup(text, item.text):
            item.kind, item.data = "claim", {"claim": item.text}


DOMAIN_IN_TEXT = re.compile(r"[\w.+-]+@([\w-]+(?:\.[\w-]+)+)|\b((?:https?://)?(?:www\.)?[\w-]+(?:\.[\w-]+)*\.(?:com|ca|org|net|edu|io|co|info|biz|us|app))\b",
                            re.I)
def attach_domains(ext: Extraction, text: str) -> None:
    """Link each domain to the organization it names, e.g. chase-student-rewards.com -> Chase Bank.

    Registry checks can then compare the domain with the organization's real ones. Bare "website" entities that
    got linked are dropped, so the report doesn't show the same domain twice."""
    orgs = [i for i in ext.items if i.kind == "entity" and (i.data.get("entity_type") or "") != "website"]
    domains = []
    for i in ext.items:
        if i.kind == "entity" and i.data.get("entity_type") == "website":
            d = domain_of(i.data.get("website")) or domain_of(i.data.get("name"))
            if d:
                domains.append((d, i))
    for m in DOMAIN_IN_TEXT.finditer(text):
        d = domain_of(m.group(1) or m.group(2))
        if d and d not in {x[0] for x in domains}:
            domains.append((d, None))

    linked_sites = set()
    for d, site in domains:
        label = d.split(".")[0]
        for org in orgs:
            if domain_of(org.data.get("website")) or domain_of(org.data.get("email_domain")):
                continue
            tokens = [t for t in normalize_name(org.data.get("name")).split() if len(t) >= 4 and t not in GENERIC_NAME_WORDS]
            if tokens and any(t in label for t in tokens):
                org.data["website"] = d
                if site is not None:
                    linked_sites.add(id(site))
                break
    if linked_sites:
        ext.items = [i for i in ext.items if id(i) not in linked_sites]
        for n, item in enumerate(ext.items, start=1):
            item.id = n


def _key(item: Item) -> tuple[str, str | None]:
    return item.kind, item.data.get("pattern") or item.data.get("category")


def _merge_offline(ext: Extraction, offline: Extraction, notes: list[str]) -> None:
    """Keyword rules always run too, so an AI miss can't hide an obvious red flag or price."""
    have = {_key(i) for i in ext.items}
    has_statistic = any(i.kind == "statistic" for i in ext.items)
    added = 0
    for item in offline.items:
        if _key(item) in have or (item.kind == "statistic" and has_statistic):
            continue
        ext.items.append(Item(len(ext.items) + 1, item.kind, item.text, item.data))
        have.add(_key(item))
        added += 1
    if not ext.location.label() and offline.location.label():
        ext.location = offline.location
    if ext.context == "other" and offline.context != "other":
        ext.context = offline.context
    if added:
        notes.append(f"Keyword rules added {added} item(s) the AI extraction missed.")


def _groq_extract(text: str, said_on: date, hint: str | None = None) -> Extraction:
    source = f"{hint}\n" if hint else ""
    message, model = llm.chat_any(
        config.EXTRACT_MODELS,
        [{"role": "system", "content": system_prompt()},
         {"role": "user", "content": f"{source}Date seen: {said_on.isoformat()}\n\nText:\n{text}"}],
        json_mode=True, timeout=60)
    data = llm.parse_json(message.get("content"))
    if not data:
        raise llm.LLMError("model returned no JSON")
    loc = data.get("location") or {}
    ext = Extraction(said_on=said_on, context=str(data.get("context") or "other"), summary=str(data.get("summary") or ""),
                     location=Location(loc.get("city"), loc.get("region"), loc.get("country")), parser=f"groq {model}")
    for raw in (data.get("items") or [])[:15]:
        item = _validated(raw, len(ext.items) + 1)
        if item:
            if item.kind == "statistic" and about_subgroup(text, item.text):
                item.kind, item.data = "claim", {"claim": item.text}
            ext.items.append(item)
    return ext


def about_subgroup(text: str, quote: str, window: int = 160) -> bool:
    """True when the words around a quoted statistic tie it to one group, major, or industry
    ("nursing ... unemployment rate is 1.42%"), so it shouldn't be compared with the national figure."""
    from .checkers.statistic import SUBGROUP

    if SUBGROUP.search(quote or ""):
        return True
    # Captions and pasted text break lines and spacing differently from the model's quote, so compare normalized text.
    flat = " ".join(text.split())
    low, q = flat.lower(), " ".join((quote or "").split()).lower()
    pos = low.find(q[:30]) if q else -1
    if pos < 0:
        numbers = re.findall(r"\d[\d,.]*%?", q)
        for number in sorted(numbers, key=len, reverse=True):  # the most distinctive number, e.g. "1.42%"
            pos = low.find(number)
            if pos >= 0:
                break
    if pos < 0:
        return False
    return bool(SUBGROUP.search(flat[max(0, pos - window): pos + len(q) + 40]))


def _validated(raw: dict, next_id: int) -> Item | None:
    if not isinstance(raw, dict):
        return None
    kind = raw.get("kind")
    quote = str(raw.get("text") or raw.get("claim") or raw.get("name") or "")[:300]
    data = {k: v for k, v in raw.items() if k not in ("kind", "text")}
    if kind == "entity":
        if not data.get("name"):
            return None
    elif kind == "price":
        try:
            data["amount"] = float(data["amount"])
        except (KeyError, TypeError, ValueError):
            return None
    elif kind == "statistic":
        if stats_catalog().get(data.get("metric_id")) is None or data.get("value") is None:
            kind, data = "claim", {"claim": quote}
    elif kind == "pattern":
        if data.get("pattern") not in patterns.PATTERNS:
            return None
    elif kind == "claim":
        if not data.get("claim"):
            data["claim"] = quote
    elif kind == "school":
        if not (data.get("school") or data.get("program")):
            return None
        if data.get("metric") not in college.METRICS:
            data["metric"] = "general"
        try:
            data["value"] = float(data["value"]) if data.get("value") is not None else None
        except (TypeError, ValueError):
            data["value"] = None
    else:
        return None
    return Item(next_id, kind, quote, data)


# --- Offline fallback: regular expressions only. Used without a key or when Groq is rate limited. ---

OFFLINE_PATTERNS = [
    ("unusual_payment_method", r"\b(gift ?cards?|bitcoin|crypto(?:currency)?|wire transfer|western union|moneygram|zelle|cash ?app|venmo|e-?transfer)\b"),
    ("cannot_view_in_person", r"\b(out of (?:the )?country|abroad|overseas|can'?t (?:show|meet)|cannot (?:show|meet)|mail (?:you )?the keys)\b"),
    ("overpayment_check", r"\b(?:check|cheque)\b[^.]{0,80}\bdeposit\b[^.]{0,80}\bsend\b|\bdeposit (?:the|this|a|it)\b[^.]{0,40}\bsend\b"
                          r"|\bsend (?:back )?the (?:rest|remaining|difference|extra)\b"),
    ("upfront_payment", r"\b(deposit|application fee|processing fee|holding fee|first and last)\b[^.]{0,60}"
                        r"\b(before|first|today|to (?:hold|secure|reserve|lock))\b"),
    ("urgency", r"\b(act (?:fast|now)|today only|first come|lots of (?:interest|people|students)|within 24 hours|urgent(?:ly)?"
                r"|limited (?:spots|time|availability)|before someone else|spots? (?:are )?filling)\b"),
    ("pay_for_job", r"\b(starter kit|training fee|pay for (?:your )?(?:equipment|training|certification))\b"),
    ("guaranteed_returns", r"\bguaranteed\b[^.]{0,40}\b(returns?|profits?|income|apy|interest)\b"
                           r"|\b(returns?|profits?|income|apy|interest)\b[^.]{0,40}\bguaranteed\b"),
    ("asks_personal_info", r"\b(ssn|sin number|social security|social insurance|(?:online )?banking login|bank (?:login|password)"
                           r"|login credentials|your password|pin number|credit card number)\b"),
]
RENT = re.compile(r"(?:\$\s?)?\b([\d,]{3,}(?:\.\d+)?)\s*(?:cad|usd|dollars)?\s*(?:/|per|a)\s*(?:mo|month)\b", re.I)
HOURLY = re.compile(r"\$\s?([\d,]+(?:\.\d+)?)\s*(?:/|per|an|a)\s*(?:hr|hour)\b", re.I)
RATE = re.compile(r"\b(\d{1,2}(?:\.\d+)?)\s*%\s*(apy|apr|interest)\b", re.I)
BEDROOMS = re.compile(r"\b(\d)\s*(?:-?\s*)(?:br|bd|bed(?:room)?s?)\b", re.I)
CANADA_CUES = re.compile(r"\b(cad|e-?transfer|interac|ontario|quebec|alberta|british columbia|manitoba|nova scotia|"
                         r"waterloo|kitchener|toronto|ottawa|vancouver|montreal|calgary|sin number)\b", re.I)
NEGATION = re.compile(r"\b(never|not|won'?t|don'?t|do not|will not|no one|nobody|avoid|beware)\b", re.I)
HOUSING_CUES = re.compile(r"\b(sublet|rent|lease|apartment|bedroom|room|landlord|condo|house|tenant)\b", re.I)
JOB_CUES = re.compile(r"\b(job|role|position|hiring|recruit\w*|interview|employer|internship)\b", re.I)
FINANCE_CUES = re.compile(r"\b(bank|apy|apr|loan|credit card|savings|invest\w*|crypto)\b", re.I)


def _sentence(text: str, start: int, end: int) -> str:
    """The whole sentence or line around a match, so quotes don't start mid-word."""
    left = max(text.rfind(c, 0, start) for c in ".!?\n") + 1
    rights = [i for i in (text.find(c, end) for c in ".!?\n") if i >= 0]
    right = min(rights) + 1 if rights else len(text)
    return text[left:right].strip()


def offline_extract(text: str, said_on: date) -> Extraction:
    ext = Extraction(said_on=said_on, parser="offline rules")
    low = text.lower()

    def add(kind: str, quote: str, data: dict) -> None:
        ext.items.append(Item(len(ext.items) + 1, kind, quote[:300], data))

    if FINANCE_CUES.search(text) and not HOUSING_CUES.search(text):
        ext.context = "finance"
    elif HOUSING_CUES.search(text):
        ext.context = "housing"
    elif JOB_CUES.search(text):
        ext.context = "job"
    if CANADA_CUES.search(text):
        city = next((c for c in ONTARIO_CITIES if re.search(rf"\b{re.escape(c)}\b", low)), None)
        ext.location = Location(city=city.title() if city else None, region=province_name(None, city), country="CA")

    for pattern, rx in OFFLINE_PATTERNS:
        for m in re.finditer(rx, low):
            sentence = _sentence(text, m.start(), m.end())
            if NEGATION.search(sentence):  # safety tips like "we will never ask for your password"
                continue
            add("pattern", sentence, {"pattern": pattern, "why": ""})
            break
    bedrooms = BEDROOMS.search(text)
    if ext.context == "housing" and (m := RENT.search(text)):
        add("price", m.group(0), {"category": "rent", "amount": float(m.group(1).replace(",", "")), "unit": "per_month",
                                  "bedrooms": int(bedrooms.group(1)) if bedrooms else None})
    if m := HOURLY.search(text):
        add("price", m.group(0), {"category": "hourly_wage", "amount": float(m.group(1).replace(",", "")),
                                  "unit": "per_hour", "entry_level": "no experience" in low or None})
    if m := RATE.search(text):
        kind = m.group(2).lower()
        category = "savings_rate" if kind == "apy" else ("credit_card_rate" if "credit card" in low else "loan_rate")
        add("price", _sentence(text, m.start(), m.end()), {"category": category, "amount": float(m.group(1)), "unit": "percent"})
    claim = parse_rules.parse(text, said_on, stats_catalog())
    if claim.metric_id and claim.value is not None:
        add("statistic", text[:200], {
            "metric_id": claim.metric_id, "measure": claim.measure, "value": claim.value,
            "period": {"year": claim.period.year, "month": claim.period.month, "quarter": claim.period.quarter} if claim.period else None,
            "state": claim.state, "city": claim.city, "comparator": claim.comparator})
    return ext

"""Name and domain normalization shared by checkers."""
from __future__ import annotations

import re

FREE_EMAIL_DOMAINS = {
    "gmail.com", "googlemail.com", "yahoo.com", "yahoo.ca", "ymail.com", "outlook.com", "hotmail.com", "hotmail.ca",
    "live.com", "live.ca", "msn.com", "aol.com", "icloud.com", "me.com", "proton.me", "protonmail.com", "gmx.com",
    "mail.com", "yandex.com", "zoho.com",
}
_SECOND_LEVEL = {"co.uk", "ac.uk", "org.uk", "com.au", "co.in", "co.nz", "com.br", "co.jp", "on.ca", "qc.ca", "bc.ca"}

US_STATES = {
    "AL": "Alabama", "AK": "Alaska", "AZ": "Arizona", "AR": "Arkansas", "CA": "California", "CO": "Colorado",
    "CT": "Connecticut", "DE": "Delaware", "DC": "District of Columbia", "FL": "Florida", "GA": "Georgia",
    "HI": "Hawaii", "ID": "Idaho", "IL": "Illinois", "IN": "Indiana", "IA": "Iowa", "KS": "Kansas", "KY": "Kentucky",
    "LA": "Louisiana", "ME": "Maine", "MD": "Maryland", "MA": "Massachusetts", "MI": "Michigan", "MN": "Minnesota",
    "MS": "Mississippi", "MO": "Missouri", "MT": "Montana", "NE": "Nebraska", "NV": "Nevada", "NH": "New Hampshire",
    "NJ": "New Jersey", "NM": "New Mexico", "NY": "New York", "NC": "North Carolina", "ND": "North Dakota",
    "OH": "Ohio", "OK": "Oklahoma", "OR": "Oregon", "PA": "Pennsylvania", "RI": "Rhode Island",
    "SC": "South Carolina", "SD": "South Dakota", "TN": "Tennessee", "TX": "Texas", "UT": "Utah", "VT": "Vermont",
    "VA": "Virginia", "WA": "Washington", "WV": "West Virginia", "WI": "Wisconsin", "WY": "Wyoming",
}
CANADIAN_PROVINCES = {
    "ON": "Ontario", "QC": "Quebec", "BC": "British Columbia", "AB": "Alberta", "MB": "Manitoba",
    "SK": "Saskatchewan", "NS": "Nova Scotia", "NB": "New Brunswick", "NL": "Newfoundland and Labrador",
    "PE": "Prince Edward Island",
}
ONTARIO_CITIES = {"waterloo", "kitchener", "cambridge", "guelph", "toronto", "ottawa", "hamilton", "london",
                  "mississauga", "brampton", "kingston", "windsor", "oshawa", "st. catharines"}

_LEGAL_WORDS = re.compile(
    r"\b(the|and|inc|incorporated|llc|ltd|limited|corp|corporation|co|company|n a|na|national association|plc|lp|llp|"
    r"group|holdings|mgmt|management)\b")


GENERIC_NAME_WORDS = {"bank", "university", "college", "student", "students", "services", "service", "financial",
                      "credit", "union", "property", "properties", "rentals", "rental", "careers", "career", "online",
                      "national", "federal", "savings", "housing", "group", "team", "support", "official"}


def brand_tokens(*names: str | None) -> list[str]:
    """Distinctive words from organization names, plus the words joined: "JPMorgan Chase Bank" -> jpmorgan, chase, jpmorganchase."""
    tokens: list[str] = []
    for name in names:
        words = [w for w in normalize_name(name).split() if w not in GENERIC_NAME_WORDS]
        tokens += [w for w in words if len(w) >= 4]
        if len(words) > 1:
            tokens.append("".join(words))
    return list(dict.fromkeys(tokens))


def domain_brand_relation(domain: str, *names: str | None) -> str:
    """How a domain relates to an organization's name.

    exact: the domain is just the brand (chase.com for Chase), which is probably official.
    lookalike: the brand plus extra words (chase-student-rewards.com), a classic impersonation trick.
    unrelated: no sign of the brand at all."""
    label = domain.split(".")[0]
    tokens = brand_tokens(*names)
    if not tokens:
        return "unrelated"
    if label in tokens or label.replace("-", "") in tokens:
        return "exact"
    if any(t in label for t in tokens):
        return "lookalike"
    return "unrelated"


def domain_of(value: str | None) -> str | None:
    """Registrable domain from a URL, host, or email address. careers.amazon.com -> amazon.com."""
    if not value:
        return None
    v = str(value).strip().lower()
    if "@" in v:
        v = v.split("@")[-1]
    v = re.sub(r"^[a-z][a-z0-9+.-]*://", "", v)
    v = v.split("/")[0].split("?")[0].split(":")[0].strip(".")
    if v.startswith("www."):
        v = v[4:]
    if "." not in v or " " in v or not re.fullmatch(r"[a-z0-9.-]+", v):
        return None
    parts = v.split(".")
    if len(parts) >= 3 and ".".join(parts[-2:]) in _SECOND_LEVEL:
        return ".".join(parts[-3:])
    return ".".join(parts[-2:])


def normalize_name(name: str | None) -> str:
    n = (name or "").lower().replace("&", " and ")
    n = re.sub(r"[^\w\s]", " ", n)
    n = _LEGAL_WORDS.sub(" ", n)
    return re.sub(r"\s+", " ", n).strip()


def like_pattern(name: str | None) -> str | None:
    """SQL ILIKE pattern that matches the name's words in order, ignoring legal suffixes."""
    tokens = [t for t in normalize_name(name).split() if len(t) >= 2]
    return "%" + "%".join(tokens) + "%" if tokens else None


def name_matches(claimed: str | None, registered: str | None) -> bool:
    """True when every word of the claimed name appears in the registered name."""
    a = set(normalize_name(claimed).split())
    b = set(normalize_name(registered).split())
    return bool(a) and a <= b


def us_state_name(region: str | None) -> str | None:
    if not region:
        return None
    r = region.strip()
    if r.upper() in US_STATES:
        return US_STATES[r.upper()]
    for name in US_STATES.values():
        if name.lower() == r.lower():
            return name
    return None


def province_name(region: str | None, city: str | None = None) -> str | None:
    if region:
        r = region.strip()
        if r.upper() in CANADIAN_PROVINCES:
            return CANADIAN_PROVINCES[r.upper()]
        for name in CANADIAN_PROVINCES.values():
            if name.lower() == r.lower():
                return name
    if city and city.strip().lower() in ONTARIO_CITIES:
        return "Ontario"
    return None

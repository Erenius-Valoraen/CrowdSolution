"""Is this organization real, and does its website or email match? Official US registries only."""
from __future__ import annotations

from .. import db
from ..models import SEVERITY, Evidence, Extraction, Finding, Item
from .common import FREE_EMAIL_DOMAINS, domain_brand_relation, domain_of, like_pattern, name_matches

BANK_TYPES = {"bank", "credit_union", "lender", "credit_card"}
COMPANY_TYPES = {"employer", "company", "landlord", "property_manager", "school", "loan_servicer", "website", "other"}
SRC_BANKS = "Federal bank registry (FFIEC/FDIC, via Snowflake Public Data)"
SRC_ADVISERS = "SEC investment adviser registry (via Snowflake Public Data)"
SRC_DOMAINS = "Company and web domain registry (via Snowflake Public Data)"
SRC_CHARITIES = "IRS Form 990 filings (via Snowflake Public Data)"


def check(item: Item, ext: Extraction) -> Finding | None:
    if item.kind != "entity":
        return None
    d = item.data
    name = d.get("name") or ""
    etype = (d.get("entity_type") or "other").lower()
    domain = domain_of(d.get("website")) or domain_of(d.get("email_domain"))

    if etype in BANK_TYPES and not ext.location.is_canada:
        return _bank(item, name, domain)
    if etype == "investment_adviser" and not ext.location.is_canada:
        return _adviser(item, name)
    if etype == "charity" and not ext.location.is_canada:
        return _charity(item, name)
    return _company(item, name, domain, etype)


def _combine(item: Item, title: str, parts: list[tuple[str, str, Evidence | None]], *, followup: bool = False,
             data: dict | None = None) -> Finding | None:
    """Merge several (status, sentence, evidence) observations into one finding with the worst status."""
    if not parts:
        return None
    status = max((p[0] for p in parts), key=lambda s: SEVERITY[s])
    return Finding(item, status, title, " ".join(p[1] for p in parts), "registry",
                   [p[2] for p in parts if p[2] is not None], web_followup=followup, data=data or {})


def _bank(item: Item, name: str, domain: str | None) -> Finding | None:
    pattern = like_pattern(name)
    if not pattern:
        return None
    rows = db.query(f"""
        SELECT NAME, IS_ACTIVE, FDIC_CERT, URL, CITY, STATE_ABBREVIATION, ENTITY_TYPE
        FROM {db.PUBLIC}.FINANCIAL_INSTITUTION_ENTITIES
        WHERE NAME ILIKE %(p)s
        ORDER BY IS_ACTIVE DESC, (URL IS NULL OR URL = '') ASC, LENGTH(NAME)
        LIMIT 5""", {"p": pattern})
    if not rows:
        return None
    top = rows[0]
    where = ", ".join(x for x in (top["CITY"], top["STATE_ABBREVIATION"]) if x)
    registered_site = domain_of(top["URL"])
    data = {"type": "bank", "registered_name": top["NAME"], "entity_type": top["ENTITY_TYPE"], "active": bool(top["IS_ACTIVE"]),
            "fdic_cert": str(top["FDIC_CERT"]) if top["FDIC_CERT"] is not None else None, "location": where,
            "claimed_domain": domain, "official_domains": [registered_site] if registered_site else [], "domain_result": None}
    ev = Evidence(SRC_BANKS, f"{top['NAME']} ({top['ENTITY_TYPE']}, {where}), FDIC certificate {top['FDIC_CERT'] or 'none'}, "
                             f"{'active' if top['IS_ACTIVE'] else 'no longer active'}"
                             + (f", website {top['URL']}" if top["URL"] else ""))
    title = f"{name}: bank registration"
    if not top["IS_ACTIVE"]:
        return _combine(item, title, [("caution", f"{top['NAME']} is in the federal registry but is no longer active.", ev)], data=data)

    parts = [("ok", f"{top['NAME']} is a registered, active institution.", ev)]
    if domain:
        official = _bank_domains(top["NAME"], top["URL"])
        data["official_domains"] = sorted(official)
        shown = ", ".join(sorted(official)[:4])
        relation = domain_brand_relation(domain, name, top["NAME"])
        if domain in official:
            data["domain_result"] = "official"
            parts.append(("ok", f"The website or email domain {domain} is one of its official domains.", None))
        elif domain in FREE_EMAIL_DOMAINS:
            data["domain_result"] = "free_email"
            parts.append(("red_flag", f"The message uses a free email address ({domain}); real banks use their own domain"
                                      f"{' (' + shown + ')' if shown else ''}.", None))
        elif relation == "lookalike":
            data["domain_result"] = "lookalike"
            parts.append(("red_flag", f"{domain} puts the bank's name inside a longer domain, but it is not on record as an "
                                      f"official domain{' (' + shown + ')' if shown else ''}. Lookalike domains are a classic "
                                      "phishing trick; type the bank's address yourself instead of using this link.",
                          Evidence(SRC_DOMAINS, f"Official domains on record: {shown or 'none listed'}")))
        elif relation == "exact":
            data["domain_result"] = "brand_match"
            parts.append(("info", f"{domain} matches the bank's name but isn't in our records, which are incomplete. "
                                  "It is probably official; type it yourself rather than following a link.", None))
        else:
            data["domain_result"] = "unrelated"
            parts.append(("caution", f"{domain} has no visible connection to {top['NAME']}"
                                     f"{' (official: ' + shown + ')' if shown else ''}.", None))
    return _combine(item, title, parts, data=data)


def _bank_domains(registered_name: str, url: str | None) -> set[str]:
    """Official domains from the bank registry URL plus the company domain registry."""
    domains = {d for d in [domain_of(url)] if d}
    pattern = like_pattern(registered_name)
    if pattern:
        rows = db.query(f"""
            SELECT DISTINCT DOMAIN_ID FROM {db.PUBLIC}.COMPANY_DOMAIN_RELATIONSHIPS
            WHERE COMPANY_NAME ILIKE %(p)s AND (RELATIONSHIP_END_DATE IS NULL OR RELATIONSHIP_END_DATE >= CURRENT_DATE())
            LIMIT 30""", {"p": pattern})
        domains |= {r["DOMAIN_ID"] for r in rows if r["DOMAIN_ID"]}
    return domains


def _adviser(item: Item, name: str) -> Finding | None:
    pattern = like_pattern(name)
    if not pattern:
        return None
    rows = db.query(f"""
        SELECT COMPANY_NAME, REGISTRATION_STATUS, REGISTRATION_TYPE, CITY
        FROM {db.PUBLIC}.SEC_INVESTMENT_ADVISERS_INDEX
        WHERE COMPANY_NAME ILIKE %(p)s ORDER BY LENGTH(COMPANY_NAME) LIMIT 3""", {"p": pattern})
    rows = [r for r in rows if name_matches(name, r["COMPANY_NAME"])]
    if not rows:
        return None
    r = rows[0]
    ev = Evidence(SRC_ADVISERS, f"{r['COMPANY_NAME']}, {r['REGISTRATION_TYPE'] or 'registration'}: {r['REGISTRATION_STATUS']}, {r['CITY'] or ''}")
    status = "ok" if "approved" in str(r["REGISTRATION_STATUS"]).lower() else "caution"
    data = {"type": "adviser", "registered_name": r["COMPANY_NAME"], "status": r["REGISTRATION_STATUS"],
            "registration_type": r["REGISTRATION_TYPE"]}
    return _combine(item, f"{name}: adviser registration",
                    [(status, f"{r['COMPANY_NAME']} is in the SEC adviser registry ({r['REGISTRATION_STATUS']}).", ev)], data=data)


def _charity(item: Item, name: str) -> Finding | None:
    pattern = like_pattern(name)
    if not pattern:
        return None
    rows = db.query(f"""
        SELECT BUSINESS_NAME_FULL, EIN, CITY, STATE, TAX_YEAR
        FROM {db.PUBLIC}.IRS_FORM990_INDEX
        WHERE BUSINESS_NAME_FULL ILIKE %(p)s ORDER BY TAX_YEAR DESC LIMIT 5""", {"p": pattern})
    rows = [r for r in rows if name_matches(name, r["BUSINESS_NAME_FULL"])]
    if not rows:
        return None
    r = rows[0]
    ev = Evidence(SRC_CHARITIES, f"{r['BUSINESS_NAME_FULL']}, EIN {r['EIN']}, {r['CITY']}, {r['STATE']}, latest filing for tax year {r['TAX_YEAR']}")
    data = {"type": "charity", "registered_name": r["BUSINESS_NAME_FULL"], "ein": str(r["EIN"]), "tax_year": str(r["TAX_YEAR"])}
    return _combine(item, f"{name}: charity filings",
                    [("ok", f"{r['BUSINESS_NAME_FULL']} files annual IRS returns as a nonprofit.", ev)], data=data)


def _company(item: Item, name: str, domain: str | None, etype: str) -> Finding | None:
    title = f"{name}: identity check"
    parts: list[tuple[str, str, Evidence | None]] = []
    data = {"type": "company", "registered_name": None, "official_domains": [], "claimed_domain": domain, "domain_result": None}

    if domain in FREE_EMAIL_DOMAINS and etype in COMPANY_TYPES | {"bank", "credit_union", "lender"}:
        data["domain_result"] = "free_email"
        parts.append(("caution", f"It contacts you from a free personal email ({domain}), not a company domain. "
                                 "Real employers and property companies usually use their own domain.", None))
        domain = None

    pattern = like_pattern(name)
    known: list[dict] = []
    if pattern:
        known = [r for r in db.query(f"""
            SELECT COMPANY_NAME, DOMAIN_ID FROM {db.PUBLIC}.COMPANY_DOMAIN_RELATIONSHIPS
            WHERE COMPANY_NAME ILIKE %(p)s AND (RELATIONSHIP_END_DATE IS NULL OR RELATIONSHIP_END_DATE >= CURRENT_DATE())
            ORDER BY LENGTH(COMPANY_NAME) LIMIT 25""", {"p": pattern}) if name_matches(name, r["COMPANY_NAME"])]
    known_domains = sorted({r["DOMAIN_ID"] for r in known})
    data["official_domains"] = known_domains
    if known:
        data["registered_name"] = known[0]["COMPANY_NAME"]

    if domain:
        owners = db.query(f"""
            SELECT COMPANY_NAME FROM {db.PUBLIC}.COMPANY_DOMAIN_RELATIONSHIPS
            WHERE DOMAIN_ID = %(d)s AND (RELATIONSHIP_END_DATE IS NULL OR RELATIONSHIP_END_DATE >= CURRENT_DATE())
            LIMIT 5""", {"d": domain})
        if owners:
            owner_names = [o["COMPANY_NAME"] for o in owners]
            ev = Evidence(SRC_DOMAINS, f"{domain} is registered to {', '.join(owner_names[:3])}")
            if not name or any(name_matches(name, o) for o in owner_names):
                data.update(domain_result="official", registered_name=data["registered_name"] or owner_names[0])
                parts.append(("ok", f"The domain {domain} belongs to {owner_names[0]}.", ev))
            else:
                data.update(domain_result="owned_by_other", domain_owner=owner_names[0])
                parts.append(("caution", f"The domain {domain} belongs to {owner_names[0]}, not {name}.", ev))
        elif known_domains:
            ev = Evidence(SRC_DOMAINS, f"{known[0]['COMPANY_NAME']} uses {', '.join(known_domains[:4])}")
            relation = domain_brand_relation(domain, name, known[0]["COMPANY_NAME"])
            if relation == "lookalike":
                data["domain_result"] = "lookalike"
                parts.append(("red_flag", f"{name}'s registered domains are {', '.join(known_domains[:3])}, but this uses {domain}. "
                                          "Scammers often put a real company's name inside a lookalike domain.", ev))
            elif relation == "exact":
                data["domain_result"] = "brand_match"
                parts.append(("info", f"{domain} matches {name}'s name but isn't among its recorded domains "
                                      f"({', '.join(known_domains[:3])}). It may still be official.", ev))
            else:
                data["domain_result"] = "unrelated"
                parts.append(("caution", f"{domain} has no visible connection to {name}, whose registered domains are "
                                         f"{', '.join(known_domains[:3])}.", ev))
        elif domain_brand_relation(domain, name) == "lookalike":
            data["domain_result"] = "lookalike_unknown"
            parts.append(("caution", f"{domain} contains the name {name} but we have no record of which domains {name} "
                                     "really uses. Lookalike domains are a common impersonation trick.", None))
    elif known_domains:
        ev = Evidence(SRC_DOMAINS, f"{known[0]['COMPANY_NAME']} uses {', '.join(known_domains[:4])}")
        parts.append(("info", f"A company named {known[0]['COMPANY_NAME']} exists and uses {', '.join(known_domains[:2])}. "
                              "Check that any emails or links really come from that domain.", ev))

    if not parts:
        return None
    settled = any(p[0] in ("ok", "red_flag") for p in parts)
    return _combine(item, title, parts, followup=not settled, data=data)

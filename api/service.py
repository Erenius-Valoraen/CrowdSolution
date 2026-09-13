"""
Verification service layer.
Connects the legit engine to the frontend JSON contract.
Generates actionable checklists, badge metadata, and structured groupings.
"""
from __future__ import annotations

import datetime as dt
import uuid
from datetime import date
from typing import Any

from legit import db, report, router
from legit.models import SEVERITY, Finding, Report
from legit.report import KIND_LABELS, TAGS

from . import storage

STATUS_COLOR = {
    "red_flag": "red",
    "caution": "yellow",
    "ok": "green",
    "info": "blue",
    "unverified": "gray",
}

OVERALL_META = {
    "HIGH RISK": {
        "color": "red",
        "message": "High risk detected. Do not send money, deposits, or sensitive personal information.",
    },
    "BE CAREFUL": {
        "color": "yellow",
        "message": "Caution advised. Several details do not hold up or require in-person verification.",
    },
    "NO RED FLAGS FOUND": {
        "color": "green",
        "message": "No obvious red flags found. Terms and entities appear consistent with known standards.",
    },
    "COULDN'T VERIFY": {
        "color": "gray",
        "message": "Could not confirm these details against official records. Verify independently before proceeding.",
    },
    "NOTHING TO CHECK": {
        "color": "gray",
        "message": "No verifiable claims, prices, or offers were identified in this text.",
    },
}


def generate_checklist(context: str, overall: str, findings: list[Finding]) -> list[str]:
    """Generate 3-5 concrete, actionable steps a student can take on their phone."""
    has_red_flags = any(f.status == "red_flag" for f in findings)
    has_caution = any(f.status == "caution" for f in findings)
    has_zelle_etransfer = any("payment" in f.title.lower() or "zelle" in f.summary.lower() or "etransfer" in f.summary.lower() for f in findings)
    has_cannot_view = any("see it in person" in f.title.lower() or "mail" in f.summary.lower() for f in findings)

    steps: list[str] = []

    if context == "housing":
        if has_red_flags or has_zelle_etransfer:
            steps.append("Never send a deposit, holding fee, or rent by Zelle, e-transfer, wire, or gift cards.")
        if has_cannot_view or has_red_flags:
            steps.append("Demand an in-person walkthrough or live interactive video call. If they refuse, walk away.")
        steps.append("Ask for their full legal name and check the property address on municipal rental licensing records.")
        steps.append("Reverse-image search all listing photos to see if they are copied from legitimate real estate sites.")
        steps.append("Remember: in Ontario and many jurisdictions, damage deposits are illegal—only first/last month is permitted.")

    elif context == "job":
        if has_red_flags:
            steps.append("Legitimate employers never charge candidates for training, background checks, or equipment kits.")
        steps.append("Look up the employer on the official corporate registry and verify the recruiter's email domain matches.")
        steps.append("Never deposit a check sent to you with instructions to wire or transfer a portion back to anyone.")
        steps.append("Do not provide your Social Insurance Number (SIN) or bank logins until an official written contract is verified.")

    elif context == "finance":
        steps.append("Never share your bank password, 2FA codes, or SIN/SSN over SMS, email, or unverified messaging apps.")
        steps.append("Contact the financial institution directly via the phone number printed on the back of your card.")
        steps.append("Guaranteed high-return offers or 'crypto investments' are almost always scams.")

    elif context == "school":
        steps.append("Verify the institution's official accreditation on the government education registry.")
        steps.append("Compare tuition, graduation rates, and median graduate debt using the College Scorecard.")
        steps.append("Reach out to current students or alumni on LinkedIn to confirm program reputation.")

    else:
        if has_red_flags:
            steps.append("Pause immediately. High-risk patterns were detected in this message.")
        steps.append("Never send untraceable funds to anyone you haven't verified in person.")
        steps.append("Verify claims against official consumer protection or government websites.")
        steps.append("When in doubt, show this to an adviser, student legal clinic, or housing advisor before committing.")

    return steps[:5]


def verify_text(text: str, seen_on_str: str | None = None, offline: bool = False) -> dict[str, Any]:
    """
    Run extraction and verification, returning a frontend-ready JSON dictionary.
    """
    # Parse seen_on date
    if seen_on_str:
        try:
            seen_on = date.fromisoformat(seen_on_str)
        except ValueError:
            seen_on = date.today()
    else:
        seen_on = date.today()

    try:
        rep: Report = router.run(text, seen_on, offline=offline)
    finally:
        db.close()

    scan_id = f"chk_{uuid.uuid4().hex[:10]}"
    now_iso = dt.datetime.now(dt.timezone.utc).isoformat()

    ext = rep.extraction
    overall = rep.overall
    meta = OVERALL_META.get(overall, {"color": "gray", "message": "Verify details independently."})

    # Counts
    counts = {
        "red_flag": rep.count("red_flag"),
        "caution": rep.count("caution"),
        "ok": rep.count("ok"),
        "info": rep.count("info"),
        "unverified": rep.count("unverified"),
        "total": len(rep.findings),
    }

    # Format findings
    formatted_findings = []
    grouped = {
        "red_flags": [],
        "cautions": [],
        "ok": [],
        "context": [],
        "unverified": [],
    }

    sorted_findings = sorted(rep.findings, key=lambda f: (-SEVERITY.get(f.status, 0), f.item.id))

    for f in sorted_findings:
        color = STATUS_COLOR.get(f.status, "gray")
        status_label = TAGS.get(f.status, f.status.upper())

        evidence_items = []
        for ev in f.evidence:
            evidence_items.append({
                "source": ev.source,
                "detail": ev.detail,
                "kind": ev.kind,
                "kind_label": KIND_LABELS.get(ev.kind, ev.kind),
                "url": ev.url,
            })

        item_dict = {
            "id": f.item.id,
            "kind": f.item.kind,
            "status": f.status,
            "status_label": status_label,
            "color": color,
            "title": f.title,
            "quote": f.item.text or "",
            "summary": f.summary or "",
            "checker": f.checker,
            "evidence": evidence_items,
            "data": f.data,
        }

        formatted_findings.append(item_dict)

        if f.status == "red_flag":
            grouped["red_flags"].append(item_dict)
        elif f.status == "caution":
            grouped["cautions"].append(item_dict)
        elif f.status == "ok":
            grouped["ok"].append(item_dict)
        elif f.status == "info":
            grouped["context"].append(item_dict)
        else:
            grouped["unverified"].append(item_dict)

    checklist = generate_checklist(ext.context, overall, rep.findings)

    # Location info
    loc_dict = {
        "city": ext.location.city,
        "region": ext.location.region,
        "country": ext.location.country,
        "label": ext.location.label(),
    }

    payload = {
        "id": scan_id,
        "created_at": now_iso,
        "overall": overall,
        "overall_badge": {
            "label": overall,
            "color": meta["color"],
            "message": meta["message"],
        },
        "counts": counts,
        "summary": ext.summary or "No summary generated.",
        "context": ext.context,
        "location": loc_dict,
        "action_checklist": checklist,
        "findings": formatted_findings,
        "grouped_findings": grouped,
        "notes": rep.notes,
        "raw_report": {
            "parser": ext.parser,
            "said_on": ext.said_on.isoformat(),
            "items_count": len(ext.items),
        },
    }

    # Persist to local history
    storage.save_scan(
        scan_id=scan_id,
        text=text,
        context=ext.context,
        overall=overall,
        overall_color=meta["color"],
        findings_count=len(formatted_findings),
        payload=payload,
    )

    return payload


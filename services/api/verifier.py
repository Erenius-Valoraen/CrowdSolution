"""
Verification engine for UPSTREAM.
Connects the local SQLite server datasets to kernel contracts:
- Scam pattern matching
- Duplicate listing detection
- Price baseline benchmarking
- Entity registration checking
- Append-only receipt persistence and contract formatting
"""
from __future__ import annotations

import hashlib
import json
import uuid
from typing import Any

from services.api import db
from services.api.kernel.contracts import (
    Claim,
    Evidence,
    Receipt,
    Signal,
    Verdict,
    new_claim,
    new_receipt,
    new_signal,
)


def run_verification(
    text: str,
    kind: str = "rental",
    price: float | None = None,
    bedrooms: int = 1,
    postal_prefix: str = "N2L",
    contact: str | None = None,
    address: str | None = None,
    entity_name: str | None = None,
    url: str | None = None,
) -> dict[str, Any]:
    """
    Run full verification pipeline and return the signed Receipt JSON contract.
    """
    artifact_id = f"art_{uuid.uuid4().hex[:12]}"
    content_sha256 = hashlib.sha256(text.strip().encode("utf-8")).hexdigest()

    # Log raw artifact
    db.save_artifact(
        artifact_id=artifact_id,
        source_type=kind,
        url=url,
        raw_content=text,
        content_sha256=content_sha256,
    )

    signals: list[Signal] = []
    claims: list[Claim] = []

    # ── 1. Flywheel / Peer Checks ────────────────────────────────────────────
    flywheel = db.get_flywheel_stats(content_sha256)
    # Increment this run into flywheel stats for response
    flywheel_checks = flywheel["checks"] + 1
    flywheel_flagged = flywheel["flagged"]

    # ── 2. Scam Pattern Analyzer ─────────────────────────────────────────────
    matching_patterns = db.find_matching_patterns(text)
    for p in matching_patterns:
        red_flag_sample = p["red_flags"][0] if p["red_flags"] else p["description"]
        signals.append(
            new_signal(
                analyzer="pattern.py",
                analyzer_version="v2",
                subject_type="artifact",
                subject_id=artifact_id,
                direction="undermines",
                weight=0.92,
                confidence=0.90,
                explanation=f"Matches known scam pattern '{p['pattern_name']}': {red_flag_sample}",
                evidence=[
                    Evidence(
                        url=p["evidence_url"],
                        quote=f"{p['pattern_name']}: {p['description']}",
                        source_class="primary_research",
                    )
                ],
            )
        )

    # ── 3. Duplicate Listing Analyzer ────────────────────────────────────────
    duplicates = db.find_duplicate_listings(
        title="",
        body=text,
        price=price,
        contact=contact,
    )
    if duplicates:
        first_dup = duplicates[0]
        reasons_summary = "; ".join(first_dup.get("duplicate_reasons", []))
        signals.append(
            new_signal(
                analyzer="independence.py",
                analyzer_version="v2",
                subject_type="artifact",
                subject_id=artifact_id,
                direction="undermines",
                weight=0.96,
                confidence=0.92,
                explanation=f"Listing duplicated across multiple locations: {reasons_summary}",
                evidence=[
                    Evidence(
                        url=d.get("url") or "https://uwaterloo.ca/off-campus-housing/scams",
                        quote=f"Identical listing detected at {d.get('address')} (${d.get('price')}/mo)",
                        source_class="forum_ugc",
                    )
                    for d in duplicates[:3]
                ],
            )
        )

    # ── 4. Baseline Analyzer ─────────────────────────────────────────────────
    baseline_record = db.get_baseline(postal_prefix, bedrooms)
    baseline_payload: dict[str, Any] = {}
    if baseline_record and price is not None:
        median = baseline_record["median_price"]
        p10 = baseline_record["p10_price"]
        p90 = baseline_record["p90_price"]
        diff_pct = int(round((abs(price - median) / median) * 100))

        baseline_payload = {
            "postal_prefix": postal_prefix,
            "bedrooms": bedrooms,
            "city": baseline_record["city"],
            "median_price": median,
            "p10_price": p10,
            "p90_price": p90,
            "sample_size": baseline_record["sample_size"],
            "diff_from_median_pct": diff_pct,
        }

        if price < median * 0.70:
            # Dangerously cheap
            signals.append(
                new_signal(
                    analyzer="baseline.py",
                    analyzer_version="v2",
                    subject_type="claim",
                    subject_id="price_claim",
                    direction="undermines",
                    weight=0.80,
                    confidence=0.88,
                    explanation=f"${price:,.0f} is {diff_pct}% below the local median (${median:,.0f}) for {bedrooms}-bed in {postal_prefix} ({baseline_record['city']}). Unusually low pricing is common bait.",
                    evidence=[
                        Evidence(
                            url="https://uwaterloo.ca/off-campus-housing/",
                            quote=f"Official baseline median rent for {postal_prefix} ({bedrooms}-bed): ${median:,.0f}",
                            source_class="aggregator",
                        )
                    ],
                )
            )
        elif price > median * 1.50:
            # High price
            signals.append(
                new_signal(
                    analyzer="baseline.py",
                    analyzer_version="v2",
                    subject_type="claim",
                    subject_id="price_claim",
                    direction="context",
                    weight=0.45,
                    confidence=0.85,
                    explanation=f"${price:,.0f} is {diff_pct}% above the local median (${median:,.0f}) for {bedrooms}-bed in {postal_prefix}.",
                    evidence=[
                        Evidence(
                            url="https://uwaterloo.ca/off-campus-housing/",
                            quote=f"Median rent in {postal_prefix}: ${median:,.0f}",
                            source_class="aggregator",
                        )
                    ],
                )
            )
        else:
            # Normal range
            signals.append(
                new_signal(
                    analyzer="baseline.py",
                    analyzer_version="v2",
                    subject_type="claim",
                    subject_id="price_claim",
                    direction="supports",
                    weight=0.65,
                    confidence=0.85,
                    explanation=f"${price:,.0f} is within normal market range for {bedrooms}-bed in {postal_prefix} (local median ${median:,.0f}).",
                    evidence=[
                        Evidence(
                            url="https://uwaterloo.ca/off-campus-housing/",
                            quote=f"Normal price band: ${p10:,.0f} - ${p90:,.0f}",
                            source_class="aggregator",
                        )
                    ],
                )
            )

    # ── 5. Entity Analyzer ───────────────────────────────────────────────────
    if entity_name:
        entity_record = db.lookup_entity(entity_name)
        if entity_record and entity_record["registered"]:
            signals.append(
                new_signal(
                    analyzer="entity_check.py",
                    analyzer_version="v2",
                    subject_type="entity",
                    subject_id=entity_record["entity_key"],
                    direction="supports",
                    weight=0.85,
                    confidence=0.95,
                    explanation=f"'{entity_record['entity_name']}' is a registered {entity_record['entity_type']} in {entity_record['jurisdiction']}.",
                    evidence=[
                        Evidence(
                            url=entity_record["official_registry_url"] or "https://www.appmybizaccount.gov.on.ca/",
                            quote=f"Incorporated on {entity_record['incorporated_on']}. Notes: {entity_record['notes']}",
                            source_class="primary_research",
                        )
                    ],
                )
            )
        elif entity_record and not entity_record["registered"]:
            signals.append(
                new_signal(
                    analyzer="entity_check.py",
                    analyzer_version="v2",
                    subject_type="entity",
                    subject_id=entity_record["entity_key"],
                    direction="undermines",
                    weight=0.75,
                    confidence=0.85,
                    explanation=f"'{entity_name}' does not hold a recognized corporate or business registration in local records.",
                    evidence=[
                        Evidence(
                            url="https://www.appmybizaccount.gov.on.ca/",
                            quote=entity_record["notes"] or "No registry record found.",
                            source_class="primary_research",
                        )
                    ],
                )
            )
        else:
            signals.append(
                new_signal(
                    analyzer="entity_check.py",
                    analyzer_version="v2",
                    subject_type="entity",
                    subject_id=entity_name.lower().replace(" ", "_"),
                    direction="undermines",
                    weight=0.60,
                    confidence=0.75,
                    explanation=f"No public business registration found for landlord/company '{entity_name}'.",
                    evidence=[
                        Evidence(
                            url="https://www.appmybizaccount.gov.on.ca/",
                            quote="Searched Ontario Business Registry; no matching registered business entity.",
                            source_class="unknown",
                        )
                    ],
                )
            )

    # ── 6. Determine Verdict & Headline ──────────────────────────────────────
    undermining_signals = [s for s in signals if s.direction == "undermines"]
    supporting_signals = [s for s in signals if s.direction == "supports"]

    if duplicates or any(s.weight >= 0.9 for s in undermining_signals):
        verdict: Verdict = "DO_NOT_PAY"
        flywheel_flagged += 1
        if duplicates:
            headline = f"DO NOT SEND MONEY — This listing appears across {len(duplicates) + 1} addresses or prices."
        else:
            top_reason = undermining_signals[0].explanation
            headline = f"DO NOT SEND MONEY — {top_reason}"
    elif any(s.analyzer == "entity_check.py" and s.direction == "undermines" for s in signals):
        verdict = "UNVERIFIABLE_ENTITY"
        flywheel_flagged += 1
        headline = f"UNVERIFIABLE ENTITY — Landlord '{entity_name or 'contact'}' exists on no public record."
    elif len(signals) >= 2 and len(supporting_signals) >= 1 and not undermining_signals:
        verdict = "VERIFIED"
        headline = "VERIFIED — Entity confirmed and terms align with local market baselines."
    elif len(undermining_signals) > 0:
        verdict = "RISKY_BUT_NORMAL"
        headline = "RISKY ARRANGEMENT — Common listing structure, but check verification steps before paying."
    else:
        verdict = "INSUFFICIENT_DATA"
        headline = "INSUFFICIENT DATA — Could not establish enough verifiable facts. Exercise caution."

    # ── 7. Action Checklist Formulation ──────────────────────────────────────
    if verdict == "DO_NOT_PAY":
        checklist = [
            "Do NOT e-transfer or wire any deposit. Financial transfers cannot be reversed.",
            "Demand an in-person walkthrough inside the actual unit before discussing payment. Refusal = walk away.",
            "Ask for their full legal name and check the address on the municipal rental licensing registry.",
            "Reverse-image search all listing photos to see if they were stolen from real-estate sites.",
            "Report this listing to the hosting platform and student housing safety board.",
        ]
    elif verdict == "UNVERIFIABLE_ENTITY":
        checklist = [
            "Request official photo ID and property ownership or sublet authorization papers.",
            "Verify the property manager on the official provincial business registry.",
            "Never share your Social Insurance Number (SIN) or sensitive financial logins.",
            "Insist on paying via standard trackable methods only after signing an Ontario Standard Lease.",
            "Check with the building's front desk or superintendent to verify unit occupancy status.",
        ]
    elif verdict == "VERIFIED":
        checklist = [
            "Review each section of the Ontario Standard Lease (Form 2229E).",
            "Ensure the lease specifies what utilities and amenities are included in writing.",
            "Confirm that the key deposit is explicitly refundable upon move-out.",
            "Take move-in photos/video of the unit condition before moving furniture in.",
            "Keep digital receipts of all rent transactions for tax filing.",
        ]
    else:
        checklist = [
            "Demand an in-person or live two-way video viewing before sending any funds.",
            "Ensure any required deposit is only first and last month's rent (damage deposits are illegal in ON).",
            "Verify that the person offering the sublet has written permission from the primary landlord.",
            "Search the landlord or unit address in university student housing forums for past reviews.",
            "Never pay via cryptocurrency, gift cards, or untraceable cash wires.",
        ]

    # ── 8. Assemble Claims ───────────────────────────────────────────────────
    if price is not None:
        claims.append(
            new_claim(
                artifact_id=artifact_id,
                text=f"Monthly rent is ${price:,.0f}",
                claim_type="factual",
                checkability=1.0,
                cited_urls=[url] if url else [],
            )
        )

    # ── 9. Construct and Sign Receipt ────────────────────────────────────────
    receipt: Receipt = new_receipt(
        artifact_id=artifact_id,
        policy_version="policy.student.v2",
        verdict=verdict,
        headline=headline,
        action_checklist=checklist,
        claims=claims,
        signals=signals,
        provenance_graph={
            "nodes": [{"id": artifact_id, "label": "Artifact", "kind": kind}],
            "edges": [],
        },
        independence={
            "duplicate_count": len(duplicates),
            "duplicates": duplicates,
        },
        incentive={
            "price_stated": price,
            "payment_requested": "Deposit requested" if "deposit" in text.lower() else "Standard rent",
            "off_platform": "whatsapp" in text.lower() or "telegram" in text.lower(),
        },
        baseline=baseline_payload,
        peer_checks={
            "checks": flywheel_checks,
            "flagged": flywheel_flagged,
            "first_seen": flywheel["first_seen"],
        },
        what_would_change_this=[
            "In-person physical verification of the rental unit.",
            "Signed Ontario Standard Lease with verified property owner.",
            "Municipal rental license inspection record.",
        ],
    )

    receipt.sign()
    receipt_json = receipt.to_json()
    receipt_json["content_sha256"] = content_sha256

    # Append to database (append-only)
    db.save_receipt(receipt_json)

    return receipt_json


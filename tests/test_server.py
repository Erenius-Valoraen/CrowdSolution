"""
End-to-end tests for UPSTREAM verification server.
Tests CRUD operations, pattern matching, baseline calculation,
contract compliance, and append-only invariants.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

# Add repo root to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi.testclient import TestClient
from services.api.main import app
from services.api.seed_data import seed_database

# Ensure clean seed state
seed_database()
client = TestClient(app)


def test_health():
    response = client.get("/api/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "healthy"
    assert data["counts"]["scam_patterns"] >= 5
    assert data["counts"]["local_baselines"] >= 5
    print("[PASS] Health check passed:", data["counts"])


def test_check_scam_deposit_before_viewing():
    # Listing demanding e-transfer deposit before viewing
    payload = {
        "text": "Beautiful 1 bed condo on Columbia St. High demand so you must send $1000 deposit before viewing to hold the keys. Contact me on whatsapp.",
        "kind": "rental",
        "price": 1000.0,
        "bedrooms": 1,
        "postal_prefix": "N2L",
        "contact": "519-555-9999",
    }
    response = client.post("/api/check", json=payload)
    assert response.status_code == 200
    data = response.json()

    # Invariants verification
    assert data["verdict"] == "DO_NOT_PAY"
    assert "DO NOT SEND MONEY" in data["headline"]
    assert len(data["action_checklist"]) == 5
    assert len(data["signals"]) >= 1
    assert data["receipt_sha256"] != ""

    # Every signal must have evidence with a URL
    for sig in data["signals"]:
        assert len(sig["evidence"]) >= 1
        for ev in sig["evidence"]:
            assert ev["url"].startswith("http")

    receipt_id = data["receipt_id"]
    print(f"[PASS] Scam check passed (Verdict: {data['verdict']}, Receipt ID: {receipt_id})")

    # Verify retrieval
    get_res = client.get(f"/api/receipts/{receipt_id}")
    assert get_res.status_code == 200
    retrieved = get_res.json()
    assert retrieved["receipt_id"] == receipt_id
    assert retrieved["verdict"] == "DO_NOT_PAY"
    print("[PASS] Retrieval by receipt_id passed")


def test_check_duplicate_scam_cluster():
    # Listing matching pre-seeded duplicate scam text
    payload = {
        "text": "Cozy 1 Bedroom luxury apartment fully furnished with all utilities included gym and pool",
        "kind": "rental",
        "price": 850.0,
        "bedrooms": 1,
        "postal_prefix": "N2L",
        "contact": "rentals.mark.uw@gmail.com",
    }
    response = client.post("/api/check", json=payload)
    assert response.status_code == 200
    data = response.json()

    assert data["verdict"] == "DO_NOT_PAY"
    assert any(s["analyzer"] == "independence.py" for s in data["signals"])
    assert data["independence"]["duplicate_count"] >= 1
    print("[PASS] Duplicate listing detection passed:", data["headline"])


def test_check_legitimate_listing():
    # Legitimate listing with registered entity and normal price
    payload = {
        "text": "Official 1-bedroom student sublet at Fergus House. In-person walkthrough scheduled at your convenience. Valid Ontario Standard Lease provided upon approval.",
        "kind": "rental",
        "price": 1450.0,
        "bedrooms": 1,
        "postal_prefix": "N2L",
        "entity_name": "Rez-One Properties",
        "contact": "leasing@rez-one.ca",
    }
    response = client.post("/api/check", json=payload)
    assert response.status_code == 200
    data = response.json()

    assert data["verdict"] in ("VERIFIED", "RISKY_BUT_NORMAL")
    assert any(s["analyzer"] == "entity_check.py" and s["direction"] == "supports" for s in data["signals"])
    assert any(s["analyzer"] == "baseline.py" and s["direction"] == "supports" for s in data["signals"])
    print(f"[PASS] Legitimate listing check passed (Verdict: {data['verdict']})")


def test_baselines_and_patterns_endpoints():
    # Query specific baseline
    res_b = client.get("/api/baselines?postal_prefix=N2L&bedrooms=1")
    assert res_b.status_code == 200
    baseline = res_b.json()
    assert baseline["median_price"] == 1400.0
    assert baseline["bedrooms"] == 1
    print("[PASS] Baselines endpoint passed:", baseline)

    # Query scam patterns catalog
    res_p = client.get("/api/patterns")
    assert res_p.status_code == 200
    patterns = res_p.json()
    assert len(patterns) >= 5
    print(f"[PASS] Patterns endpoint passed ({len(patterns)} patterns cataloged)")

    # Query flywheel
    test_hash = "sample_test_hash"
    res_f = client.get(f"/api/flywheel/{test_hash}")
    assert res_f.status_code == 200
    flywheel = res_f.json()
    assert "checks" in flywheel
    assert "flagged" in flywheel
    print("[PASS] Flywheel endpoint passed:", flywheel)


def test_append_only_receipts_list():
    res = client.get("/api/receipts?limit=10")
    assert res.status_code == 200
    receipts_list = res.json()
    assert len(receipts_list) >= 3
    print(f"[PASS] Receipts list passed: {len(receipts_list)} receipts in append-only log")


if __name__ == "__main__":
    test_health()
    test_check_scam_deposit_before_viewing()
    test_check_duplicate_scam_cluster()
    test_check_legitimate_listing()
    test_baselines_and_patterns_endpoints()
    test_append_only_receipts_list()
    print("\n[SUCCESS] ALL TESTS PASSED SUCCESSFULLY!")

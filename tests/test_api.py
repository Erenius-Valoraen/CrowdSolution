"""
Automated integration tests for the Frontend JSON API.
Tests POST /api/verify, GET /api/scans/{id}, GET /api/history, and GET /api/examples.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

# Add repo root to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi.testclient import TestClient
from api.main import app

client = TestClient(app)


def test_health():
    response = client.get("/api/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "healthy"
    assert data["groq_api_configured"] is True
    print("[PASS] /api/health passed. Groq is configured.")


def test_examples():
    response = client.get("/api/examples")
    assert response.status_code == 200
    examples = response.json()
    assert len(examples) >= 4
    print(f"[PASS] /api/examples passed with {len(examples)} pre-configured examples.")


def test_verify_rental_scam():
    payload = {
        "text": "Cozy 2BR near campus, $650/month. I'm abroad, send the deposit by Zelle and I'll mail the keys.",
        "offline": True,
    }
    response = client.post("/api/verify", json=payload)
    assert response.status_code == 200
    data = response.json()

    # Invariants verification
    assert data["overall"] == "HIGH RISK"
    assert data["overall_badge"]["color"] == "red"
    assert data["counts"]["red_flag"] >= 1
    assert len(data["action_checklist"]) >= 3
    assert len(data["findings"]) >= 1
    assert len(data["grouped_findings"]["red_flags"]) >= 1

    # Check evidence structure
    for finding in data["findings"]:
        assert finding["title"] != ""
        assert finding["status"] in ("red_flag", "caution", "ok", "info", "unverified")
        for ev in finding["evidence"]:
            assert ev["source"] != ""

    scan_id = data["id"]
    print(f"[PASS] /api/verify passed (ID: {scan_id}, Overall: {data['overall']}, Red Flags: {data['counts']['red_flag']})")

    # Test retrieval by ID
    get_res = client.get(f"/api/scans/{scan_id}")
    assert get_res.status_code == 200
    retrieved = get_res.json()
    assert retrieved["id"] == scan_id
    assert retrieved["overall"] == "HIGH RISK"
    print(f"[PASS] /api/scans/{scan_id} retrieved successfully.")


def test_history():
    response = client.get("/api/history")
    assert response.status_code == 200
    history = response.json()
    assert len(history) >= 1
    assert "id" in history[0]
    assert "overall" in history[0]
    print(f"[PASS] /api/history returned {len(history)} scan(s).")


def test_empty_text_validation():
    response = client.post("/api/verify", json={"text": "   ", "offline": True})
    assert response.status_code in (400, 422)
    print("[PASS] Validation for empty text returned expected client error.")


if __name__ == "__main__":
    test_health()
    test_examples()
    test_verify_rental_scam()
    test_history()
    test_empty_text_validation()
    print("\n[SUCCESS] ALL API TESTS PASSED!")


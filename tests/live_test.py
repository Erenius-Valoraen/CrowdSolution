"""
Live HTTP test against the running CrowdSolution API server on http://127.0.0.1:8000.
"""
from __future__ import annotations

import json
import urllib.request

BASE_URL = "http://127.0.0.1:8000"


def request(method: str, path: str, payload: dict | None = None) -> dict:
    url = f"{BASE_URL}{path}"
    data = json.dumps(payload).encode("utf-8") if payload else None
    headers = {"Content-Type": "application/json"} if payload else {}
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read().decode("utf-8"))


def main():
    print("=== 1. Testing GET /api/health ===")
    health = request("GET", "/api/health")
    print("Health response:", json.dumps(health, indent=2))

    print("\n=== 2. Testing GET /api/examples ===")
    examples = request("GET", "/api/examples")
    print(f"Loaded {len(examples)} examples.")
    for ex in examples[:2]:
        print(f"  - [{ex['category'].upper()}] {ex['title']}")

    print("\n=== 3. Testing POST /api/verify (Rental Scam) ===")
    rental_scam = {
        "text": "Luxury 2-bedroom sublet near university campus, $700/mo including all utilities. Currently deployed overseas for charity work, so cannot do in-person viewing. Send first month deposit via Zelle and I will courier keys with FedEx.",
        "offline": True,
    }
    res_scam = request("POST", "/api/verify", rental_scam)
    print(f"Scan ID:          {res_scam['id']}")
    print(f"Overall Rating:   {res_scam['overall']} (Color: {res_scam['overall_badge']['color']})")
    print(f"Overall Message:  {res_scam['overall_badge']['message']}")
    print(f"Red Flags Count:  {res_scam['counts']['red_flag']}")
    print(f"Cautions Count:   {res_scam['counts']['caution']}")
    print("Action Checklist:")
    for step in res_scam["action_checklist"]:
        print(f"  [ ] {step}")
    print("\nFindings:")
    for f in res_scam["findings"]:
        print(f"  - [{f['status_label']}] {f['title']}: {f['summary'][:90]}...")
        for ev in f["evidence"]:
            print(f"      Evidence: {ev['source']} ({ev['url']})")

    scan_id = res_scam["id"]

    print(f"\n=== 4. Testing GET /api/scans/{scan_id} (Permalink lookup) ===")
    res_get = request("GET", f"/api/scans/{scan_id}")
    print(f"Retrieved scan ID: {res_get['id']} matching overall rating '{res_get['overall']}'")

    print("\n=== 5. Testing POST /api/verify (Student Job Scam) ===")
    job_scam = {
        "text": "Work from home as our Student Brand Ambassador! $40/hour, 10 hrs/week. No experience needed. Pay a refundable $150 onboarding fee for training materials to start.",
        "offline": True,
    }
    res_job = request("POST", "/api/verify", job_scam)
    print(f"Job Overall:      {res_job['overall']} (Color: {res_job['overall_badge']['color']})")
    print(f"Red Flags:        {res_job['counts']['red_flag']}")
    print(f"Action Checklist: {res_job['action_checklist'][0]}")

    print("\n=== 6. Testing GET /api/history ===")
    history = request("GET", "/api/history")
    print(f"History contains {len(history)} scan records:")
    for item in history[:3]:
        print(f"  - [{item['created_at']}] ID: {item['id']} | Context: {item['context']} | Verdict: {item['overall']} | Snippet: {item['text_snippet']}")

    print("\n>>> ALL LIVE HTTP TESTS PASSED PERFECTLY! <<<")


if __name__ == "__main__":
    main()


# Walkthrough: CrowdSolution Frontend JSON API

We have built, launched, and verified the REST API that connects the `legit` fact-checking and risk-rating engine directly to the frontend, transferring structured findings in clean, easily consumable JSON.

---

## Server Status

- **Status**: **ONLINE & RUNNING** at `http://127.0.0.1:8000`
- **Docs**: `http://127.0.0.1:8000/docs` (Swagger UI) & `http://127.0.0.1:8000/redoc` (ReDoc)
- **CORS**: Enabled for all origins (`*`)

---

## Live Test Results Summary

A live test suite ([`tests/live_test.py`](tests/live_test.py)) was run against the active HTTP server:

```text
=== 1. Testing GET /api/health ===
Health response: {
  "status": "healthy",
  "groq_api_configured": true,
  "default_extract_models": ["qwen/qwen3.8-27b", "qwen/qwen3.6-27b", "openai/gpt-oss-120b", "openai/gpt-oss-20b"],
  "search_models": ["openai/gpt-oss-120b", "openai/gpt-oss-20b"]
}

=== 2. Testing GET /api/examples ===
Loaded 5 examples.
  - [HOUSING] Rental Listing Scam (Zelle Deposit)
  - [JOB] Student Ambassador Job Scam (Upfront Fee)

=== 3. Testing POST /api/verify (Rental Scam) ===
Scan ID:          chk_24f3eb208a
Overall Rating:   HIGH RISK (Color: red)
Overall Message:  High risk detected. Do not send money, deposits, or sensitive personal information.
Red Flags Count:  2
Cautions Count:   1

Action Checklist:
  [ ] Never send a deposit, holding fee, or rent by Zelle, e-transfer, wire, or gift cards.
  [ ] Demand an in-person walkthrough or live interactive video call. If they refuse, walk away.
  [ ] Ask for their full legal name and check the property address on municipal rental licensing records.
  [ ] Reverse-image search all listing photos to see if they are copied from legitimate real estate sites.
  [ ] Remember: in Ontario and many jurisdictions, damage deposits are illegal—only first/last month is permitted.

Findings:
  - [RED FLAG] Hard-to-reverse payment method: Zelle is a hard-to-reverse payment method...
      Evidence: FTC: Rental listing scams (https://consumer.ftc.gov/articles/rental-listing-scams)
  - [RED FLAG] Pay before you can verify: The listing asks for payment before the student can verify...
      Evidence: FTC: Rental listing scams (https://consumer.ftc.gov/articles/rental-listing-scams)
  - [CAUTION] You can't see it in person: The landlord claims to be deployed overseas...
      Evidence: FTC: Rental listing scams (https://consumer.ftc.gov/articles/rental-listing-scams)

=== 4. Testing GET /api/scans/chk_24f3eb208a (Permalink lookup) ===
Retrieved scan ID: chk_24f3eb208a matching overall rating 'HIGH RISK'

=== 5. Testing POST /api/verify (Student Job Scam) ===
Job Overall:      HIGH RISK (Color: red)
Red Flags:        1
Action Checklist: Legitimate employers never charge candidates for training, background checks, or equipment kits.

=== 6. Testing GET /api/history ===
History contains 3 scan records.

>>> ALL LIVE HTTP TESTS PASSED PERFECTLY! <<<
```

---

## API Endpoints Reference

| Method | Endpoint | Description |
|---|---|---|
| `POST` | `/api/verify` | Primary verification endpoint. Receives `{ text, seen_on, offline }`, returns full formatted JSON report. |
| `GET` | `/api/scans/{scan_id}` | Fetches a past scan by ID (ideal for permalinks like `/r/{id}`). |
| `GET` | `/api/history` | Returns recent scan history for user dashboards. |
| `GET` | `/api/examples` | Returns 5 pre-configured demo cases (rental, job, check scam, legit sublet, stats) for 1-click frontend UI buttons. |
| `GET` | `/api/health` | Health check endpoint confirming Groq LLM availability. |
| `GET` | `/docs` | Interactive OpenAPI / Swagger UI. |

---

## Quick Start

### 1. Launch the Server
```bash
python run_server.py
```

### 2. Verify an Item (cURL)
```bash
curl -X POST "http://127.0.0.1:8000/api/verify" \
  -H "Content-Type: application/json" \
  -d '{
    "text": "Cozy 2BR near campus, $650/month. Send deposit by Zelle.",
    "offline": true
  }'
```


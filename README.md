# CrowdSolution — Is This Legit?

**PivotHacks 2026 Project**

CrowdSolution is a real-time fact-checking and risk-rating engine built for university students living independently for the first time. Paste a rental listing, job offer, lease clause, bank message, or claim: it checks every detail against official data first, then the web, and returns a blunt risk verdict with verified sources, categorized findings, and an actionable checklist.

---

## The Problem & The User

- **The Problem:** Students constantly struggle to decide which online claims, recommendations, rental listings, job offers, or financial messages to trust.
- **The User (Maya, 19):** Living on her own for the first time with a tight student budget. She doesn't have experience signing leases or knowing local rent baselines. Decisions like e-transferring a deposit or paying an upfront "training fee" can cost money she cannot replace.
- **The Core Rule:** We do not output an arbitrary "trust score" like 62%. We classify clear risk (`HIGH RISK`, `BE CAREFUL`, `NO RED FLAGS FOUND`), cite clickable official sources, and tell students exactly what to do before paying.

---

## How We Got Here

| Stage | Direction |
|---|---|
| **Start** | *"Was it true when they said it?"* Checked statistical claims in speeches and articles against official point-in-time US economic data. |
| **Pivot 1** | Widened focus to the university student living alone. Added rental registries, price benchmarks, complaint registries, scam patterns, and web fallback. The statistics engine became one checker in a comprehensive screening system. |
| **Current Stage** | **Frontend JSON API.** Built a high-performance FastAPI server with CORS, persistent audit history, and structured JSON contracts designed for direct consumption by web and mobile frontends. |

---

## Repo Layout

| Path | Description |
|---|---|
| `api/` | **FastAPI Server**: REST API endpoints, Pydantic schemas, persistent audit history, and JSON contract formatter |
| `legit/` | **Verification Engine**: AI extraction, evidence checkers, scam pattern matching, and report generator |
| `legit/checkers/` | Official checkers (FTC/CAFC patterns, Census/BLS benchmarks, college data, registry, web search) |
| `legit/stats/` | Point-in-time statistics engine for historical claim verification |
| `tests/` | Comprehensive test suite (unit tests, API integration tests, and live HTTP test suite) |
| `run_server.py` | One-click launcher for the API server |
| `docs/DATA_ACCESS.md` | Connection details and schema notes |
| `scripts/` | Helper exploration scripts |

---

## Frontend JSON API

The API runs on FastAPI with CORS enabled for all origins (`*`), making it effortless to integrate with **Next.js, Vite, React, Vue, or React Native**.

### Server Status
- **Default Address:** `http://127.0.0.1:8000`
- **Interactive Swagger Docs:** `http://127.0.0.1:8000/docs`
- **Alternative ReDoc UI:** `http://127.0.0.1:8000/redoc`

### API Endpoints Reference

| Method | Endpoint | Description |
|---|---|---|
| `POST` | `/api/verify` | **Primary verification endpoint.** Receives text, returns overall risk, counts, action checklist, and grouped findings. |
| `GET` | `/api/scans/{scan_id}` | **Permalink lookup.** Fetches a previously verified scan by ID (ideal for `app.com/r/{id}`). |
| `GET` | `/api/history` | **Dashboard feed.** Returns recent scans with status badges, context, and timestamps. |
| `GET` | `/api/examples` | **1-Click demo payloads.** Returns 5 realistic student cases (rental scam, job scam, fake check, legit sublet, stats). |
| `GET` | `/api/health` | **Health check.** Confirms server status and Groq LLM availability. |

---

## Frontend JSON Contract

### Request: `POST /api/verify`
```json
{
  "text": "Cozy 2BR near campus, $650/month. I'm abroad, send the deposit by Zelle and I'll mail the keys.",
  "seen_on": "2026-09-13"
}
```
> **Tip:** Web search is on by default (`"offline": false`), which takes about 10–30 seconds. Send `"offline": true` for a 2–5 second check using only official data and scam patterns. See [docs/FRONTEND_GUIDE.md](docs/FRONTEND_GUIDE.md) for the full contract.

### Response (Tailored for Frontend UI)
```json
{
  "id": "chk_24f3eb208a",
  "created_at": "2026-09-13T16:40:49.123Z",
  "overall": "HIGH RISK",
  "overall_badge": {
    "label": "HIGH RISK",
    "color": "red",
    "message": "High risk detected. Do not send money, deposits, or sensitive personal information."
  },
  "counts": {
    "red_flag": 2,
    "caution": 1,
    "ok": 0,
    "info": 0,
    "unverified": 0,
    "total": 3
  },
  "summary": "A rental listing for a 2-bedroom apartment near campus that requests a deposit via Zelle.",
  "context": "housing",
  "location": {
    "city": null,
    "region": null,
    "country": null,
    "label": ""
  },
  "action_checklist": [
    "Never send a deposit, holding fee, or rent by Zelle, e-transfer, wire, or gift cards.",
    "Demand an in-person walkthrough or live interactive video call. If they refuse, walk away.",
    "Ask for their full legal name and check the property address on municipal rental licensing records.",
    "Reverse-image search all listing photos to see if they are copied from legitimate real estate sites.",
    "Remember: in Ontario and many jurisdictions, damage deposits are illegal—only first/last month is permitted."
  ],
  "findings": [
    {
      "id": 1,
      "kind": "pattern",
      "status": "red_flag",
      "status_label": "RED FLAG",
      "color": "red",
      "title": "Hard-to-reverse payment method",
      "quote": "send the deposit by Zelle",
      "summary": "Zelle is a hard-to-reverse payment method commonly used in rental scams to steal deposits...",
      "checker": "patterns",
      "evidence": [
        {
          "source": "FTC: Rental listing scams",
          "detail": "Official consumer-protection guidance describing this warning sign",
          "kind": "guidance",
          "kind_label": "official guidance",
          "url": "https://consumer.ftc.gov/articles/rental-listing-scams"
        }
      ],
      "data": {
        "pattern": "unusual_payment_method"
      }
    }
  ],
  "grouped_findings": {
    "red_flags": [ /* array of red flag findings */ ],
    "cautions": [ /* array of caution findings */ ],
    "ok": [ /* array of verified findings */ ],
    "context": [ /* informative context items */ ],
    "unverified": [ /* unconfirmed claims */ ]
  },
  "notes": []
}
```

---

## Quick Start

### 1. Installation
```bash
pip install -r requirements.txt
```

### 2. Configure Environment
Create a `.env` file in the repo root:
```text
GROQ_API_KEY=your_groq_api_key_here
```
*(Without a key, built-in keyword rules still catch common rental scams and money requests.)*

### 3. Launch the Web App and API
```bash
python run_server.py
```
Open `http://127.0.0.1:8000` for the web app: paste text and see the verdict, charts, school comparisons, official numbers, student reports, and sources. The API docs are at `http://127.0.0.1:8000/docs`.

### 4. CLI Usage (Optional)
You can also run checks directly from the command line:
```bash
python -m legit "Cozy 2BR near campus, $650/month, send deposit by Zelle."
```
Or run interactive terminal demo mode:
```bash
python -m legit
```

---

## Testing & Verification

The codebase includes full automated test coverage:

- **Unit Tests (76 tests):**
  ```bash
  python -m unittest discover -s tests
  ```
- **API Endpoint Tests:**
  ```bash
  python tests/test_api.py
  ```
- **Live HTTP Server Integration Tests:**
  ```bash
  python tests/live_test.py
  ```

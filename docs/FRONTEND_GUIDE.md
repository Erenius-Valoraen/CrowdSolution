# Frontend and browser extension guide

For the agent or developer building the web app, the browser extension, and anything else that shows CrowdSolution results. Everything here was checked against the running backend on 2026-09-13.

**Read this first, then open the real responses in [`docs/examples/`](examples/).** They are complete, unedited API output.

---

## 1. What the product does

A university student living on their own for the first time pastes something they aren't sure about: a rental listing, a job offer, a message from a "bank", a Reddit post about colleges, or a YouTube transcript. The backend pulls out every checkable claim, checks each one against official data, searches the web for the rest, and returns a clear verdict with sources.

Design rules the UI should keep:

- **No trust score.** Show the verdict (`HIGH RISK`, `BE CAREFUL`, `NO RED FLAGS FOUND`, `COULDN'T VERIFY`, `NOTHING TO CHECK`) and the evidence. Never invent a percentage.
- **Every claim shows its source.** Official data, official guidance, and web results must look visibly different (see `evidence[].kind`).
- **Plain language for students.** No parser names, model names, checker names, or developer notes in the UI.
- **Always show the disclaimer:** "A screening tool, not legal or financial advice. Open the sources before you act."

---

## 2. Architecture

```text
Web app / browser extension
        |  HTTP JSON (CORS open)
        v
api/            FastAPI server (python run_server.py, port 8000)
        |
        v
legit/          the checking engine
  extract.py        reads the text  -> Snowflake Cortex (claude-haiku-4-5), Groq as backup
  router.py         sends each claim to the right checker
  checkers/         official data checks -> Snowflake (public data, College Scorecard, cached benchmarks)
  checkers/web.py   web search for anything official data can't settle -> Groq browser search
  community.py      shared scam memory across students: match earlier reports, save new ones -> Backboard.io
  youtube.py        transcript fetching and timestamps (not exposed over HTTP yet, see section 8)
```

The frontend only talks to the API. **Never put any key in the frontend or the extension.** All keys stay in the backend's `.env` and `~/.snowflake/connections.toml`.

---

## 3. Running the backend

```bash
pip install -r requirements.txt
python run_server.py
```

Then open `http://127.0.0.1:8000/docs` for interactive Swagger docs.

Backend prerequisites, already set up on Abhi's machine:

| Need | Where | Notes |
|---|---|---|
| Snowflake data connection | `~/.snowflake/connections.toml`, section `[crowdsolution]` | See `docs/DATA_ACCESS.md` and `scripts/configure_snowflake.py` |
| Benchmark tables | Run `sql/setup/04_benchmarks.sql` and `sql/setup/05_college_scorecard.sql` once | Needs the College Scorecard Marketplace listing |
| Groq key | `.env`: `GROQ_API_KEY=` | Web search and backup extraction |
| Snowflake Cortex | `.env`: `PIVOT_AI=` (access token) and `CORTEX_ACCOUNT=BXUDSLD-KS59503` | Primary extraction. Check with `python scripts/check_cortex.py` |
| Backboard.io | `.env`: `BACKBOARD_API=` | Shared scam memory. The assistant `crowdsolution-community-memory` is found or created automatically. `COMMUNITY_MEMORY=off` disables it, for example in tests. |

`GET /api/health` reports `groq_api_configured`, `snowflake_cortex_configured`, and `community_memory_configured`.

---

## 4. Endpoints

| Method | Path | Use |
|---|---|---|
| `POST` | `/api/verify` | Check text. The main endpoint. |
| `GET` | `/api/scans/{id}` | Fetch a saved result, for share links like `/r/{id}` |
| `GET` | `/api/history?limit=20&offset=0` | Recent checks, newest first |
| `GET` | `/api/examples` | Five demo texts for one-click buttons |
| `GET` | `/api/health` | Status and which AI providers are configured |

### `POST /api/verify`

Request:

```json
{
  "text": "Cozy 2BR near UT Austin, only $650/month. I'm abroad, send the deposit by Zelle.",
  "seen_on": "2026-09-13",
  "offline": false
}
```

| Field | Default | Meaning |
|---|---|---|
| `text` | required | Anything: a listing, message, post, article, or a whole transcript. Long text is split and checked in parts automatically. |
| `seen_on` | today | Date the student saw it. Statistics are judged against what was published on that date. Usually leave it out. |
| `offline` | `false` | **Web search is on by default.** `true` skips web search for a faster check. Don't expose this to students; it's for testing. |

Errors: `400` for empty text, `422` for a malformed body, `500` with `detail` if the engine fails.

---

## 5. Response contract

Real examples: [`verify_rental_scam.json`](examples/verify_rental_scam.json), [`verify_college_claims.json`](examples/verify_college_claims.json), and [`verify_waterloo_sublet_web.json`](examples/verify_waterloo_sublet_web.json) (includes web search results).

### Top level

| Field | Type | Use in the UI |
|---|---|---|
| `id` | string, e.g. `chk_24f3eb208a` | Share links |
| `created_at` | ISO timestamp (UTC) | History list |
| `overall` | one of the five verdicts | Big headline |
| `overall_badge` | `{label, color, message}` | Headline color and one-sentence explanation |
| `counts` | `{red_flag, caution, ok, info, unverified, total}` | Count chips under the headline |
| `summary` | string | One line describing what the text is |
| `context` | `housing`, `job`, `finance`, `school`, `health`, `everyday`, or `other` | Icon or theme |
| `location` | `{city, region, country, label}` | Optional small text |
| `action_checklist` | list of strings | "What to do next" checklist |
| `findings` | list, sorted worst first | Main content |
| `grouped_findings` | same findings split by status | Convenience for status tabs |
| `notes` | list of strings | **Developer-facing. Don't show raw.** Use them to detect rate limits (section 7). |
| `raw_report` | `{parser, said_on, items_count}` | Debug only |

### Finding

```json
{
  "id": 3,
  "kind": "price",
  "status": "red_flag",
  "status_label": "RED FLAG",
  "color": "red",
  "title": "Rent compared with local median",
  "quote": "$650/month",
  "summary": "$650/month is 34% of the 2024 median for 2-bedroom rentals in Austin ($1,899). Rent far below the local norm is one of the most common signs of a rental scam.",
  "checker": "benchmark",
  "evidence": [
    {"source": "US Census Bureau, American Community Survey 1-year median gross rent (via Snowflake Public Data)",
     "detail": "Austin, 2-bedroom rentals, 2024: $1,899/month", "kind": "official", "kind_label": "official data", "url": null}
  ],
  "data": {"type": "rent", "amount": 650.0, "benchmark": 1899.0, "ratio": 0.342, "unit": "usd_month",
           "benchmark_label": "Typical 2-bedroom rentals in Austin (2024)", "place": "Austin", "size": "2-bedroom rentals", "year": 2024}
}
```

| Field | Notes |
|---|---|
| `id` | The claim's number. **Several findings can share an `id`**, e.g. a bank gets a registry finding and a complaints finding. Group by `id` for organization cards. |
| `kind` | What the claim is: `entity`, `price`, `statistic`, `pattern`, `school`, `claim` |
| `status` | `red_flag`, `caution`, `ok`, `info`, `unverified` |
| `status_label` / `color` | Backend labels: RED FLAG/red, CAUTION/yellow, OK/green, INFO/blue, UNVERIFIED/gray. The terminal UI renames them CHECKS OUT, CONTEXT, UNCONFIRMED, which read better for students. |
| `quote` | Exact words from the text. Can be empty. |
| `checker` | Which checker produced it. **Pick the layout from `checker` plus `data.type`.** |
| `evidence[].kind` | `official` (government data), `guidance` (FTC or Canadian Anti-Fraud Centre advice), `web` (web search), `community` (earlier student reports). Style these differently. |
| `evidence[].url` | Clickable when present. |
| `data` | Structured numbers for charts and tables. Shapes in section 6. Can be `{}`. |

---

## 6. `data` shapes and how to render each

The terminal UI in [`legit/demo.py`](../legit/demo.py) is the reference design. Run `python -m legit` and paste text to see it. Suggested page order, matching it:

1. Headline (`overall_badge`, `counts`, `summary`)
2. Reported by other students
3. Warning signs
4. Who's behind it
5. Is the price normal?
6. Schools and majors
7. Official numbers
8. Other claims (web)
9. Couldn't confirm
10. Action checklist and disclaimer

### Reported by other students: `checker: "community"`, `data.type: "community"`

Shared scam memory stored in Backboard.io. Every check with red flags is saved, and later checks match against it.

```json
{"type": "community", "match": "exact",
 "matched": [{"kind": "email", "value": "greenview.rentals@gmail.com"}],
 "reports": 2, "first_seen": "2026-09-13", "last_seen": "2026-09-13", "context": "housing",
 "red_flags": ["Rent compared with local median", "Pay before you can verify", "Hard-to-reverse payment method"],
 "summary": "A rental listing for a 2-bedroom apartment near UT Austin with an unusually low price and pressure to pay a deposit via Zelle without viewing.",
 "distance": null}
```

| `match` | Status | Meaning |
|---|---|---|
| `exact` | `red_flag` | An email, suspicious domain, or phone number in this text was in an earlier scam report. `matched` lists them. |
| `same_message` | `red_flag` | An almost identical message was reported before (semantic `distance` ≤ 0.25). |
| `similar` | `caution` | A closely similar scam was reported before (`distance` ≤ 0.45). Lower distance means more similar. |

`reports` counts how many times students hit that scam. `summary` and `red_flags` describe the earlier report, not the current text. The finding's `quote` is the matched values for `exact`, or the earlier summary otherwise. Evidence uses `kind: "community"` ("student reports").

**Render:** put this right under the headline when present; it's the most persuasive signal. Show the matched values, "Reported N times, last on DATE", the earlier summary, and the earlier red flags. Label it as student reports, distinct from official data and web results.

### Warning signs: `checker: "patterns"`, `data.type: "pattern"`

```json
{"type": "pattern", "pattern": "upfront_payment",
 "explanation": "Asking for a deposit or fee before you've seen the place, signed a lease, or started a job is how most rental and job scams take money.",
 "why": "Asking for money upfront before the apartment can be verified or viewed."}
```

`pattern` values: `upfront_payment`, `unusual_payment_method`, `overpayment_check`, `pay_for_job`, `guaranteed_returns`, `cannot_view_in_person`, `urgency`, `asks_personal_info`, `too_good_to_be_true`, `impersonation`, `unsolicited_offer`.

**Render:** a table or card list with the badge, `title`, the `quote`, `explanation`, and the guidance link from `evidence[0]`.

### Who's behind it: `checker: "registry"` and `"reputation"`

Group findings with the same `id` into one card per organization. The name is the `title` text before the colon.

`data.type: "bank"`:

```json
{"type": "bank", "registered_name": "JPMorgan Chase Bank, National Association", "entity_type": "National Bank",
 "active": true, "fdic_cert": "628", "location": "Columbus, OH",
 "claimed_domain": "chase-student-rewards.com", "official_domains": ["jpmorganchase.com", "jpmorganchina.com.cn"],
 "domain_result": "lookalike"}
```

`data.type: "company"`:

```json
{"type": "company", "registered_name": null, "official_domains": [], "claimed_domain": "gmail.com", "domain_result": "free_email"}
```

Also `"adviser"` (`registered_name`, `status`, `registration_type`) and `"charity"` (`registered_name`, `ein`, `tax_year`).

`domain_result` wording:

| Value | Color | Say |
|---|---|---|
| `official` | green | is one of its official domains |
| `free_email` | red | is a free personal email, not the organization's own domain |
| `lookalike` | red | imitates the name but is not an official domain |
| `lookalike_unknown` | yellow | contains the name, but we can't confirm who owns it |
| `brand_match` | yellow | matches the name but isn't in our records, probably official |
| `unrelated` | yellow | has no visible connection to this organization |
| `owned_by_other` | yellow | belongs to a different company (`domain_owner`) |
| `null` | | no domain in the message |

In `official_domains`, show plain domains first (one dot) and hide foreign subsidiaries like `jpmorganchina.com.cn`.

`checker: "reputation"`, `data.type: "complaints"`:

```json
{"type": "complaints", "company": "JPMORGAN CHASE & CO.", "complaints": 26502, "timely_pct": 100,
 "top_issue": "Managing an account", "top_product": "Checking or savings account", "period_end": "2026-06-14"}
```

**Render:** one card per organization with rows for registered as, official websites, "this message uses" (colored), and complaints (timely % red below 90). Add web results for the same `id` if present. The card's badge is the worst status in the group.

### Is the price normal: `checker: "benchmark"`

`data.type` is `rent`, `wage`, `savings_rate`, `loan_rate`, or `credit_card_rate`. They share one shape:

```json
{"type": "wage", "amount": 55.0, "benchmark": 37.49, "ratio": 1.47, "unit": "usd_hour",
 "benchmark_label": "Average pay, all private jobs in the US (May 2026)", "place": "the US", "month": "May 2026", "entry_level": true}
```

`unit`: `usd_month` ($1,899/mo), `usd_hour` ($37.49/hr), or `percent` (3.63%).

**Render:** a two-bar comparison with the offer in the status color and the benchmark in gray, then `summary`.

`data.type: "rent_trend"` (Canada, no rent levels available):

```json
{"type": "rent_trend", "province": "Ontario", "change_pct": 2.4, "month": "May 2026", "amount": 700.0}
```

**Render:** a short line like "Rents in Ontario: +2.4% vs a year earlier". The actual price is checked by web search as a separate finding.

### Schools and majors: `checker: "college"`, `data.type: "college"`

```json
{
  "type": "college",
  "schools": [
    {"name": "University of California-Los Angeles", "city": "Los Angeles", "state": "CA", "control": "public", "country": "US",
     "admission_rate": 0.0873, "tuition_in_state": 13747.0, "tuition_out_of_state": 44524.0, "net_price": 14013.0,
     "graduation_rate": 0.9266, "earnings_10yr": 82511.0, "median_debt": 14000.0, "undergrads": 33040.0,
     "research_name": "University of California, Los Angeles", "research_works": 402368, "citations": 49170616, "h_index": 1605}
  ],
  "programs": [
    {"school": "The University of Texas at Austin", "program": "Computer and Information Sciences, General",
     "credential": "Bachelor's Degree", "graduates": 438, "earnings_1yr": 111587.0, "earnings_4yr": 112017.0,
     "earnings_5yr": 132436.0, "median_debt": 20500.0, "schools": null}
  ],
  "claim": {"text": "It's even cheaper for out-of-state students", "label": "Out-of-state tuition and fees", "unit": "usd",
            "metric": "tuition_out_of_state", "claimed": "lower than The University of Texas at Austin",
            "official": "$44,524 vs $42,778", "result": "caution"},
  "opinion": false
}
```

- Rates (`admission_rate`, `graduation_rate`) are fractions: `0.0873` means 9%.
- Any school field can be `null`. Canadian schools have only `name` and research fields, because College Scorecard is US only.
- `programs[].schools` is set for national medians, and then `school` reads like "Typical across 505 US schools".
- `claim` is `null` when there's nothing numeric to judge. `opinion: true` means "X is better than Y", which should be shown as context, not a verdict.

**Render:**
1. A side-by-side table: merge `schools` from all college findings by `name`, one column per school. Skip rows where every value is null. Highlight rows whose `metric` was claimed.
2. A "what graduates earn" table from `programs`.
3. A claims table: badge, quote, `claim.label`, `claim.claimed`, `claim.official`. For opinions, say "This is an opinion" and point to the table.

### Official numbers: `checker: "statistic"`, `data.type: "statistic"`

```json
{"type": "statistic", "label": "Total nonfarm jobs", "where": "United States", "agency": "Bureau of Labor Statistics",
 "verdict": "ACCURATE WHEN SAID", "claimed": "added 172,000 jobs last month",
 "figures": {
   "when_said": {"value": "+172,000 jobs", "period": "May 2026", "published": "2026-06-05"},
   "revised":   {"value": "+63,000 jobs",  "period": "May 2026", "published": "2026-08-07"},
   "latest":    {"value": "+63,000 jobs",  "period": "May 2026", "published": "2026-08-07"}}}
```

`figures` can instead contain `today` when there's no record from the date it was said. `verdict` values: `ACCURATE WHEN SAID`, `OUTDATED WHEN SAID`, `WRONG WHEN SAID`, `NOT YET PUBLISHED WHEN SAID`, `MATCHES TODAY'S DATA`, `DOESN'T MATCH TODAY'S DATA`.

**Render:** a row per claim with columns for when it was said, revised since (highlight if different), and latest. This "true when said, revised later" view is a strong demo moment.

### Web results: `checker: "web"`, `data.type: "web"`

```json
{"type": "web", "verdict": "contradicted",
 "question": "Is 700.0 (per month) a normal rent for Waterloo, Ontario, CA? Give the typical range.",
 "sources": [{"title": "Web source cited by the search", "url": "https://www.zumper.com/rent-research/waterloo-on"}]}
```

`verdict`: `supported` becomes status `ok`, `contradicted` becomes `red_flag` for organizations or `caution` otherwise, and `unclear` becomes `unverified`.

**Render:** show web findings for an organization inside its card, for a price inside the price section, and for a school inside the claims table. Show the rest in an "Other claims" list with source links. Label them clearly as web results.

### Couldn't confirm: `checker: "router"`, `data: {}`

Nothing confirmed these. **Render** a simple list of quotes under "Couldn't confirm, check these yourself".

---

## 7. Speed, limits, and failure states

| Situation | Typical time | What happens |
|---|---|---|
| Web search off | 2 to 8 seconds | Official data and patterns only |
| Web search on (default) | 6 to 60 seconds | One batched web search for up to 6 unresolved claims |
| Long text or transcript | adds about 4 seconds per 3,000 characters | Split into parts automatically |

- **Use a request timeout of at least 120 seconds.** Show a loading state with changing messages, like "Reading...", "Checking official data...", "Searching the web...".
- **Groq's free tier has a daily token cap, and one web search can use most of it.** When that happens the request still succeeds with official results. `notes` contains a message starting with `Web search hit Groq's rate limit`, and those claims show as `unverified`. Show a gentle line like "Web search is busy, so some claims couldn't be checked online."
- **If Cortex fails, extraction silently falls back to Groq.** If both fail, simple keyword rules still catch common scams and prices.
- **The first request after starting the server is slower** because it opens the Snowflake connection.

---

## 8. Browser extension notes

- **Manifest V3.** The extension calls the backend at `http://127.0.0.1:8000` for local demos. Add it to `host_permissions`. CORS already allows all origins.
- **No keys in the extension.** It only sends text to the backend.
- **Ways to get text:**
  - Selected text via a context-menu item "Is this legit?".
  - The main text of the page, for listings and posts.
  - YouTube: read the transcript and send it as `text`. Long transcripts are handled.
- **Timestamps for YouTube aren't exposed over HTTP yet.** `legit/youtube.py` already has `check_video(url, offline=..., max_sections=...)`, which returns `(info, report, timed_findings)` with a `seconds` value per finding. `to_json(info, report, timed)` serializes it. The natural next step is a `POST /api/verify/youtube` endpoint taking `{url}` that wraps those two functions, so the extension can put badges at timestamps in the video player.
- **Keep the popup light.** Show the verdict, counts, and the top 3 findings, with a link to the full report page at `/r/{id}` using `GET /api/scans/{id}`.

---

## 9. Known gaps

- **Canada is thin.** There are no official rent levels, registries, or school earnings for Canada, so these rely on web search. Ontario rent trends and university research stats do work.
- **Official data runs through mid-June 2026.** College Scorecard earnings reflect recent graduating cohorts.
- **Wording varies between runs.** The AI extraction can phrase titles and summaries differently each time. Build the UI on `checker`, `status`, and `data`, never on exact title text.
- **History is a local SQLite file** (`api/history.db`, gitignored) with no user accounts.
- **The checklist is rule-based by context.** It includes an Ontario deposit tip even for US housing listings.

---

## 10. Where things are

| Path | What |
|---|---|
| `api/main.py` | Routes |
| `api/models.py` | Pydantic request and response models |
| `api/service.py` | Turns engine reports into the JSON above, plus the checklist |
| `legit/demo.py` | Reference terminal UI; mirror its sections |
| `legit/router.py` | Which checker runs for which claim, web fallback, long text |
| `legit/checkers/*.py` | Each checker and the exact `data` it returns |
| `legit/youtube.py` | Transcript and timestamp logic |
| `docs/examples/*.json` | Real full responses |
| `tests/test_api.py` | API tests: `python tests/test_api.py` |

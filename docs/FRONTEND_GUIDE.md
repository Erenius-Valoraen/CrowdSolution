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
| `POST` | `/api/transcribe` | Voice typing: audio in, text out (see below) |
| `POST` | `/api/scans/{id}/spoken-summary` | A short summary of the results to read aloud (see below) |
| `POST` | `/api/speak` | Text to speech: `{"text"}` in, WAV audio out, or `503` to use the browser's voice |
| `GET` | `/api/scans/{id}` | Fetch a saved result, for share links like `/r/{id}` |
| `GET` | `/api/history?limit=20&offset=0` | Recent checks, newest first |
| `GET` | `/api/examples` | Demo texts for one-click buttons: `{id, title, category, text}`, where `category` is `housing`, `job`, `school`, `finance`, or `video` |
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
| `text` | required | Anything: a listing, message, post, article, or a whole transcript. Long text is split and checked in parts automatically. **A YouTube link on its own** (`youtube.com/watch?v=`, `youtu.be/`, `shorts/`, `live/`, `embed/`) fetches that video's captions and checks them instead; see "YouTube videos" below. |
| `seen_on` | today | Date the student saw it. Statistics are judged against what was published on that date. Usually leave it out. |
| `offline` | `false` | **Web search is on by default.** `true` skips web search for a faster check. Don't expose this to students; it's for testing. |

Errors: `400` for empty text, `422` for a malformed body or a YouTube video we can't read (captions off, private, YouTube blocking the server; `detail` is a student-friendly sentence you can show as is), `500` with `detail` if the engine fails.

#### YouTube videos

When `text` is only a YouTube link, the API reads the video's English captions (creator captions preferred over auto-generated), checks the first 6 transcript sections (about 20 minutes of speech), and judges statistics against what was published on the **upload date**. It takes longer than text: allow up to about two minutes with web search on. The response has the usual fields plus:

- `video`: `{id, url, title, channel, upload_date, language, auto_captions, thumbnail, duration, duration_label, sections_total, sections_checked, checked_until, checked_until_label, fully_checked, transcript}`. `transcript` is a list of `{seconds, timestamp, text, checked}` lines of about 220 characters; `checked: false` lines are past the part we checked.
- Each finding's `seconds` and `timestamp` (e.g. `125.4`, `"2:05"`): where it was said. Link to `{video.url}?t={floor(seconds)}`. Both are `null` for text checks.

#### Voice typing: `POST /api/transcribe`

Record with `MediaRecorder` and send the recording as the **raw request body** with its MIME type as `Content-Type` (`audio/webm;codecs=opus` from Chrome and Firefox, `audio/mp4` from Safari; ogg, mp3, wav, and flac also work). The server transcribes it with Groq Whisper (`whisper-large-v3-turbo`, falling back to `whisper-large-v3`) and returns `{"text": "...", "model": "..."}`. Put the text in the textbox; don't auto-submit, so the student can fix mistakes. Nothing is checked or stored.

Errors, each with a `detail` you can show as is: `415` unsupported type, `400` empty recording, `413` over 15 MB, `503` no Groq key on the server, `429` speech-to-text rate limited, `422` no words heard, `502` Groq failed. `GET /api/health` has `voice_input: true` when it's available; hide the mic otherwise. Microphone access needs `https` or `localhost`.

#### Spoken results: `POST /api/scans/{id}/spoken-summary` and `POST /api/speak`

When a student asks by voice, answer out loud too. After the results render, call `spoken-summary` for the scan: it returns `{"text", "source"}`, a 70 to 130 word summary written for listening (verdict, the key warnings with real numbers, what to do next). `source` is `ai` (Cortex, saved with the scan so replays match) or `template` (built from the results when no model is available). Show the text as captions while it plays.

For audio, send one sentence at a time to `/api/speak` as `{"text": "..."}` (max 1,500 characters) and play the WAV it returns. It uses Groq text-to-speech (`canopylabs/orpheus-v1-english`, voice set by `GROQ_TTS_VOICE`). If it returns `503`, the model isn't enabled for the server's Groq account (its terms must be accepted once in the Groq console), so use the browser's `speechSynthesis` instead. Browsers only play sound after the student has interacted with the page; if playback is refused, show a "Tap to listen" button.

The web app shows a video header with a coverage bar, a clickable timeline of markers colored by status, `▶ 2:05` links on every card, and the transcript with checked lines highlighted.

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
| `video` | object or `null` | YouTube checks only. See "YouTube videos" in section 4. |

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
| `seconds` / `timestamp` | YouTube checks only: where in the video it was said. `null` otherwise. |

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
{"type": "web", "verdict": "supported",
 "question": "Canada lost 84,000 jobs in February 2026", "query": "Canada lost 84,000 jobs in February 2026",
 "claimed": "84,000 jobs lost", "found": "84,000 jobs lost in February 2026",
 "claimed_value": 84000, "found_value": 84000, "unit": "jobs", "as_of": "February 2026",
 "sources": [{"title": "Labour Force Survey, February 2026", "url": "https://www150.statcan.gc.ca/...", "site": "statcan.gc.ca", "date": "2026-03-13"}]}
```

How it works: each open claim gets its own DuckDuckGo search (in parallel), the top page is skimmed for sentences with numbers, and Cortex reads the results in batches of 5. Sources are always real search results, never URLs the model made up. If the search engine refuses requests, one Groq browser-search call covers up to 6 claims instead.

`verdict` to `status`: `supported` is `ok`; `contradicted` is `red_flag` for organizations and `caution` otherwise; `misleading` is `caution`; `context` is `info` (sources don't settle it but give the real figure in `found`); `unclear` is `unverified`.

`claimed_value` and `found_value` are both numbers in the same `unit`, or both `null`. `claimed`, `found`, and `as_of` are short display strings and can be `null`.

**Render:** show web findings for an organization inside its card, for a price inside the price section, and for a school inside the claims table. Show the rest under "Checked online" with claimed vs found figures (bars when both values are numbers) and the source sites as links. Web findings that are `unverified` with no `found` go under "Couldn't confirm".

### Couldn't confirm: `checker: "router"`, `data: {}`

Nothing confirmed these. **Render** a simple list of quotes under "Couldn't confirm, check these yourself".

---

## 7. Speed, limits, and failure states

| Situation | Typical time | What happens |
|---|---|---|
| Web search off | 2 to 8 seconds | Official data and patterns only |
| Web search on (default) | 6 to 40 seconds | A search per unresolved claim (up to 30), read by Cortex in batches of 5 |
| Long text or transcript | adds about 4 seconds per 3,000 characters | Split into parts automatically |

- **Use a request timeout of at least 120 seconds.** Show a loading state with changing messages, like "Reading...", "Checking official data...", "Searching the web...".
- **Web search is free and doesn't use Groq** unless the search engine refuses requests. Then the Groq browser-search backup runs, and Groq's free tier has a daily token cap one search can use most of. If that also fails, the request still succeeds with official results, `notes` contains a message starting with `Web search hit Groq's rate limit`, and those claims show as `unverified`. Show a gentle line like "Web search is busy, so some claims couldn't be checked online."
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

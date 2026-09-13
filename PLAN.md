# UPSTREAM — Build Plan v2 (post-pivot)

> **Problem 6 — Information Trust**
> **User — a university student living independently for the first time.**
>
> We do not score truth. We trace where it came from, who wants your money,
> and tell you what to do before you pay.

**PIVOT 02 absorbed.** Kernel untouched. Two contract lines changed.
Everything else was a leaf. This file replaces PLAN.md v1 entirely.

---

## 0. THE USER — read this before you read anything else

Her name is Maya. She is 19. Six weeks ago she lived with her parents.

- She has **$4,100** in her account. It is all the money she has.
- She has **never signed a lease**, never filed taxes, never had a landlord.
- She has **20 minutes** between lectures, and she is on her phone.
- She moved to a city she has never lived in. She does not know what rent
  *should* cost here, what a normal lease *should* say, or what a real job
  offer *should* look like.
- Her parents cannot help. They have never rented here either.

This week she will be asked to:
- e-transfer **$2,400** for a sublet she has only seen photos of
- pay a **$200 "training deposit"** for a campus ambassador job from an Instagram DM
- sign a lease clause she does not understand
- give her **SIN** to someone who says they need it for payroll
- pay someone who says they can "fix" her study-permit paperwork

**Every one of these decisions is irreversible and costs money she cannot
replace.** She will make all of them alone, on her phone, in under ten minutes,
with no idea what normal looks like.

### What that forces on the product

| Her constraint | What it forces |
|---|---|
| Limited budget | Being wrong costs $2,400 she doesn't have. **The verdict must be blunt.** No hedging, no "here are some considerations." |
| Limited experience | She doesn't know what's normal. **We supply the baseline**, not just the analysis. "38% below local median" means something. "Suspicious" doesn't. |
| Busy schedule | **5 seconds to the answer.** On a phone. Between classes. Depth is opt-in, never up front. |
| Unfamiliar environment | "Is $1,400 normal for a 1-bed here?" is a **data question**. That's our warehouse. |
| Practical decisions | **A verdict without an action is useless to her.** She doesn't want analysis. She wants to know whether to send the e-transfer. |

### The sentence that governs every decision today

> **If Maya can't act on it in 5 seconds on her phone, it doesn't ship.**

Tape it to the table. When someone proposes a feature, read it out loud.

### We are her

Three university students, building for a university student, in a university
town, demoing to university people. We do not need to imagine this user. We have
been sent this listing, or we know the person who lost the money. **Use that.**
Every design argument today is settled by: *"what would you have wanted in
first year?"*

---

## 1. THE PRODUCT

### One sentence
Screenshot the listing, the job offer, the DM, or the lease clause.
Get back: **should I pay, and what do I check first.**

### The five verdicts

| Verdict | Colour | Means |
|---|---|---|
| `DO_NOT_PAY` | red | Matches a known scam structure, or duplicated across addresses/prices |
| `UNVERIFIABLE_ENTITY` | amber | This landlord / employer / company exists on no public record |
| `RISKY_BUT_NORMAL` | amber | Common arrangement. Here's what to check before committing. |
| `VERIFIED` | green | Entity confirmed, terms within local norms |
| `INSUFFICIENT_DATA` | grey | We couldn't establish enough. **A valid, shippable answer.** |

**Never a numeric score.** Never "trust: 62%". She cannot act on a number.

### The four questions we answer

| Signal | What Maya is really asking |
|---|---|
| **Entity** | Does this person / company / address actually exist? |
| **Duplicates** | Is this same listing posted at other addresses or prices? |
| **Money** | Who's asking for money, how much, and *when* in the process? |
| **Baseline** | Is this price / term normal for **here**? |

Plus the output that matters most to a first-timer:

**Checklist** — the 5 things to check before paying. The questions a scammer
can't answer.

### Scope discipline — what we are NOT building

This pivot narrows us. **Narrowing is the point. Do not re-widen.**

- ❌ News fact-checking, health claims, product reviews — gone with v1
- ❌ Citation-chain walking on articles — Maya's artifacts cite nothing
- ❌ General-purpose "check anything" — one user, five situations
- ❌ Accounts, auth, history, notifications, payments
- ❌ Anything requiring more than 5 seconds of reading to act on

**Five situations only:** sublet/rental · job or internship offer · lease clause ·
money request (deposit/fee/e-transfer) · document or ID request.

If a feature doesn't serve one of those five, it doesn't ship today.

---

## 2. WHAT SURVIVED THE PIVOT

Proof the architecture was right. Say this in the pitch.

| Layer | Status |
|---|---|
| `kernel/` — Signal, Claim, Receipt, sign, append-only | **Zero changes** |
| `independence.py` (MinHash + embeddings) | **Survives and improved** — duplicate-listing detection is the same query as syndication detection |
| `incentive.py` | **Survives, now central** — "who wants your money" is the whole question |
| `adapters/image.py` | **Survives, now primary** — students screenshot everything |
| SSE streaming · lens system · receipt permalink · DEMO_MODE | **Zero changes** |
| `provenance.py` | **Repurposed** → `entity_check.py` |
| GDELT seed corpus | **DEAD.** ~1h sunk. Binned without argument. |
| `policy.yaml` | New profile, same file format. Zero Python changes. |

**The gift:** R1's work transfers 1:1. The classic rental scam signature is one
listing at three addresses with three prices — MinHash catches that natively, and
duplicate listings separate *more cleanly* than syndicated articles did.

**Second gift:** OpenCorporates went from nice-to-have to load-bearing.
"Is this employer actually registered?" is now a primary signal.

---

## 3. LANES

| | Person | OWNS | NEVER TOUCHES |
|---|---|---|---|
| **A** | | `kernel/`, `analyzers/`, `adapters/`, `policy*.yaml`, `CLAUDE.md`, `README.md` | `apps/web/`, `snowflake/` |
| **B** | | `services/api/snowflake/`, `snowflake/`, `scripts/`, `evals/`, `fixtures/`, AWS | `apps/web/`, `kernel/` |
| **C** | | `apps/web/` — everything | all Python |

**This pivot's cost lands mostly on B.** Say it out loud so nobody's surprised.
A and C are additive. B is rebuilding the corpus from scratch.

### Git
```
main                  # always deployable
├── kernel/<thing>    # A
├── data/<thing>      # B
└── web/<thing>       # C
```
`git pull --rebase origin main` before every push. Merge to main every 45 min.
Never hold a branch longer. Deploys come off `main` only.

---

## 4. ARCHITECTURE — unchanged trunk, new leaves

```
   ADAPTERS          KERNEL                    LENSES
 ┌──────────┐   ┌──────────────────────┐   ┌──────────────┐
 │ image ★  │   │ 1. normalize         │   │ ACTION ★     │
 │ listing ★│──▶│ 2. extract claims    │──▶│ why          │
 │ url      │   │ 3. fan out analyzers │   │ money        │
 │ text     │   │ 4. aggregate (YAML)  │   │ duplicates   │
 └──────────┘   │ 5. sign + persist    │   │ raw JSON     │
                └──────────────────────┘   └──────────────┘
                          │                  ★ = new / promoted
                  ┌───────▼────────┐
                  │   SNOWFLAKE    │  append-only, versioned
                  │  every stage   │  raw → claims → signals → receipts
                  └────────────────┘
```

**Law: changes may only touch `adapters/` and `analyzers/`.**
If a task seems to need a `kernel/` edit, it is the wrong task.

### Analyzer roster (post-pivot)

```
analyzers/
├── entity_check.py    NEW   company registered? address real? domain age?
│                            phone/email reused across listings?
├── pattern.py         NEW   semantic match vs the scam-pattern corpus
├── independence.py    KEPT  duplicate listing detection (was syndication)
├── incentive.py       GREW  payment timing: deposit-before-viewing, e-transfer,
│                            wire, gift card, urgency, "text me off-platform"
├── baseline.py        NEW   is this price / term normal for this postal area?
└── checklist.py       NEW   the 5 questions a scammer can't answer
```

`checklist.py` is **one `AI_COMPLETE` call and probably the highest
perceived-value thing in the build.** "Limited experience" means she doesn't know
*what to ask*. Five specific, concrete questions is help she can act on in the
next two minutes.

### Contract change — two lines, announced out loud

```python
Verdict = Literal["DO_NOT_PAY","UNVERIFIABLE_ENTITY",
                  "RISKY_BUT_NORMAL","VERIFIED","INSUFFICIENT_DATA"]
# Receipt gains:  action_checklist: list[str]
```

That is the entire kernel delta for this pivot.

---

## 5. THE FLOW — exactly what Maya does

### S1 · Home — camera first
Big **📷 Check a listing** button. Paste box underneath, smaller.
Share-sheet entry if the PWA is installed.
No nav. No login. No settings. One decision.

> She is looking at a Kijiji listing on her phone. She screenshots it.
> She does not copy URLs. **Nobody copies URLs on a phone.**

### S2 · Analyzing — 15 seconds of visible reasoning
Never a spinner. Signals land live over SSE:
```
✓ Read listing — $1,400/mo, 1 bed, Northdale
✓ Checked 1,847 local listings
⚠ Same photos posted at 2 other addresses in the last 6 weeks
⚠ "E-transfer deposit before viewing" — known scam structure
⚠ No landlord or company found on public record
✓ $1,400 is 9% above the local median for a 1-bed in N2L
```
**Not dead time — the product showing its work.** Most of her trust in the
answer comes from watching it happen.

### S3 · Receipt — the 5-second answer

```
┌──────────────────────────────────────┐
│  ⛔  DO NOT SEND MONEY                │  ← 40px. the whole answer.
│                                      │
│  These photos appear at 3 addresses  │
│  with 3 different prices.            │
├──────────────────────────────────────┤
│  BEFORE YOU DO ANYTHING              │  ← the primary content now
│  □ Ask to view the unit in person.   │
│    Refusal = walk away.              │
│  □ Ask for the unit number, check it │
│    on the city rental registry.      │
│  □ Never e-transfer before a signed  │
│    lease. There is no reversal.      │
│  □ Ask for their full legal name.    │
│  □ Reverse-image-search the photos.  │
├──────────────────────────────────────┤
│  4 students checked this listing     │  ← the flywheel
│  this week. 3 marked it suspicious.  │
├──────────────────────────────────────┤
│  ⟨Action⟩ Why  Money  Duplicates  Raw│  ← depth on demand
├──────────────────────────────────────┤
│  receipt a9f2c1 · sha256 4e8b…       │
│  [ Send to a friend ]  [ Re-check ]  │
└──────────────────────────────────────┘
```

### S4 · Evidence
Tap any signal → bottom sheet: exact quote, source, timestamp, source class.
**Every number is one tap from its evidence.** This is why she believes us.

### S5 · Share
`crowd.app/r/a9f2c1` — opens for anyone, no install.
OG card shows the verdict. She sends it to the group chat, her roommate, her mum.
**That is our entire distribution model and it costs nothing.**

### The three laws
1. **Never show a number without its evidence link.** Enforced in `contracts.py`.
2. **Never say true / false.** We classify provenance and risk, not truth.
3. **"We don't know" ships.** For a user who cannot afford to be wrong,
   honesty *is* the feature.

---

## 6. SNOWFLAKE — maximum surface, all of it load-bearing

Separate prize track. Sponsor judges want **platform depth**, not "we called an
LLM." Every feature below does real work. None is decoration.

| Feature | What it does for Maya | Cost |
|---|---|---|
| **Cortex Search** | Matches her listing against the scam-pattern corpus | 30m |
| **VECTOR + cosine** | Finds the same listing posted elsewhere | done |
| **Snowpark UDF (MinHash)** | Catches copy-paste duplicates | done |
| **AI_EXTRACT (multimodal)** | Reads her screenshot straight from S3 | 20m |
| **AI_CLASSIFY** | Listing type, payment-request type | 10m |
| **AI_FILTER in JOIN** | Semantic matching against scam corpus | 15m |
| **AI_AGG** | Summarises what other students said about this listing | 15m |
| **AI_COMPLETE** | Generates her action checklist | 15m |
| **Dynamic Tables** | Live local rent baselines, auto-refreshing | 20m |
| **Marketplace — OpenCorporates** | Is this employer a real registered company? | done |
| **Marketplace — IPinfo** | Are these "different" landlords on one host? | done |
| **External stage → S3** | Screenshot → Cortex, no download | 30m |
| **Time Travel** | "This listing's price changed twice this week" | 10m |
| **Streamlit in Snowflake** | Trust Lab console + backup demo surface | 45m |
| **Cortex Analyst** | Judge asks our warehouse a question in English | 45m |

**Time Travel is the elegant one.** Our thesis is "trust needs receipts."
Snowflake gives `AT(OFFSET => ...)` free — so listing-history diffing isn't a
feature we built, it's a platform capability we recognised.

### `snowflake/02_tables.sql` — post-pivot schema

```sql
USE ROLE upstream_dev; USE WAREHOUSE upstream_wh;
USE DATABASE upstream; CREATE SCHEMA IF NOT EXISTS core; USE SCHEMA core;

CREATE TABLE IF NOT EXISTS raw_artifacts (
  artifact_id STRING PRIMARY KEY, source_type STRING, url STRING,
  raw_content VARIANT, content_sha256 STRING,
  fetched_at TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP());

-- what she screenshotted, parsed
CREATE TABLE IF NOT EXISTS artifacts_parsed (
  artifact_id STRING PRIMARY KEY,
  kind STRING,          -- rental | job | lease_clause | money_request | id_request
  title STRING, body_text STRING,
  price NUMBER, bedrooms NUMBER, postal_prefix STRING, city STRING,
  contact_email STRING, contact_phone STRING, contact_handle STRING,
  entity_name STRING,   -- claimed landlord / employer
  payment_method STRING, payment_timing STRING,
  image_hashes ARRAY,
  minhash ARRAY, embedding VECTOR(FLOAT,1024));

-- our local corpus. powers duplicates AND baselines.
CREATE TABLE IF NOT EXISTS listings (
  listing_id STRING PRIMARY KEY, platform STRING, url STRING,
  title STRING, body_text STRING,
  price NUMBER, bedrooms NUMBER, postal_prefix STRING, city STRING,
  contact_email STRING, contact_phone STRING, posted_at TIMESTAMP_NTZ,
  minhash ARRAY, embedding VECTOR(FLOAT,1024));

-- known scam structures. the corpus that makes pattern.py work.
CREATE TABLE IF NOT EXISTS scam_patterns (
  pattern_id STRING PRIMARY KEY,
  scam_type STRING,     -- rental | job | immigration | deposit | phishing
  pattern_name STRING, description STRING, example_text STRING,
  red_flags ARRAY, source STRING,   -- CAFC | FTC | reddit | university advisory
  embedding VECTOR(FLOAT,1024));

CREATE TABLE IF NOT EXISTS entities (
  entity_key STRING PRIMARY KEY,    -- normalised name | domain | phone
  entity_type STRING, registered BOOLEAN, jurisdiction STRING,
  incorporated_on DATE, domain_age_days NUMBER, asn STRING,
  evidence VARIANT, first_seen TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP());

CREATE TABLE IF NOT EXISTS signals (
  signal_id STRING PRIMARY KEY, artifact_id STRING, analyzer STRING,
  analyzer_version STRING, subject_type STRING, subject_id STRING,
  direction STRING, weight FLOAT, confidence FLOAT,
  explanation STRING, evidence VARIANT,
  created_at TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP());

-- APPEND ONLY. never UPDATE, never DELETE.
CREATE TABLE IF NOT EXISTS receipts (
  receipt_id STRING PRIMARY KEY, artifact_id STRING, content_sha256 STRING,
  policy_version STRING, verdict STRING, headline STRING,
  action_checklist ARRAY, payload VARIANT, receipt_sha256 STRING,
  created_at TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP());
```

### The seven queries that carry the product

**1 · Read the screenshot — one function, no OCR pipeline of our own**
```sql
SELECT AI_EXTRACT(TO_FILE('@uploads_stage', ?), {
 'kind'    :'rental listing, job offer, lease clause, money request, or ID request?',
 'price'   :'Any monetary amount, as a number',
 'bedrooms':'Number of bedrooms if stated',
 'address' :'Any address, street, or neighbourhood mentioned',
 'entity'  :'The landlord, company, or person named',
 'contact' :'Any email, phone, or social handle',
 'payment' :'How and WHEN payment is requested — before or after viewing?',
 'urgency' :'Any time pressure or scarcity language, verbatim'});
```

**2 · Scam pattern match — the analyzer that lands the demo**
```sql
SELECT pattern_name, scam_type, red_flags, source,
       VECTOR_COSINE_SIMILARITY(
         AI_EMBED('snowflake-arctic-embed-l-v2.0', :artifact_text),
         embedding) AS sim
FROM scam_patterns
ORDER BY sim DESC LIMIT 5;
```

**3 · Duplicate listing — R1's work, transferred**
```sql
SELECT l.listing_id, l.url, l.price, l.postal_prefix, l.posted_at,
       upstream.core.minhash_jaccard(:artifact_minhash, l.minhash) AS jac,
       VECTOR_COSINE_SIMILARITY(:artifact_embedding, l.embedding)  AS sim
FROM listings l
WHERE upstream.core.minhash_jaccard(:artifact_minhash, l.minhash) > 0.55
   OR VECTOR_COSINE_SIMILARITY(:artifact_embedding, l.embedding) > :thresh
ORDER BY jac DESC;
-- 3 hits, 3 addresses, 3 prices  =>  DO_NOT_PAY
```

**4 · Local baseline — Dynamic Table over our own corpus**
```sql
CREATE OR REPLACE DYNAMIC TABLE local_baselines
  TARGET_LAG='5 minutes' WAREHOUSE=upstream_wh AS
SELECT postal_prefix, bedrooms,
       MEDIAN(price) AS med,
       PERCENTILE_CONT(0.1) WITHIN GROUP (ORDER BY price) AS p10,
       PERCENTILE_CONT(0.9) WITHIN GROUP (ORDER BY price) AS p90,
       COUNT(*) AS n
FROM listings WHERE price IS NOT NULL
GROUP BY 1,2 HAVING COUNT(*) >= 5;
```
*"38% below the local median for a 1-bed in N2L"* is a number no other team will
have, computed from local data we gathered ourselves.

**5 · Entity verification — Marketplace shares doing real work**
```sql
SELECT a.entity_name, oc.company_number, oc.incorporation_date,
       oc.current_status, ip.asn, ip.country
FROM artifacts_parsed a
LEFT JOIN opencorporates_share.companies oc
       ON UPPER(oc.name) = UPPER(a.entity_name)
LEFT JOIN ipinfo_share.ip_asn ip ON ip.ip = :resolved_ip
WHERE a.artifact_id = ?;
-- no row  =>  UNVERIFIABLE_ENTITY
```

**6 · The flywheel — free, and our moat**
```sql
SELECT COUNT(*) AS checks,
       SUM(IFF(verdict IN ('DO_NOT_PAY','UNVERIFIABLE_ENTITY'),1,0)) AS flagged,
       MIN(created_at) AS first_seen
FROM receipts WHERE content_sha256 = ?;
```
> *"4 students checked this listing this week. 3 marked it suspicious."*

Zero new infrastructure — receipts were already append-only and content-hashed.
**Students trust other students.** 20 minutes, and the strongest slide in the deck.

**7 · Time Travel — listing history**
```sql
SELECT 'now' v, verdict, headline FROM receipts WHERE content_sha256=?
UNION ALL
SELECT '24h ago', verdict, headline
FROM receipts AT(OFFSET => -86400) WHERE content_sha256=?;
```

### Trust Lab (Streamlit in Snowflake) — 45m, zero hosting
1. **Corpus** — listings + scam patterns loaded, by source
2. **Duplicate explorer** — similarity histogram, side-by-side text
3. **Signals** — analyzer firing rates, verdict distribution
4. **Ask** — Cortex Analyst box → hand the laptop to a judge

---

## 7. TIMELINE — from T+4

### T+4:00 → 4:20 · TRIAGE (no code)
1. `git worktree add ../crowd-p2` — v1 stays live on its URL
2. A announces: *"1 adapter, 4 new analyzers, 2 contract lines, 1 policy profile,
   1 new lens. Kernel untouched."*
3. B declares GDELT **dead** out loud. No mourning. An hour is gone. Move.
4. **Repick the villain together:** a real Waterloo sublet listing with a
   deposit-before-viewing ask. We are demoing to Waterloo people, in Waterloo,
   during Waterloo tech week. Use it.
5. **Read section 0 aloud.** One person reads, everyone listens.

### T+4:20 → 6:20 · THE NEW CORE

**A** — `adapters/listing.py` · `analyzers/pattern.py` · `analyzers/entity_check.py` ·
expand `incentive.py` with payment-timing signals · contract edit + announce ·
`policy.student.yaml` weighted hard toward money-risk.

**B** — **Scam pattern corpus (45m, highest value):** Canadian Anti-Fraud Centre
advisories, FTC scam alerts, r/uwaterloo + r/OffCampusHousing scam threads, UW
off-campus housing warnings. Target **80–150 patterns**, embedded, in Cortex
Search. **Listing corpus (45m):** 500–2,000 Waterloo/KW rental + job listings
through the existing MinHash + embed pipeline. Then entity wiring.

**C** — `ActionLens.tsx` as the default lens, with checkable boxes ·
verdict restyle (red/amber/green/grey) · **camera button bigger than the paste
box** · demote `OriginLens` → `DuplicatesLens`, position 4.

> ### GATE A — T+6:20
> One real listing screenshot → real verdict → real checklist. On a phone.

### T+6:20 → 7:50 · DEPTH

**A** — `baseline.py`, `checklist.py`. Tune `policy.student.yaml` against the
golden set. Wire the peer-check flywheel into the receipt.

**B** — `local_baselines` Dynamic Table · flywheel query · Time Travel query ·
golden set of **20 fixtures: 8 known scams, 8 legitimate, 4 ambiguous** ·
`run_evals.py` green.

**C** — `WhyLens`, `MoneyLens`, `EvidenceSheet` bottom sheet, OG image showing the
verdict, PWA `share_target` tested on a real Android.

> ### GATE B — T+7:50
> Checklist live · baseline live · flywheel live · golden set green

### T+7:50 → 8:40 · SNOWFLAKE TRACK
**B** — Cortex Analyst semantic model over `signals` + `receipts`, tested with 5
real judge questions. Then Trust Lab.
**A** — `README.md` for judges: architecture diagram, explicit Snowflake feature
list, the pivot story.
**C** — desktop pass at projector resolution. Contrast check.

### T+8:40 · CODE FREEZE
**DEMO_MODE runs the entire demo with wifi physically off.** Test it that way, not
theoretically. Warm the warehouse, pre-run every demo query.
Bug fixes on the demo path only.

### T+9:00 → 10:00 · REHEARSE ×6 · SUBMIT AT 9:50

---

## 8. CUT LIST — reordered for this user

**When behind, cut from the bottom up. No debate.**

```
 1. Desktop force graph            ← first to die
 2. Time Travel / listing history
 3. Duplicates lens (signal still fires, no dedicated view)
 4. Cortex Analyst / Trust Lab
 5. baseline.py
──────── BELOW THIS LINE IS MAYA. NEVER CUT. ────────
 6. Peer-check flywheel
 7. checklist.py
 8. pattern.py + incentive.py
 9. Action lens + the verdict
10. DEMO_MODE offline replay
```

Cortex Analyst now sits **above** the cut line while the checklist sits below it.
**Do not sacrifice the product demo for the sponsor demo.** Without it we still
tick AISQL, VECTOR, Cortex Search, Snowpark UDF, Marketplace, Dynamic Tables,
external stage and Time Travel — already more Snowflake surface than anyone else
in the room will have.

---

## 9. RESEARCH

**R1 (repurposed · B · 30m).** Run duplicate detection on **listing text**, not
news. 12 listings: 4 known-duplicate (same scammer, different addresses),
8 distinct. Measure MinHash Jaccard and cosine separation. Duplicate listings
separate more cleanly than syndicated articles, so this should pass more easily
than v1's version. Set `:thresh` at the measured gap midpoint. If it fails,
MinHash alone ships.

**R7 (NEW · C · 15m) — the 5-second test.** Show the receipt to a student who has
never seen it. **Cover the screen after 5 seconds.** Ask: *"what do you do next?"*
If they can't answer, **the design is wrong — not their reading.**
Run it three times during the build. It is the only user test that matters today.

**R8 (NEW · B · 20m) — baseline sanity.** Does the computed median match what
students actually pay in Waterloo? Ask two people in the room. If it's wildly off,
the corpus is skewed and the signal gets cut, not shipped wrong.

**R3 (B · 20m).** `AI_EXTRACT` on a real, recompressed, twice-forwarded WhatsApp
screenshot — not a clean one. Fallback: AWS Textract → Cortex.

**R4 (shared · ongoing).** Full receipt under **20 seconds.** She's between classes.

---

## 10. RISK REGISTER

| Risk | Likelihood | Known by | Mitigation |
|---|---|---|---|
| Scam corpus too thin → `pattern.py` weak | **High** | T+5:30 | 80 patterns minimum; hand-write from CAFC if scraping is slow |
| Listing corpus too small → no duplicates to find | **High** | T+5:30 | **Plant our own**: seed 3 variants of the villain into the corpus. Legitimate — it simulates exactly what the scammer does. |
| Baseline wrong → we confidently mislead Maya | Medium | T+7 (R8) | If unsure, cut `baseline.py`. Silent beats wrong. |
| AI_EXTRACT fails on bad screenshots | Medium | T+5 (R3) | Textract fallback |
| Conference wifi dies | Medium | Demo | DEMO_MODE, tested wifi-off |
| Scope creep back toward v1 generality | **High** | T+7 | Section 1 "NOT building". A enforces. |

Row 3 deserves emphasis. **This user cannot afford a confidently wrong answer.**
If a signal isn't solid, it doesn't ship. `INSUFFICIENT_DATA` is a real verdict and
we should be willing to show it on stage.

---

## 11. THE DEMO — 90 seconds

1. *(15s)* **"I'm a first-year. I found a sublet. They want $2,400 by e-transfer
   tonight and they can't do a viewing."** Everyone in the room has had this
   message or knows who did.
2. *(5s)* Screenshot → tap → phone.
3. *(15s)* Signals stream in live.
4. *(20s)* **⛔ DO NOT SEND MONEY.** Same photos, 3 addresses, 3 prices. No
   landlord on record. Tap any line → the evidence.
5. *(15s)* **The checklist.** "Ask to view in person. Refusal = walk away."
   Five things she can do in the next two minutes.
6. *(10s)* *"4 students checked this listing this week."* Every check makes the
   next student safer.
7. *(10s)* Hand over the laptop → Trust Lab → *"ask our warehouse anything."*

**Never say "trust score." Never say "AI-powered."**
Close on: *"She has $4,100. This is the thing that stops her losing $2,400 of it."*

---

## 12. THE PACT — post in the channel now

> **A** = kernel/analyzers · **B** = snowflake/data/aws · **C** = apps/web
> Never edit outside your lane. Merge to main every 45 minutes.
> **GATE A (T+6:20):** one screenshot → verdict + checklist, on a phone.
> Cut list is written. Cut from the bottom up. No debate.
>
> **If Maya can't act on it in 5 seconds on her phone, it doesn't ship.**

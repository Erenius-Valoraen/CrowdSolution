# legit: is this legit?

A checker for university students living on their own. Paste a rental listing, job offer, bank or loan message, or any post. It pulls out every checkable claim and checks each one against evidence, then gives a risk rating with sources.

## Use it

```bash
python -m legit
```

Paste or type anything, like a listing, a job offer, a message, a post, or a whole video transcript, and press Enter. Long text is read in parts automatically. Each kind of evidence gets its own layout: warning signs, organization cards, price comparisons, side-by-side school tables, and official numbers.

## Run it

Set up Snowflake first using [docs/DATA_ACCESS.md](../docs/DATA_ACCESS.md), and build the benchmark table once with [sql/setup/04_benchmarks.sql](../sql/setup/04_benchmarks.sql). Then run these from the repo root.

**Check a message:**

```bash
python -m legit "Cozy 2BR near UT Austin, $650/month. I'm abroad, send the deposit by Zelle and I'll mail the keys."
```

**Check a file:**

```bash
python -m legit --file listing.txt
```

**Paste interactively** (type END on its own line when done):

```bash
python -m legit
```

**Official data only**, which skips web search and saves Groq tokens:

```bash
python -m legit --offline "..."
```

`--json` prints the report as JSON for a future UI. `--seen-on YYYY-MM-DD` sets the date the message was seen, which matters for statistics.

**Check a YouTube video** from its transcript. Findings link to the timestamp, and claims are judged as of the upload date:

```bash
python -m legit.youtube "https://www.youtube.com/watch?v=4sH30KUfPpM" --offline --max-sections 3
```

## College data setup

The college checker needs the College Scorecard listing from Snowflake Marketplace, attached as database `COLLEGE_SCORECARD`. Then build the cleaned tables once:

```bash
python -c "import sys; sys.path.insert(0,'scripts'); import sf; c=sf.connect(); c.execute_string(open('sql/setup/05_college_scorecard.sql').read())"
```

This creates `CROWDSOLUTION.BENCHMARKS.COLLEGES` (about 6,200 schools), `COLLEGE_PROGRAMS` (about 67,000 programs with earnings or debt), and `PROGRAM_NATIONAL` (typical outcomes per major).

## Groq key

Put your key in a `.env` file in the repo root. `.env` is gitignored.

```text
GROQ_API_KEY=your-key-here
```

Without a key, keyword rules still catch common scam patterns, rents, wages, and rates. They find much less than the AI extraction.

## How it works

1. **Extract.** A Groq model reads the text and lists entities, prices, statistics, scam patterns, and other claims. Keyword rules run too and add anything the model missed. Domains are linked to the organization they name, so `chase-student-rewards.com` is compared with Chase.
2. **Check official data first:**

| Checker | Question | Evidence |
|---|---|---|
| Registry | Is this bank, adviser, company, or charity real? Does the website or email match? | Federal bank registry, SEC adviser registry, company domain registry, IRS nonprofit filings |
| Reputation | What problems do people report with this financial company? | CFPB consumer complaints |
| Benchmark | Is this rent, pay, or interest rate normal? | Census median rent by city and bedrooms, BLS average hourly pay, Fed rates, Statistics Canada rent index |
| Statistic | Was this official number true when it was said? | Point-in-time economic data |
| College | Is this claim about a school or major accurate? How do two schools really compare? | College Scorecard: admissions, tuition, net price, graduation, earnings by school and by major, debt. OpenAlex research output for any university, including Canadian ones. |
| Patterns | Is this a known scam tactic? | FTC and Canadian Anti-Fraud Centre guidance |
| Community | Did other students already report this scam? | Shared scam memory in Backboard.io: exact matches on emails, suspicious domains, and phone numbers, plus similar messages. Checks with red flags are saved automatically. Set `BACKBOARD_API` in `.env`; `COMMUNITY_MEMORY=off` disables it. |

3. **Search the web for the rest.** Anything official data couldn't settle goes into one batched Groq browser-search request, with cited sources.
4. **Report.** HIGH RISK if anything is a red flag, BE CAREFUL for cautions, and NO RED FLAGS FOUND otherwise. Every finding says whether it came from official data, official guidance, or the web.

## Limits

- **Groq's free tier is tight.** Each model allows 8,000 tokens per minute and 200,000 per day. Extraction uses about 2,000 tokens, but one browser search can use over 200,000, so web search often hits the daily limit. The tool reports that and keeps the official-data results.
- **Most registries are US only.** Canadian organizations and rent levels rely on web search. Ontario rent trends come from Statistics Canada.
- **Official data runs through mid-June 2026.** Census rent medians are from 2024, so current rents are likely somewhat higher.
- **College Scorecard covers US schools only.** Canadian schools get OpenAlex research data, and other claims go to web search.
- **Career salaries aren't graduate earnings.** "Developers make $131k" is shown with graduate earnings as context, not judged, because Scorecard measures pay 1, 4, and 5 years after graduating.
- **Monthly changes aren't supported for wages.** A claim like "hourly earnings rose 0.3% last month" is compared with the yearly change and can be wrongly flagged.
- **It's a screening tool.** It can miss scams and flag honest offers. Always open the sources.

## Files

| Path | Job |
|---|---|
| `extract.py` | Groq extraction, keyword rules, domain linking |
| `llm.py` | Groq client with model fallback and rate-limit handling |
| `checkers/` | Registry, reputation, benchmark, statistic, patterns, and web checkers |
| `router.py` | Runs official checks, then the web fallback |
| `report.py` | Terminal and JSON output |
| `stats/` | The point-in-time statistics engine from the pre-pivot concept |
| `youtube.py` | Transcript fetching, sectioning, timestamps, and the video report |
| `checkers/college.py` | College Scorecard and OpenAlex lookups for schools and majors |

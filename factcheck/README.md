# factcheck: was it true when they said it?

A terminal concept. Type a statistical claim and the date it was said. It finds the matching official statistic and compares the claim with three numbers:

- **Known when said:** the latest figure published by that date.
- **Same period today:** that same figure after later revisions.
- **Latest available:** the newest figure in our data.

## Run it

Set up Snowflake first using [docs/DATA_ACCESS.md](../docs/DATA_ACCESS.md). Then run these from the repo root.

**One claim:**

```bash
python -m factcheck "unemployment is 4.1%" --said-on 2025-01-15
```

**Interactive mode:**

```bash
python -m factcheck
```

**Supported statistics:**

```bash
python -m factcheck --list
```

**Tests** (the live ones skip automatically if Snowflake isn't configured):

```bash
python -m unittest discover -s tests -v
```

## Groq (optional)

Without a key, a rule-based parser handles simple one-statistic claims. With a key, Groq pulls claims out of messier text. Every number is still checked against the database.

Put the key in a `.env` file in the repo root. `.env` is gitignored, so it never gets committed.

```text
GROQ_API_KEY=your-key-here
GROQ_MODEL=llama-3.3-70b-versatile
```

`--parser rules` forces the rule-based parser. `--parser groq` errors instead of falling back when Groq fails.

## Verdicts

| Verdict | Meaning |
|---|---|
| ACCURATE WHEN SAID | Matched the latest figure published by that date. Notes say if it was revised since or is outdated now. |
| OUTDATED WHEN SAID | Matched an older figure, but a newer one was already out. |
| WRONG WHEN SAID | Didn't match anything published at the time. |
| NOT YET PUBLISHED WHEN SAID | No figure for that period existed yet. |
| MATCHES / DOESN'T MATCH TODAY'S DATA | There is no record from that date, so the claim is compared with today's revised data. |
| CAN'T VERIFY | No supported statistic, no number, or no data. |

**Rounding is respected.** "4%" allows ±0.5 points, "4.1%" allows ±0.1, and "200,000 jobs" allows up to 10%.

## Files

| File | Job |
|---|---|
| `headline_series.json` | Curated statistics: series IDs, phrasings, units, and scale |
| `parse.py` | Picks Groq or the rule-based parser |
| `parse_rules.py`, `parse_groq.py` | Turn text into a structured claim |
| `lookup.py` | Point-in-time, vintage, and city crime queries |
| `measures.py` | Levels, monthly changes, yearly % changes, and yearly totals |
| `verdict.py` | Tolerance and verdict rules, with no database access |
| `engine.py` | Checks one claim end to end |

**To add a statistic,** add an entry to `headline_series.json`. Get `scale` right: some sources store 4.3% as `0.043` (use `fraction`), others as `4.3` (use `percent`).

## Limits

- **Data runs through mid-June 2026.** The free tier lags about three months.
- **History starts late 2023 to 2024 for most series.** PCE inflation goes back to 2016 and weekly jobless claims to 2020, using release vintages.
- **City crime covers six cities.** Los Angeles data stops in February 2025.
- **FBI crime ends in 2023** and has only one saved version, so there is no revision history.

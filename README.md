# CrowdSolution

PivotHacks 2026 project.

**Problem:** people struggle to decide which online claims, recommendations, reviews, sources, or generated content to trust.

**Who it's for (after Pivot 1):** a university student living on their own for the first time, making decisions about housing, jobs, school, and money.

**What it does:** paste a rental listing, job offer, bank message, or post. It checks every claim against official data first, then the web, and returns a risk rating with sources. See [legit/README.md](legit/README.md).

```bash
python -m legit "Cozy 2BR near campus, $650/month, send the deposit by Zelle and I'll mail the keys."
```

## How we got here

| Stage | Direction |
|---|---|
| Start | "Was it true when they said it?" Check statistics in speeches and threads against official data as published on that day. |
| Pivot 1 | The user became a student living alone. We widened from statistics to "is this legit?", adding registries, price benchmarks, complaint data, scam patterns, and web fallback. The statistics engine became one checker. |

## Repo layout

| Path | What it is |
|---|---|
| `legit/` | The checker: extraction, evidence checkers, web fallback, report |
| `legit/stats/` | Point-in-time statistics engine |
| `docs/DATA_ACCESS.md` | Connect to Snowflake and query the data |
| `sql/setup/` | Account, teammate, token, and benchmark table setup |
| `sql/queries/` | Reusable queries to run in Snowsight |
| `scripts/` | Connection setup and data exploration helpers |
| `tests/` | Unit tests, plus live tests that skip without Snowflake |

## Quick start

```bash
pip install -r requirements.txt
```

```bash
python scripts/configure_snowflake.py
```

```bash
python -m unittest discover -s tests
```

Put `GROQ_API_KEY=...` in a `.env` file in the repo root to enable AI extraction and web search.

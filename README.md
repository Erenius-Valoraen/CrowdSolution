# CrowdSolution

PivotHacks 2026 project.

**Problem:** people struggle to decide which online claims, statistics, and generated content to trust.

**Current direction:** "Was it true when they said it?" We extract statistical claims from speeches and online threads, then check them against official US data *as it was published on the day the claim was made*. A claim can be accurate then, outdated now, or wrong from the start.

## Repo layout

| Path | What it is |
|---|---|
| `docs/DATA_ACCESS.md` | Start here: connect to Snowflake and query the data |
| `scripts/` | Python helpers: connection setup, series search, point-in-time lookups |
| `sql/setup/` | One-time account, teammate, and token setup |
| `sql/queries/` | Reusable queries to run in Snowsight |

## Quick start

```bash
pip install -r requirements.txt
python scripts/configure_snowflake.py
python scripts/as_of.py LNS14000000.M_SA --date 2025-01-15
```

See [docs/DATA_ACCESS.md](docs/DATA_ACCESS.md) for getting a login and token first.

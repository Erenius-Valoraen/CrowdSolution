# Getting the data

How to connect to our Snowflake account and query the official statistics we fact-check against.

## What we have

All data comes from the free **Snowflake Public Data** listing, attached as the database `SNOWFLAKE_PUBLIC_DATA_FREE`, schema `PUBLIC_DATA_FREE`.

| Table | What it holds |
|---|---|
| `FINANCIAL_ECONOMIC_INDICATORS_ATTRIBUTES` | Catalog of ~170k statistics series: ID, name, frequency, unit, source agency |
| `FINANCIAL_ECONOMIC_INDICATORS_TIMESERIES` | Current values for every series, back to 1913 |
| `FINANCIAL_ECONOMIC_INDICATORS_TIMESERIES_PIT` | Every published version of every value, with `_EFFECTIVE_START_TIMESTAMP` and `_EFFECTIVE_END_TIMESTAMP` |
| `FBI_CRIME_ATTRIBUTES` / `_TIMESERIES` | FBI annual crime counts, US and states, 1979 to 2023 |
| `URBAN_CRIME_INCIDENT_LOG` | Individual incidents for 6 big US cities, through mid-2026 |
| `DATACOMMONS_*`, `OPENALEX_*`, `FINANCIAL_CFPB_COMPLAINT` | Demographics, research papers, consumer complaints |

**The point-in-time table is the key one.** It tells us what number had been published on any given day, so we can judge a claim by what the speaker could have known.

Verified headline series:

| Series ID | Meaning | Unit |
|---|---|---|
| `LNS14000000.M_SA` | Unemployment rate, monthly | fraction, 0.043 = 4.3% |
| `CES0000000001.M_SA` | Total nonfarm jobs, monthly | count |
| `CUSRSA0SA01982-84.M` | CPI all items, monthly | index, 1982-84 = 100 |
| `BEA_NIPA_1.1.1_A191RL_Q` | Real GDP growth, quarterly | percent change, annual rate |

### Known limits

- **Point-in-time history starts in 2024.** It begins March 2024 for the table and August 2024 for some series. Older dates return nothing.
- **About one quarter of lag.** In September 2026 the newest jobs figure is May 2026.
- **Cortex AI functions are blocked on trial accounts.** `AI_COMPLETE`, `AI_CLASSIFY`, and the rest all fail. Claim-to-series matching uses an external model for now.
- **Many near-duplicate series.** Unemployment alone has dozens of variants by age, sex, race, and seasonal adjustment. Prefer names containing "Seasonally adjusted" and no subgroup.

## Setup

We share one Snowflake account. Abhi is the admin.

### 1. Get a login

Ask Abhi to run `sql/setup/02_add_teammate.sql` for you. Abhi then sends you a username and a temporary password privately. Log in at https://app.snowflake.com and set a new password.

*Using your own trial account instead?* Run `sql/setup/01_account_setup.sql` in your account first. Your AI functions will be blocked too.

### 2. Create your access token

In Snowsight, open **Projects > Workspaces** (or **Worksheets**), click **+**, and create a SQL file. Paste `sql/setup/03_create_my_token.sql`, then run it. Copy the `TOKEN_SECRET` from the result right away, because it is shown only once.

### 3. Configure your machine

```bash
pip install -r requirements.txt
python scripts/configure_snowflake.py
```

It asks for three things:

- **Account identifier:** `DURSAFQ-VX02090`
- **Username:** your Snowflake login name
- **Token:** paste it at the hidden prompt

It writes `~/.snowflake/connections.toml` outside the repo, then runs the connection check. Three `[pass]` lines mean you are set. The Cortex line will say unavailable, which is expected.

## Using the data

**Search for a series:**

```bash
python scripts/find_series.py unemployment rate --frequency Monthly
```

**What had been published by a date:**

```bash
python scripts/as_of.py LNS14000000.M_SA --date 2025-01-15
```

**How a number was revised over time:**

```bash
python scripts/as_of.py CES0000000001.M_SA --period 2024-06-30
```

**From Python:**

```python
import sys; sys.path.insert(0, "scripts")
import sf

rows = sf.query(
    f"SELECT VALUE FROM {sf.PUBLIC}.FINANCIAL_ECONOMIC_INDICATORS_TIMESERIES "
    "WHERE VARIABLE = %(v)s ORDER BY DATE DESC LIMIT 1",
    {"v": "LNS14000000.M_SA"},
)
```

**In Snowsight:** open any file in `sql/queries/`, edit the `SET` values at the top, and run it.

## Troubleshooting

| Error | Fix |
|---|---|
| `OSError [Errno 22] Invalid argument ... python.exe` | Microsoft Store Python bug. Use `scripts/sf.py`, which patches it, instead of calling the connector directly. |
| `terms for the associated listing ... have not been accepted` | In Snowsight, go to Marketplace, find "Snowflake Public Data (Free)", click Get, and name the database `SNOWFLAKE_PUBLIC_DATA_FREE`. |
| `Network policy is required` | Your user is missing the authentication policy. Ask Abhi to rerun the last line of `02_add_teammate.sql` for you. |
| `AI function ... is not available for trial accounts` | Expected. Snowflake blocks Cortex AI on trials. |
| Token expired or leaked | Rerun `03_create_my_token.sql` after removing the old token, using the commented line in that file. |

## Security

- **Tokens live only in `~/.snowflake/connections.toml`.** `.gitignore` blocks common secret files, but check `git status` before committing.
- **Never paste tokens in chat, Slack, or issues.** If one leaks, remove it and create a new one.

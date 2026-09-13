# Deploying Trustify on Vercel

The FastAPI app in `api/main.py` deploys as one Vercel Function. Vercel serves the frontend (`frontend/`, mounted at `/static`) from its CDN.

## Files

| File | Purpose |
|---|---|
| `pyproject.toml` | Runtime dependencies and `tool.vercel.entrypoint = "api.main:app"` |
| `vercel.json` | Lets checks run up to 300 seconds (YouTube checks take 1 to 2.5 minutes) and trims the bundle |
| `.vercelignore` | Keeps `.env`, local databases, tests, docs, and SQL out of the upload |
| `scripts/vercel_env.py` | Copies your keys into Vercel environment variables without printing them |

## Steps

```bash
npm install -g vercel
vercel login
vercel link
python scripts/vercel_env.py --dry-run
python scripts/vercel_env.py
vercel deploy
vercel deploy --prod
```

`vercel deploy` makes a preview URL to test. `vercel deploy --prod` publishes it.

## Environment variables

| Variable | Used for |
|---|---|
| `SNOWFLAKE_ACCOUNT`, `SNOWFLAKE_USER`, `SNOWFLAKE_TOKEN` | Official data. The token is a Snowflake programmatic access token. |
| `SNOWFLAKE_ROLE`, `SNOWFLAKE_WAREHOUSE` | Optional; default `SYSADMIN` and `COMPUTE_WH` |
| `PIVOT_AI`, `CORTEX_ACCOUNT` | Snowflake Cortex (reading text and web results) |
| `GROQ_API_KEY` | Backup AI, voice typing (Whisper), spoken results |
| `TAVILY_API` | Web search |
| `SUPADATA_API` | YouTube transcripts. Required on Vercel, because YouTube blocks transcript requests from cloud servers. Free tier: 100 a month. |
| `BACKBOARD_API` | Shared scam memory |

Vercel sets `VERCEL=1` itself. The app uses it to keep history and Snowflake caches in `/tmp`.

## Known limits

- **History and share links are temporary.** They live in `/tmp` on whichever server instance handled the check, so they disappear on redeploys and may not be found from another instance. The spoken summary sends the report along, so it still works.
- **YouTube blocks transcript requests from cloud servers**, so the deployed app reads transcripts through Supadata (`SUPADATA_API`). Each video uses one transcript credit, plus one for video details when YouTube's page can't be read. When the free quota runs out, students see a message asking them to paste the transcript text.
- **Snowflake must accept connections from Vercel.** Our account's authentication policy doesn't require a network policy for access tokens (`sql/setup/03_create_my_token.sql`); keep it that way, since Vercel's IP addresses change.
- **Checks can run up to 300 seconds** on the Hobby plan, which covers every check type today.

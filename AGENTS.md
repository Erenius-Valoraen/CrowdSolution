# Notes for AI agents working on this repo

CrowdSolution is a PivotHacks 2026 project: an "is this legit?" checker for university students living on their own. Paste a listing, job offer, message, post, or transcript and it checks every claim against official data (Snowflake) and the web.

## Start here

- **Building the frontend or browser extension:** read [docs/FRONTEND_GUIDE.md](docs/FRONTEND_GUIDE.md). It has the full API contract, every `data` shape, rendering guidance, limits, and real responses in `docs/examples/`.
- **Working on the checking engine:** read [legit/README.md](legit/README.md).
- **Querying the data directly:** read [docs/DATA_ACCESS.md](docs/DATA_ACCESS.md).

## Run

```bash
pip install -r requirements.txt
python run_server.py          # API on http://127.0.0.1:8000, docs at /docs
python -m legit               # terminal UI: paste anything
python -m unittest discover -s tests
```

## Rules

- **Never commit secrets.** Keys live in `.env` (gitignored) and `~/.snowflake/connections.toml`. Never put keys in frontend or extension code.
- **Ask the user before committing or pushing.**
- **Web search is on by default** in the API (`offline: false`). Keep it that way unless the user says otherwise.
- **Community scam memory is shared and real.** Every check with red flags is saved to Backboard. Set `COMMUNITY_MEMORY=off` in tests and experiments, or use `BACKBOARD_COMMUNITY_ASSISTANT=<test name>`, so test scans don't pollute it. It only stores scammer indicators, red flags, a summary, and a short excerpt, never student details.
- **Build UI on `checker`, `status`, and `data`,** not on title or summary text, which the AI phrases differently each run.
- **Don't let the AI write SQL.** Checkers run fixed, parameterized queries. New data sources get a new checker in `legit/checkers/` and a line in `OFFICIAL` in `legit/router.py`.

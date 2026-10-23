"""Copy this project's keys into Vercel environment variables. Run it yourself after `vercel login` and `vercel link`.

  python scripts/vercel_env.py            # production and preview
  python scripts/vercel_env.py --dry-run  # list what would be set, without sending anything

Reads .env and the [crowdsolution] connection in ~/.snowflake/connections.toml. Values are passed to the Vercel CLI
on stdin and never printed."""
from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DOTENV_KEYS = ["GROQ_API_KEY", "PIVOT_AI", "CORTEX_ACCOUNT", "BACKBOARD_API", "TAVILY_API", "SUPADATA_API"]
SNOWFLAKE_KEYS = {"account": "SNOWFLAKE_ACCOUNT", "user": "SNOWFLAKE_USER", "token": "SNOWFLAKE_TOKEN",
                  "role": "SNOWFLAKE_ROLE", "warehouse": "SNOWFLAKE_WAREHOUSE"}


def read_dotenv(path: Path) -> dict[str, str]:
    values = {}
    for line in path.read_text(encoding="utf-8").splitlines() if path.exists() else []:
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, _, value = line.partition("=")
            values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def collect() -> dict[str, str]:
    env = read_dotenv(ROOT / ".env")
    wanted = {k: env[k] for k in DOTENV_KEYS if env.get(k)}
    toml_path = Path.home() / ".snowflake" / "connections.toml"
    if toml_path.exists():
        conn = tomllib.loads(toml_path.read_text(encoding="utf-8")).get("crowdsolution", {})
        wanted.update({name: str(conn[key]) for key, name in SNOWFLAKE_KEYS.items() if conn.get(key)})
    return wanted


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dry-run", action="store_true", help="list variable names only")
    ap.add_argument("--environments", default="production,preview", help="comma-separated Vercel environments")
    args = ap.parse_args()

    values = collect()
    missing = [k for k in DOTENV_KEYS + list(SNOWFLAKE_KEYS.values()) if k not in values]
    print("Will set:", ", ".join(sorted(values)) or "nothing")
    if missing:
        print("Not found locally (set these in the Vercel dashboard if you need them):", ", ".join(missing))
    if args.dry_run:
        return 0
    vercel = shutil.which("vercel")
    if not vercel:
        print("Vercel CLI not found. Install it with: npm install -g vercel", file=sys.stderr)
        return 1
    failed = 0
    for environment in [e.strip() for e in args.environments.split(",") if e.strip()]:
        for name, value in sorted(values.items()):
            result = subprocess.run([vercel, "env", "add", name, environment, "--force"], input=value,
                                    text=True, capture_output=True, cwd=ROOT)
            ok = result.returncode == 0
            failed += not ok
            print(f"  {'set' if ok else 'FAILED'} {name} ({environment})"
                  + ("" if ok else f": {result.stderr.strip().splitlines()[-1] if result.stderr.strip() else 'unknown error'}"))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())

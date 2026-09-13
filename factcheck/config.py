"""Settings. Secrets come from environment variables or a gitignored .env file in the repo root."""
import os
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


def load_dotenv(path: Path = REPO_ROOT / ".env") -> None:
    """Minimal .env loader: KEY=VALUE lines. Never overrides variables that are already set."""
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


load_dotenv()

SNOWFLAKE_CONNECTION = os.environ.get("CROWDSOLUTION_SF_CONNECTION", "crowdsolution")
GROQ_MODEL = os.environ.get("GROQ_MODEL", "llama-3.3-70b-versatile")

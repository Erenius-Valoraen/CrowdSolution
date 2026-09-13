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
GROQ_MODEL = os.environ.get("GROQ_MODEL", "openai/gpt-oss-120b")
SEARCH_MODEL = os.environ.get("GROQ_SEARCH_MODEL", "openai/gpt-oss-120b")


def _models(var: str, default: str) -> list[str]:
    return [m.strip() for m in os.environ.get(var, default).split(",") if m.strip()]


# Tried in order; the next model is used when one hits its rate limit.
# Qwen first: fast (about 1 second) and cheap per call. GPT-OSS models are kept as backups.
EXTRACT_MODELS = _models("GROQ_EXTRACT_MODELS", "qwen/qwen3.8-27b,qwen/qwen3.6-27b,openai/gpt-oss-120b,openai/gpt-oss-20b")
SEARCH_MODELS = _models("GROQ_SEARCH_MODELS", f"{SEARCH_MODEL},openai/gpt-oss-20b")

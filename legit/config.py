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

# Snowflake Cortex (REST chat completions). The token is a Snowflake programmatic access token for the account below.
CORTEX_TOKEN = os.environ.get("CORTEX_PAT") or os.environ.get("PIVOT_AI")
CORTEX_ACCOUNT = os.environ.get("CORTEX_ACCOUNT")          # account identifier, e.g. MYORG-MYACCOUNT
CORTEX_PREFIX = "cortex:"


def _models(var: str, default: str) -> list[str]:
    return [m.strip() for m in os.environ.get(var, default).split(",") if m.strip()]


def cortex_configured() -> bool:
    return bool(CORTEX_TOKEN and CORTEX_ACCOUNT)


GROQ_EXTRACT_MODELS = _models("GROQ_EXTRACT_MODELS", "qwen/qwen3.8-27b,qwen/qwen3.6-27b,openai/gpt-oss-120b,openai/gpt-oss-20b")
CORTEX_MODELS = _models("CORTEX_MODELS", "claude-haiku-4-5,openai-gpt-5-mini,llama3.3-70b")

# Tried in order; the next model is used when one hits a rate limit or is unavailable.
# Snowflake Cortex goes first when configured; Groq models are the backup.
EXTRACT_MODELS = ([CORTEX_PREFIX + m for m in CORTEX_MODELS] if cortex_configured() else []) + GROQ_EXTRACT_MODELS
# Backboard.io shared scam memory across students.
BACKBOARD_KEY = os.environ.get("BACKBOARD_API_KEY") or os.environ.get("BACKBOARD_API")
BACKBOARD_COMMUNITY_ASSISTANT = os.environ.get("BACKBOARD_COMMUNITY_ASSISTANT", "crowdsolution-community-memory")
BACKBOARD_COMMUNITY_ASSISTANT_ID = os.environ.get("BACKBOARD_COMMUNITY_ASSISTANT_ID")
COMMUNITY_MEMORY = os.environ.get("COMMUNITY_MEMORY", "on").strip().lower() not in ("off", "0", "false", "no")

# Web checks search, then these models read the results (Cortex first, like extraction).
READ_MODELS = EXTRACT_MODELS
# Optional search APIs. Without one, web checks use DuckDuckGo's HTML page, which blocks heavy automated use.
TAVILY_API_KEY = os.environ.get("TAVILY_API_KEY") or os.environ.get("TAVILY_API")
BRAVE_SEARCH_API_KEY = os.environ.get("BRAVE_SEARCH_API_KEY")
# Voice typing: Groq Whisper speech-to-text, tried in order when one is rate limited.
TRANSCRIBE_MODELS = _models("GROQ_TRANSCRIBE_MODELS", "whisper-large-v3-turbo,whisper-large-v3")
# Spoken results: Groq text-to-speech. Its terms must be accepted once in the Groq console; until then the web app
# falls back to the browser's built-in voice.
TTS_MODEL = os.environ.get("GROQ_TTS_MODEL", "canopylabs/orpheus-v1-english")
TTS_VOICE = os.environ.get("GROQ_TTS_VOICE", "hannah")
# Backup web search uses Groq's browser_search tool, which Cortex chat completions don't offer.
SEARCH_MODELS = _models("GROQ_SEARCH_MODELS", f"{SEARCH_MODEL},openai/gpt-oss-20b")

"""Check that Snowflake Cortex chat completions work with the settings in .env. Never prints the token.

Needs in .env:
    CORTEX_ACCOUNT=MYORG-MYACCOUNT      (account identifier of the account that issued the token)
    PIVOT_AI=<programmatic access token>  (or CORTEX_PAT)

Usage:  python scripts/check_cortex.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from legit import config, llm  # noqa: E402

print("token set:", bool(config.CORTEX_TOKEN))
print("account set:", config.CORTEX_ACCOUNT or "MISSING (add CORTEX_ACCOUNT=ORGNAME-ACCOUNTNAME to .env)")
if not config.cortex_configured():
    sys.exit(1)
print("endpoint:", llm.cortex_url(config.CORTEX_ACCOUNT))

ok = False
for model in config.CORTEX_MODELS:
    try:
        reply = llm.chat([{"role": "user", "content": 'Reply with only this JSON: {"ok": true}'}],
                         model=config.CORTEX_PREFIX + model, json_mode=True, timeout=60)
        print(f"[pass] {model}: {(reply.get('content') or '')[:60]!r} -> parsed {llm.parse_json(reply.get('content'))}")
        ok = True
    except llm.LLMError as e:
        print(f"[fail] {model}: {str(e)[:200]}")
sys.exit(0 if ok else 1)

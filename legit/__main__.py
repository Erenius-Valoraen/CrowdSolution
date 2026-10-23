"""Terminal interface.

  python -m legit "Cozy 2BR near campus, $650/month, send the deposit by Zelle..."
  python -m legit --file listing.txt
  python -m legit                        (paste text, then a line with just END)
"""
from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path

from . import db, llm, report, router


def read_pasted() -> str:
    print("Paste the listing, offer, or message. Then type END on its own line and press Enter.", file=sys.stderr)
    lines = []
    for line in sys.stdin:
        if line.strip() == "END":
            break
        lines.append(line)
    return "".join(lines).strip()


def main(argv=None) -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")

    ap = argparse.ArgumentParser(prog="python -m legit", description="Is this legit? Checks a listing, offer, or message.")
    ap.add_argument("text", nargs="?", help="the text to check; omit to paste it")
    ap.add_argument("--file", type=Path, help="read the text from a file")
    ap.add_argument("--seen-on", type=date.fromisoformat, default=date.today(), help="date you saw it, YYYY-MM-DD")
    ap.add_argument("--offline", action="store_true", help="official data only; skip web search")
    ap.add_argument("--json", action="store_true", help="print the report as JSON")
    args = ap.parse_args(argv)

    if not args.text and not args.file and not args.json:
        from .demo import main as interactive  # the paste-anything experience

        return interactive(["--offline"] if args.offline else [])

    if args.file:
        text = args.file.read_text(encoding="utf-8")
    elif args.text:
        text = args.text
    else:
        text = read_pasted()
    if not text.strip():
        print("Nothing to check.", file=sys.stderr)
        return 1

    if not llm.available():
        print("Note: GROQ_API_KEY isn't set, so extraction is limited and web search is off.", file=sys.stderr)
    try:
        result = router.run(text, args.seen_on, offline=args.offline)
    finally:
        db.close()
    print(report.to_json(result) if args.json else "\n" + report.render(result))
    return 0


if __name__ == "__main__":
    sys.exit(main())

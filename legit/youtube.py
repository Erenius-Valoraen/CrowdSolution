"""Check the claims in a YouTube video from its transcript, with timestamps.

  python -m legit.youtube https://www.youtube.com/watch?v=VIDEO_ID
  python -m legit.youtube VIDEO_ID --offline --max-sections 3

Claims are checked as of the video's upload date, so a statistic that was true when the video was published
counts as accurate even if it has since been revised."""
from __future__ import annotations

import argparse
import dataclasses
import html
import json
import re
import sys
import urllib.request
from dataclasses import dataclass, field
from datetime import date

from . import db, extract, llm, router
from .models import SEVERITY, Extraction, Finding, Report
from .report import KIND_LABELS, TAGS, _wrap

MAX_SECTION_CHARS = 3000   # keeps each extraction call well under Groq's 8K tokens-per-minute limit
WEB_WORTHY_ENTITIES = {"company", "employer", "bank", "lender", "loan_servicer", "credit_card", "investment_adviser",
                       "website", "landlord", "property_manager", "charity"}
VIDEO_ID = re.compile(r"(?:v=|youtu\.be/|shorts/|embed/|live/)([A-Za-z0-9_-]{11})")
HINT = ("This text is one section of a YouTube video transcript{about}, published {published}. It is spoken language, "
        "often without punctuation, and may be auto-captioned. Extract the speaker's checkable factual claims, "
        "statistics, prices and rates, claims about specific schools and majors, and advice. Skip predictions, "
        "forecasts, consensus estimates, greetings, jokes, and sponsor reads. Only list an organization as an entity "
        "if the video gives its website or asks viewers to contact it.")
FORECAST = re.compile(r"\b(expect\w*|forecast\w*|consensus|estimate[sd]?|predict\w*|projected|projections?|could|would|might)\b", re.I)


def _skip_in_video(item) -> bool:
    """Mentions of organizations aren't solicitations, and forecasts aren't facts."""
    if item.kind == "entity" and not (item.data.get("website") or item.data.get("email_domain")):
        return True
    if item.kind == "claim" and not re.search(r"\d", item.text or ""):
        return True  # opinions and advice without numbers only add noise to a video report
    return item.kind in ("statistic", "claim", "school") and bool(FORECAST.search(item.text or ""))


@dataclass
class Segment:
    start: float
    duration: float
    text: str


@dataclass
class Section:
    start: float
    end: float
    text: str
    segments: list[Segment] = field(default_factory=list)


@dataclass
class VideoInfo:
    video_id: str
    title: str | None = None
    channel: str | None = None
    upload_date: date | None = None
    language: str | None = None
    auto_captions: bool | None = None

    @property
    def url(self) -> str:
        return f"https://youtu.be/{self.video_id}"


@dataclass
class TimedFinding:
    seconds: float | None
    finding: Finding


def parse_video_id(value: str) -> str:
    value = value.strip()
    if m := VIDEO_ID.search(value):
        return m.group(1)
    if re.fullmatch(r"[A-Za-z0-9_-]{11}", value):
        return value
    raise ValueError(f"Couldn't find a YouTube video ID in {value!r}")


def timestamp(seconds: float | None) -> str:
    if seconds is None:
        return "--:--"
    s = int(seconds)
    return f"{s // 3600}:{s % 3600 // 60:02d}:{s % 60:02d}" if s >= 3600 else f"{s // 60}:{s % 60:02d}"


def fetch_info(video_id: str) -> VideoInfo:
    """Title, channel, and upload date from the public watch page. Best effort; fields stay None on failure."""
    info = VideoInfo(video_id)
    try:
        req = urllib.request.Request(f"https://www.youtube.com/watch?v={video_id}",
                                     headers={"User-Agent": "Mozilla/5.0", "Accept-Language": "en-US,en;q=0.8"})
        page = urllib.request.urlopen(req, timeout=20).read().decode("utf-8", "replace")
    except Exception:  # noqa: BLE001
        return info
    if m := (re.search(r'"uploadDate":"(\d{4}-\d{2}-\d{2})', page) or re.search(r'"publishDate":"(\d{4}-\d{2}-\d{2})', page)):
        info.upload_date = date.fromisoformat(m.group(1))
    if m := re.search(r'<meta name="title" content="([^"]*)"', page):
        info.title = html.unescape(m.group(1))
    if m := re.search(r'"ownerChannelName":"([^"]*)"', page):
        info.channel = html.unescape(m.group(1))
    return info


def fetch_transcript(video_id: str) -> tuple[list[Segment], str, bool]:
    """English transcript, preferring human-made captions over auto-generated ones."""
    from youtube_transcript_api import YouTubeTranscriptApi

    transcripts = YouTubeTranscriptApi().list(video_id)
    languages = ["en", "en-US", "en-GB", "en-CA"]
    try:
        chosen = transcripts.find_manually_created_transcript(languages)
    except Exception:  # noqa: BLE001
        chosen = transcripts.find_transcript(languages)
    segments = [Segment(float(s.start), float(s.duration), " ".join(s.text.split()))
                for s in chosen.fetch() if s.text and s.text.strip()]
    return segments, chosen.language_code, chosen.is_generated


def make_sections(segments: list[Segment], max_chars: int = MAX_SECTION_CHARS) -> list[Section]:
    sections: list[Section] = []
    current: list[Segment] = []
    size = 0
    for seg in segments:
        if current and size + len(seg.text) + 1 > max_chars:
            sections.append(_section(current))
            current, size = [], 0
        current.append(seg)
        size += len(seg.text) + 1
    if current:
        sections.append(_section(current))
    return sections


def _section(segments: list[Segment]) -> Section:
    last = segments[-1]
    return Section(segments[0].start, last.start + last.duration, " ".join(s.text for s in segments), list(segments))


_WORD = re.compile(r"\$?\d[\d,.]*%?|[a-z']+")


def _words(text: str) -> list[str]:
    return [w.rstrip(".,") for w in _WORD.findall(text.lower())]


def locate(quote: str, section: Section) -> float:
    """Start time of the caption line where a quote begins, falling back to the first matching number."""
    words = _words(quote)
    timed = [(w, seg.start) for seg in section.segments for w in _words(seg.text)]
    for n in (4, 3, 2):
        key = words[:n]
        if len(key) < n:
            continue
        for i in range(len(timed) - n + 1):
            if [w for w, _ in timed[i:i + n]] == key:
                return timed[i][1]
    for w in words:
        if any(ch.isdigit() for ch in w):
            for tw, start in timed:
                if tw == w:
                    return start
    return section.start


def check_video(url: str, *, offline: bool = False, max_sections: int = 6, seen_on: date | None = None,
                progress=router._progress) -> tuple[VideoInfo, Report, list[TimedFinding]]:
    video_id = parse_video_id(url)
    progress("Fetching video details and transcript...")
    info = fetch_info(video_id)
    segments, info.language, info.auto_captions = fetch_transcript(video_id)
    said_on = seen_on or info.upload_date or date.today()
    sections = make_sections(segments)

    notes: list[str] = []
    if info.upload_date is None and seen_on is None:
        notes.append("Couldn't read the upload date; checked claims as of today.")
    if len(sections) > max_sections:
        notes.append(f"Checked the first {max_sections} of {len(sections)} transcript sections "
                     f"(up to {timestamp(sections[max_sections - 1].end)}). Use --max-sections for more.")
        sections = sections[:max_sections]

    about = f' titled "{info.title}"' if info.title else ""
    about += f" from {info.channel}" if info.channel else ""
    hint = HINT.format(about=about, published=said_on.isoformat())
    combined = Extraction(said_on=said_on, summary=f"YouTube video{about}", parser="")
    findings: list[Finding] = []
    needs_web = []
    item_seconds: dict[int, float] = {}
    next_id = 1

    for n, section in enumerate(sections, start=1):
        progress(f"Reading section {n}/{len(sections)} ({timestamp(section.start)}-{timestamp(section.end)})...")
        ext, ext_notes = extract.extract(section.text, said_on, hint=hint)
        notes.extend(f"[{timestamp(section.start)}] {x}" for x in ext_notes if not x.startswith("Keyword rules"))
        ext.items = [i for i in ext.items if not _skip_in_video(i)]
        for i in ext.items:
            if i.kind == "price" and (i.data.get("category") or "") in ("hourly_wage", "salary"):
                i.kind, i.data = "claim", {"claim": i.text}  # a salary in a video is a claim, not an offer
        for item in ext.items:
            item.id = next_id
            next_id += 1
            item_seconds[item.id] = locate(item.text, section)
        combined.items.extend(ext.items)
        combined.parser = ext.parser
        if combined.context == "other":
            combined.context = ext.context
        if not combined.location.label() and ext.location.label():
            combined.location = ext.location
        section_findings, section_needs = router.check_official(ext, notes)
        findings.extend(section_findings)
        needs_web.extend(i for i in section_needs
                         if i.kind != "entity" or (i.data.get("entity_type") or "") in WEB_WORTHY_ENTITIES)

    report = router.finish(combined, findings, needs_web, notes, offline=offline, progress=progress)
    timed = sorted((TimedFinding(item_seconds.get(f.item.id), f) for f in report.findings),
                   key=lambda t: (t.seconds if t.seconds is not None else 1e9, -SEVERITY[t.finding.status]))
    return info, report, timed


def render(info: VideoInfo, report: Report, timed: list[TimedFinding]) -> str:
    counts = ", ".join(f"{report.count(s)} {TAGS[s].lower()}" for s in ("red_flag", "caution", "unverified", "ok")
                       if report.count(s))
    captions = "auto-generated captions" if info.auto_captions else "creator captions"
    lines = [
        f"Video:    {info.title or info.video_id}" + (f"  |  {info.channel}" if info.channel else ""),
        f"          {info.url}  |  published {info.upload_date or 'unknown'}  |  {info.language} {captions}",
        f"Overall:  {report.overall}" + (f"  ({counts})" if counts else ""),
        "Claims are judged against what official data showed on the publish date.",
    ]
    for t in timed:
        f = t.finding
        link = f"{info.url}?t={int(t.seconds)}" if t.seconds is not None else info.url
        lines.append("")
        lines.append(f"[{timestamp(t.seconds)}] [{TAGS[f.status]}] {f.title}")
        lines += _wrap(f'"{f.item.text}"  {link}', "    ")
        if f.summary:
            lines += _wrap(f.summary, "    ")
        for ev in f.evidence:
            url = f" {ev.url}" if ev.url else ""
            lines += _wrap(f"- {ev.source} [{KIND_LABELS.get(ev.kind, ev.kind)}]: {ev.detail}{url}", "      ")
    if report.notes:
        lines.append("")
        lines += [f"Note: {n}" for n in report.notes]
    return "\n".join(lines)


def to_json(info: VideoInfo, report: Report, timed: list[TimedFinding]) -> str:
    def default(o):
        if isinstance(o, date):
            return o.isoformat()
        raise TypeError(type(o).__name__)

    return json.dumps({
        "video": dataclasses.asdict(info) | {"url": info.url},
        "overall": report.overall,
        "findings": [{"seconds": t.seconds, "timestamp": timestamp(t.seconds), **dataclasses.asdict(t.finding)} for t in timed],
        "notes": report.notes,
    }, default=default, indent=2)


def main(argv=None) -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(prog="python -m legit.youtube", description="Fact-check a YouTube video from its transcript.")
    ap.add_argument("video", help="YouTube URL or video ID")
    ap.add_argument("--offline", action="store_true", help="official data only; skip web search")
    ap.add_argument("--max-sections", type=int, default=6, help="transcript sections to check (about 3,000 characters each)")
    ap.add_argument("--seen-on", type=date.fromisoformat, help="check claims as of this date instead of the upload date")
    ap.add_argument("--json", action="store_true", help="print JSON (for a browser extension)")
    args = ap.parse_args(argv)
    if not llm.available():
        print("Note: GROQ_API_KEY isn't set, so claim extraction is very limited.", file=sys.stderr)
    try:
        info, report, timed = check_video(args.video, offline=args.offline, max_sections=args.max_sections, seen_on=args.seen_on)
    except Exception as e:  # noqa: BLE001
        print(f"Couldn't check this video: {type(e).__name__}: {e}", file=sys.stderr)
        return 1
    finally:
        db.close()
    print(to_json(info, report, timed) if args.json else "\n" + render(info, report, timed))
    return 0


if __name__ == "__main__":
    sys.exit(main())

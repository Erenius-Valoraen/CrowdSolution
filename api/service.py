"""
Verification service layer.
Connects the legit engine to the frontend JSON contract.
Generates actionable checklists, badge metadata, and structured groupings.
"""
from __future__ import annotations

import datetime as dt
import re
import uuid
from datetime import date
from typing import Any

from legit import config, db, llm, report, router, youtube
from legit.models import SEVERITY, Finding, Report
from legit.report import KIND_LABELS, TAGS

from . import storage

# A message that is just a YouTube link: we fetch the transcript and check the video instead of the text.
YOUTUBE_LINK = re.compile(
    r"^\s*(?:https?://)?(?:www\.|m\.|music\.)?"
    r"(?:youtube\.com/(?:watch\?\S*?v=|shorts/|embed/|live/)|youtu\.be/)[A-Za-z0-9_-]{11}\S*\s*$",
    re.I,
)
VIDEO_MAX_SECTIONS = 6      # about 3,000 characters each, roughly the first 20 minutes of speech
TRANSCRIPT_LINE_CHARS = 220

TRANSCRIPT_ERRORS = {
    "TranscriptsDisabled": "This video has captions turned off, so there's no transcript to check.",
    "NoTranscriptFound": "This video has no English captions to check.",
    "VideoUnavailable": "That video is unavailable. It may be private, deleted, or age-restricted.",
    "InvalidVideoId": "That doesn't look like a valid YouTube video link.",
    "AgeRestricted": "That video is age-restricted, so its transcript can't be read.",
    "RequestBlocked": "YouTube is blocking transcript requests from this server right now. Paste the transcript text instead.",
    "IpBlocked": "YouTube is blocking transcript requests from this server right now. Paste the transcript text instead.",
}


class InputError(ValueError):
    """The request can't be checked as given; the message is safe to show to the user."""


def is_youtube_link(text: str) -> bool:
    return bool(YOUTUBE_LINK.match(text or ""))

STATUS_COLOR = {
    "red_flag": "red",
    "caution": "yellow",
    "ok": "green",
    "info": "blue",
    "unverified": "gray",
}

OVERALL_META = {
    "HIGH RISK": {
        "color": "red",
        "message": "High risk detected. Do not send money, deposits, or sensitive personal information.",
    },
    "BE CAREFUL": {
        "color": "yellow",
        "message": "Caution advised. Several details do not hold up or require in-person verification.",
    },
    "NO RED FLAGS FOUND": {
        "color": "green",
        "message": "No obvious red flags found. Terms and entities appear consistent with known standards.",
    },
    "COULDN'T VERIFY": {
        "color": "gray",
        "message": "Could not confirm these details against official records. Verify independently before proceeding.",
    },
    "NOTHING TO CHECK": {
        "color": "gray",
        "message": "No verifiable claims, prices, or offers were identified in this text.",
    },
}


SPOKEN_OPENERS = {
    "HIGH RISK": "This looks high risk.",
    "BE CAREFUL": "Be careful with this one.",
    "NO RED FLAGS FOUND": "Good news: nothing here raised a red flag.",
    "COULDN'T VERIFY": "I couldn't verify most of this, so treat it with caution.",
    "NOTHING TO CHECK": "I didn't find any specific claims, prices, or offers to check.",
}
SPOKEN_MAX_CHARS = 1200
SPOKEN_PROMPT = """You are Trustify, talking to a university student who asked by voice. Your words will be read aloud by
text-to-speech right after the results appear on their screen.

Write 70 to 130 words in 4 to 7 short sentences:
1. Start with the verdict in plain words.
2. Name the most important warnings, with the real numbers: what was claimed and what the sources say.
3. End with the one to three things they should do or watch out for before acting.
Sound like a calm, friendly advisor. No lists, headings, markdown, emojis, or links. Write numbers the way you'd say
them, like "650 dollars a month" or "4.3 percent". Use only the facts below and don't add new ones. If one finding
confirms a number and another disputes the same number, say the sources disagree rather than calling it wrong.

{facts}"""


def _join_spoken(items: list[str]) -> str:
    return items[0] if len(items) == 1 else ", ".join(items[:-1]) + f", and {items[-1]}"


def _first_sentence(text: str | None, limit: int = 220) -> str:
    sentence = re.split(r"(?<=[.!?])\s+", " ".join(str(text or "").split()))[0]
    return sentence if len(sentence) <= limit else sentence[:limit].rsplit(" ", 1)[0] + "."


def clean_spoken(text: str, limit: int = SPOKEN_MAX_CHARS) -> str:
    """Text safe to read aloud: no reasoning tags, links, or markdown, and cut at a sentence end if too long."""
    text = re.sub(r"(?s)<think>.*?</think>", " ", text or "")
    text = re.sub(r"https?://\S+|www\.\S+", "", text)
    text = re.sub(r"[*_#`>|\[\]]", "", text)
    text = " ".join(text.split())
    if len(text) > limit:
        cut = max(text.rfind(". ", 0, limit), text.rfind("! ", 0, limit), text.rfind("? ", 0, limit))
        text = text[:cut + 1] if cut > 0 else text[:limit].rsplit(" ", 1)[0] + "."
    return text


def template_spoken_summary(payload: dict[str, Any]) -> str:
    """Plain spoken summary built from the results, used when no AI model is available."""
    counts = payload.get("counts") or {}
    parts = [SPOKEN_OPENERS.get(payload.get("overall"), "Here's what I found.")]
    tally = [f"{n} {one if n == 1 else many}" for n, one, many in (
        (counts.get("red_flag", 0), "red flag", "red flags"),
        (counts.get("caution", 0), "thing to be careful about", "things to be careful about"),
        (counts.get("ok", 0), "claim that checked out", "claims that checked out")) if n]
    if tally:
        parts.append(f"I checked {counts.get('total', 0)} things and found {_join_spoken(tally)}.")
    said: set[tuple[str, str]] = set()
    for f in payload.get("findings") or []:
        if f.get("status") not in ("red_flag", "caution") or len(said) == 3:
            continue
        d = f.get("data") or {}
        then = (d.get("figures") or {}).get("when_said")
        title = re.sub(r"^Web check:\s*", "", f.get("title") or "")
        if f.get("checker") == "statistic":
            title = title.split(":")[0]  # "Total nonfarm jobs: United States" reads better as "Total nonfarm jobs"
        if d.get("found"):
            detail = f"The sources say {d['found']}."
        elif then and d.get("claimed"):
            detail = f"It said {d['claimed']}, but official data showed {then['value']} for {then['period']}."
        else:
            detail = _first_sentence(f.get("summary"))
        if (title, detail) in said:
            continue
        said.add((title, detail))
        parts.append(f"{title}: {detail}")
    steps = (payload.get("action_checklist") or [])[:2]
    if steps:
        parts.append("Before you act: " + " ".join(steps))
    return clean_spoken(" ".join(parts))


def _spoken_facts(payload: dict[str, Any]) -> str:
    counts = payload.get("counts") or {}
    lines = [f"Verdict: {payload.get('overall')}", f"What it is: {payload.get('summary')}"]
    video = payload.get("video")
    if video:
        lines.append(f"Source: YouTube video \"{video.get('title')}\" by {video.get('channel')}, published {video.get('upload_date')}")
    lines.append(f"Counts: {counts.get('red_flag', 0)} red flags, {counts.get('caution', 0)} cautions, "
                 f"{counts.get('ok', 0)} checked out, {counts.get('unverified', 0)} unconfirmed")
    lines.append("Findings, most serious first:")
    for f in (payload.get("findings") or [])[:10]:
        d = f.get("data") or {}
        numbers = f" Claimed: {d['claimed']}. Sources say: {d['found']}." if d.get("found") else ""
        lines.append(f"- [{f.get('status_label')}] {f.get('title')}. Quote: \"{str(f.get('quote') or '')[:140]}\". "
                     f"{str(f.get('summary') or '')[:300]}{numbers}")
    if payload.get("action_checklist"):
        lines.append("Suggested next steps: " + " | ".join(payload["action_checklist"][:4]))
    return "\n".join(lines)


def spoken_summary(payload: dict[str, Any]) -> tuple[str, str]:
    """A short summary to read aloud. Returns (text, source) where source is "ai" or "template"."""
    if llm.available():
        try:
            message, _model = llm.chat_any(config.READ_MODELS, [{"role": "user", "content": SPOKEN_PROMPT.format(
                facts=_spoken_facts(payload))}], timeout=45)
            text = clean_spoken(message.get("content") or "")
            if len(text) >= 40:
                return text, "ai"
        except llm.LLMError:
            pass
    return template_spoken_summary(payload), "template"


def generate_checklist(context: str, overall: str, findings: list[Finding], is_video: bool = False) -> list[str]:
    """Generate 3-5 concrete, actionable steps a student can take on their phone."""
    has_red_flags = any(f.status == "red_flag" for f in findings)
    has_caution = any(f.status == "caution" for f in findings)
    has_zelle_etransfer = any("payment" in f.title.lower() or "zelle" in f.summary.lower() or "etransfer" in f.summary.lower() for f in findings)
    has_cannot_view = any("see it in person" in f.title.lower() or "mail" in f.summary.lower() for f in findings)

    steps: list[str] = []

    if is_video:
        if has_red_flags or has_caution:
            steps.append("Jump to the flagged timestamps and compare what was said with the official numbers above.")
        steps.append("Check the upload date: numbers that were right then may have changed since.")
        if context == "school":
            steps.append("Before choosing a school or major from a video, look up the same school on the College Scorecard yourself.")
        steps.append("Find a second source for any claim you plan to act on, especially ones we couldn't confirm.")
        steps.append("Be wary of links, promo codes, or courses the creator is selling in the description.")

    elif context == "housing":
        if has_red_flags or has_zelle_etransfer:
            steps.append("Never send a deposit, holding fee, or rent by Zelle, e-transfer, wire, or gift cards.")
        if has_cannot_view or has_red_flags:
            steps.append("Demand an in-person walkthrough or live interactive video call. If they refuse, walk away.")
        steps.append("Ask for their full legal name and check the property address on municipal rental licensing records.")
        steps.append("Reverse-image search all listing photos to see if they are copied from legitimate real estate sites.")
        steps.append("Remember: in Ontario and many jurisdictions, damage deposits are illegal—only first/last month is permitted.")

    elif context == "job":
        if has_red_flags:
            steps.append("Legitimate employers never charge candidates for training, background checks, or equipment kits.")
        steps.append("Look up the employer on the official corporate registry and verify the recruiter's email domain matches.")
        steps.append("Never deposit a check sent to you with instructions to wire or transfer a portion back to anyone.")
        steps.append("Do not provide your Social Insurance Number (SIN) or bank logins until an official written contract is verified.")

    elif context == "finance":
        steps.append("Never share your bank password, 2FA codes, or SIN/SSN over SMS, email, or unverified messaging apps.")
        steps.append("Contact the financial institution directly via the phone number printed on the back of your card.")
        steps.append("Guaranteed high-return offers or 'crypto investments' are almost always scams.")

    elif context == "school":
        steps.append("Verify the institution's official accreditation on the government education registry.")
        steps.append("Compare tuition, graduation rates, and median graduate debt using the College Scorecard.")
        steps.append("Reach out to current students or alumni on LinkedIn to confirm program reputation.")

    else:
        if has_red_flags:
            steps.append("Pause immediately. High-risk patterns were detected in this message.")
        steps.append("Never send untraceable funds to anyone you haven't verified in person.")
        steps.append("Verify claims against official consumer protection or government websites.")
        steps.append("When in doubt, show this to an adviser, student legal clinic, or housing advisor before committing.")

    return steps[:5]


def verify_text(text: str, seen_on_str: str | None = None, offline: bool = False) -> dict[str, Any]:
    """
    Run extraction and verification, returning a frontend-ready JSON dictionary.
    """
    # Parse seen_on date
    if seen_on_str:
        try:
            seen_on = date.fromisoformat(seen_on_str)
        except ValueError:
            seen_on = date.today()
    else:
        seen_on = date.today()

    video: dict[str, Any] | None = None
    seconds: dict[int, float | None] = {}
    try:
        if is_youtube_link(text):
            rep, video, seconds = check_youtube(text.strip(), seen_on if seen_on_str else None, offline)
        else:
            rep = router.run(text, seen_on, offline=offline)
    finally:
        db.close()

    return build_payload(rep, text, offline, video=video, seconds=seconds)


def check_youtube(url: str, seen_on: date | None, offline: bool) -> tuple[Report, dict[str, Any], dict[int, float | None]]:
    """Fetch the transcript and check the video. Returns the report, video details, and each finding's timestamp."""
    try:
        info, rep, timed = youtube.check_video(url, offline=offline, max_sections=VIDEO_MAX_SECTIONS,
                                               seen_on=seen_on, progress=lambda _msg: None)
    except ValueError as e:
        raise InputError(str(e)) from e
    except Exception as e:  # noqa: BLE001
        if type(e).__module__.startswith("youtube_transcript_api"):
            message = TRANSCRIPT_ERRORS.get(type(e).__name__, "Couldn't get this video's transcript. Paste the transcript text instead.")
            raise InputError(message) from e
        raise
    seconds = {id(t.finding): t.seconds for t in timed}
    return rep, video_details(info), seconds


def video_details(info: youtube.VideoInfo) -> dict[str, Any]:
    checked_until = info.checked_until or 0
    lines: list[dict[str, Any]] = []
    for seg in info.segments:
        if lines and len(lines[-1]["text"]) + len(seg.text) < TRANSCRIPT_LINE_CHARS and (seg.start < checked_until) == lines[-1]["checked"]:
            lines[-1]["text"] += " " + seg.text
        else:
            lines.append({"seconds": seg.start, "timestamp": youtube.timestamp(seg.start), "text": seg.text,
                          "checked": seg.start < checked_until})
    return {
        "id": info.video_id,
        "url": info.url,
        "title": info.title,
        "channel": info.channel,
        "upload_date": info.upload_date.isoformat() if info.upload_date else None,
        "language": info.language,
        "auto_captions": info.auto_captions,
        "thumbnail": f"https://i.ytimg.com/vi/{info.video_id}/hqdefault.jpg",
        "duration": info.duration,
        "duration_label": youtube.timestamp(info.duration),
        "sections_total": info.sections_total,
        "sections_checked": info.sections_checked,
        "checked_until": info.checked_until,
        "checked_until_label": youtube.timestamp(info.checked_until),
        "fully_checked": info.sections_checked >= info.sections_total,
        "transcript": lines,
    }


def build_payload(rep: Report, text: str, offline: bool = False, *, video: dict[str, Any] | None = None,
                  seconds: dict[int, float | None] | None = None) -> dict[str, Any]:
    """Shape a report into the frontend JSON contract and save it to history."""
    seconds = seconds or {}
    scan_id = f"chk_{uuid.uuid4().hex[:10]}"
    now_iso = dt.datetime.now(dt.timezone.utc).isoformat()

    ext = rep.extraction
    overall = rep.overall
    meta = OVERALL_META.get(overall, {"color": "gray", "message": "Verify details independently."})

    # Counts
    counts = {
        "red_flag": rep.count("red_flag"),
        "caution": rep.count("caution"),
        "ok": rep.count("ok"),
        "info": rep.count("info"),
        "unverified": rep.count("unverified"),
        "total": len(rep.findings),
    }

    # Format findings
    formatted_findings = []
    grouped = {
        "red_flags": [],
        "cautions": [],
        "ok": [],
        "context": [],
        "unverified": [],
    }

    sorted_findings = sorted(rep.findings, key=lambda f: (-SEVERITY.get(f.status, 0), f.item.id))

    for f in sorted_findings:
        color = STATUS_COLOR.get(f.status, "gray")
        status_label = TAGS.get(f.status, f.status.upper())

        evidence_items = []
        for ev in f.evidence:
            evidence_items.append({
                "source": ev.source,
                "detail": ev.detail,
                "kind": ev.kind,
                "kind_label": KIND_LABELS.get(ev.kind, ev.kind),
                "url": ev.url,
            })

        item_dict = {
            "id": f.item.id,
            "kind": f.item.kind,
            "status": f.status,
            "status_label": status_label,
            "color": color,
            "title": f.title,
            "quote": f.item.text or "",
            "summary": f.summary or "",
            "checker": f.checker,
            "evidence": evidence_items,
            "data": f.data,
            "seconds": seconds.get(id(f)),
            "timestamp": youtube.timestamp(seconds[id(f)]) if seconds.get(id(f)) is not None else None,
        }

        formatted_findings.append(item_dict)

        if f.status == "red_flag":
            grouped["red_flags"].append(item_dict)
        elif f.status == "caution":
            grouped["cautions"].append(item_dict)
        elif f.status == "ok":
            grouped["ok"].append(item_dict)
        elif f.status == "info":
            grouped["context"].append(item_dict)
        else:
            grouped["unverified"].append(item_dict)

    checklist = generate_checklist(ext.context, overall, rep.findings, is_video=video is not None)

    # Location info
    loc_dict = {
        "city": ext.location.city,
        "region": ext.location.region,
        "country": ext.location.country,
        "label": ext.location.label(),
    }

    payload = {
        "id": scan_id,
        "created_at": now_iso,
        "overall": overall,
        "overall_badge": {
            "label": overall,
            "color": meta["color"],
            "message": meta["message"],
        },
        "counts": counts,
        "summary": ext.summary or "No summary generated.",
        "context": ext.context,
        "location": loc_dict,
        "action_checklist": checklist,
        "findings": formatted_findings,
        "grouped_findings": grouped,
        "notes": rep.notes,
        "raw_report": {
            "parser": ext.parser,
            "said_on": ext.said_on.isoformat(),
            "items_count": len(ext.items),
        },
        "video": video,
    }

    # Persist to local history
    storage.save_scan(
        scan_id=scan_id,
        text=f"YouTube: {video['title'] or video['url']}" if video else text,
        context=ext.context,
        overall=overall,
        overall_color=meta["color"],
        findings_count=len(formatted_findings),
        payload=payload,
    )

    return payload


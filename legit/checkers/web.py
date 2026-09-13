"""Web fallback: one batched Groq browser-search call for everything official data couldn't settle.

Browser search is expensive (a single call can use 200k+ tokens), so all open questions go in one request."""
from __future__ import annotations

from .. import config, llm
from ..models import Evidence, Extraction, Finding, Item
from .common import domain_of

MAX_ITEMS = 6


def question(item: Item, ext: Extraction) -> str:
    d = item.data
    where = f" in {ext.location.label()}" if ext.location.label() else ""
    if item.kind == "entity":
        dom = domain_of(d.get("website")) or domain_of(d.get("email_domain"))
        extra = f" It uses the domain {dom}." if dom else ""
        return (f'Is "{d.get("name")}" a real, reputable {str(d.get("entity_type") or "organization").replace("_", " ")}{where}? '
                f"Look for official registration, reviews, and scam reports.{extra}")
    if item.kind == "price":
        beds = f" for a {d['bedrooms']}-bedroom" if d.get("bedrooms") is not None else ""
        return (f"Is {d.get('amount')} ({str(d.get('unit') or '').replace('_', ' ')}) a normal "
                f"{str(d.get('category') or 'price').replace('_', ' ')}{beds}{where}? Give the typical range.")
    if item.kind == "claim":
        return str(d.get("claim") or item.text)
    if item.kind == "school":
        school = d.get("school") or "this program"
        return (f'Check this claim about {school}: "{item.text}". Prefer official university, government, or '
                "statistics agency sources, and give the actual figure.")
    return item.text


def verify(items: list[Item], ext: Extraction) -> tuple[list[Finding], list[str]]:
    if not items:
        return [], []
    if not llm.available():
        return [], ["Web search skipped: no GROQ_API_KEY set."]
    batch = items[:MAX_ITEMS]
    notes = [f"Web search covered the first {MAX_ITEMS} unresolved items only."] if len(items) > MAX_ITEMS else []
    questions = "\n".join(f"{it.id}. {question(it, ext)}" for it in batch)
    prompt = f"""You are checking facts for a university student living on their own, who is deciding whether to trust this:
"{ext.summary or 'a message they received'}". Date seen: {ext.said_on}.

Search the web to answer each numbered question. Use at most 3 searches in total, and prefer official or
well-known sources (government sites, registries, major news, established review sites).

{questions}

After searching, reply with JSON only, in this shape:
{{"results": [{{"id": <number>, "verdict": "supported" | "contradicted" | "unclear",
  "answer": "one or two plain sentences", "sources": [{{"title": "...", "url": "https://..."}}]}}]}}
"supported" means the question's premise checks out (real organization, normal price, true claim).
"contradicted" means evidence shows it is false, fake, or abnormal. Use "unclear" when evidence is thin."""
    try:
        message, _model = llm.chat_any(config.SEARCH_MODELS, [{"role": "user", "content": prompt}],
                                       tools=[{"type": "browser_search"}], reasoning_effort="low", timeout=180, max_wait=0)
    except llm.RateLimited as e:
        wait = f" Try again in about {int(e.retry_after) + 1} seconds." if e.retry_after else ""
        return [], [f"Web search hit Groq's rate limit; a single browser search can use more than a free-tier "
                    f"day of tokens.{wait}"]
    except llm.LLMError as e:
        return [], [f"Web search failed: {e}"]

    data = llm.parse_json(message.get("content")) or {}
    fallback_sources = []
    for tool in message.get("executed_tools") or []:
        for r in ((tool.get("search_results") or {}).get("results") or [])[:3]:
            if r.get("url"):
                fallback_sources.append((r.get("title") or r["url"], r["url"]))

    by_id = {it.id: it for it in batch}
    findings: list[Finding] = []
    for r in data.get("results") or []:
        try:
            item = by_id.get(int(r.get("id")))
        except (TypeError, ValueError):
            continue
        if item is None:
            continue
        verdict = r.get("verdict")
        if verdict == "supported":
            status = "ok"
        elif verdict == "contradicted":
            status = "red_flag" if item.kind == "entity" else "caution"
        else:
            status = "unverified"
        sources = [(s.get("title") or s.get("url"), s.get("url")) for s in (r.get("sources") or []) if isinstance(s, dict) and s.get("url")]
        evidence = [Evidence(title, "Web source cited by the search", "web", url) for title, url in (sources or fallback_sources)[:3]]
        title = item.data.get("name") or item.data.get("claim") or item.text
        data = {"type": "web", "verdict": verdict, "question": question(item, ext),
                "sources": [{"title": e.source, "url": e.url} for e in evidence]}
        findings.append(Finding(item, status, f"Web check: {str(title)[:80]}", str(r.get("answer") or "").strip(), "web",
                                evidence, data=data))
    if not findings:
        notes.append("Web search returned no usable answer.")
    return findings, notes

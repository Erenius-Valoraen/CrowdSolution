"""
FastAPI REST API for CrowdSolution / Legit.
Transfers structured verification reports to the frontend in clean JSON.
"""
from __future__ import annotations

import os
from functools import lru_cache
from typing import Any

from pathlib import Path

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles

from legit import community, config, llm
from legit.checkers import web

from . import models, service, storage

# Initialize local scan storage
storage.init_storage()

app = FastAPI(
    title="Trustify API",
    description="Fact-checking and risk-rating API for university students. Checks rental listings, job offers, and claims.",
    version="2.1.0",
)

# Enable CORS for Next.js, Vite, React, mobile apps
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend"
app.mount("/static", StaticFiles(directory=FRONTEND_DIR), name="static")


@app.get("/", include_in_schema=False)
def web_app() -> FileResponse:
    """The Trustify web app."""
    return FileResponse(FRONTEND_DIR / "index.html")


@app.get("/favicon.ico", include_in_schema=False)
def favicon() -> Response:
    """The page sets an inline SVG icon; answer the browser's default request quietly."""
    return Response(status_code=204)


@app.get("/api")
def root() -> dict[str, str]:
    return {
        "name": "Trustify API",
        "version": "2.1.0",
        "status": "online",
        "docs_url": "/docs",
    }


@app.get("/api/health")
def health_check() -> dict[str, Any]:
    """Health check endpoint showing Groq API status and available models."""
    return {
        "status": "healthy",
        "groq_api_configured": llm.groq_available(),
        "snowflake_cortex_configured": llm.cortex_available(),
        "community_memory_configured": community.enabled(),
        "web_search_provider": web.provider(),
        "voice_input": llm.groq_available(),
        "voice_output_model": config.TTS_MODEL if llm.groq_available() else None,
        "default_extract_models": config.EXTRACT_MODELS,
        "search_models": config.SEARCH_MODELS,
    }


@app.post("/api/verify", response_model=models.VerifyResponse)
def verify_claim(req: models.VerifyRequest) -> dict[str, Any]:
    """
    Verify a listing, message, job offer, or claim.
    Returns complete structured JSON with overall risk rating, evidence, and actionable checklist.
    """
    if not req.text.strip():
        raise HTTPException(status_code=400, detail="Text cannot be empty.")

    try:
        response_data = service.verify_text(
            text=req.text,
            seen_on_str=req.seen_on,
            offline=req.offline,
        )
        return response_data
    except service.InputError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Verification failed: {str(e)}")


MAX_AUDIO_BYTES = 15 * 1024 * 1024  # about 15 minutes of browser-recorded speech; Groq accepts up to 25 MB
MIN_AUDIO_BYTES = 1000
VOICE_PROMPT = ("A university student asking whether something is legit: a rental listing, lease, job offer, bank "
                "message, tuition, or a college or major. Zelle, e-transfer, Interac, UT Austin, UCLA, MIT, College Scorecard.")


@app.post("/api/transcribe", response_model=models.TranscribeResponse)
async def transcribe_audio(request: Request) -> dict[str, str]:
    """
    Voice typing. Send the recording as the raw request body with its Content-Type (e.g. `audio/webm`).
    Returns the text so the frontend can put it in the textbox; nothing is checked or saved.
    """
    content_type = request.headers.get("content-type", "")
    if llm.audio_extension(content_type) is None:
        raise HTTPException(status_code=415, detail="Send the recording as webm, ogg, mp4/m4a, mp3, wav, or flac audio.")
    if int(request.headers.get("content-length") or 0) > MAX_AUDIO_BYTES:
        raise HTTPException(status_code=413, detail="That recording is too long. Keep it under a few minutes.")
    audio = await request.body()
    if len(audio) > MAX_AUDIO_BYTES:
        raise HTTPException(status_code=413, detail="That recording is too long. Keep it under a few minutes.")
    if len(audio) < MIN_AUDIO_BYTES:
        raise HTTPException(status_code=400, detail="No audio came through. Click the mic, speak, then click it again.")
    if not llm.groq_available():
        raise HTTPException(status_code=503, detail="Voice typing isn't set up on this server.")
    try:
        text, model = await run_in_threadpool(llm.transcribe, audio, content_type, prompt=VOICE_PROMPT)
    except llm.RateLimited:
        raise HTTPException(status_code=429, detail="Voice typing is busy right now. Try again in a minute, or type instead.")
    except llm.LLMError as e:
        raise HTTPException(status_code=502, detail=f"Couldn't turn that into text: {e}")
    if not text:
        raise HTTPException(status_code=422, detail="We didn't catch any words. Try again a little closer to the mic.")
    return {"text": text, "model": model}


@app.post("/api/scans/{scan_id}/spoken-summary", response_model=models.SpokenSummaryResponse)
def spoken_summary(scan_id: str) -> dict[str, str]:
    """
    A 70 to 130 word summary of a check's results, written to be read aloud: verdict, key warnings with numbers,
    and what to do. Saved with the scan, so asking again returns the same words.
    """
    data = storage.get_scan(scan_id)
    if not data:
        raise HTTPException(status_code=404, detail=f"Scan '{scan_id}' not found.")
    if data.get("spoken_summary"):
        return data["spoken_summary"]
    text, source = service.spoken_summary(data)
    result = {"text": text, "source": source}
    if source == "ai":  # the template is instant, so only cache AI-written summaries
        storage.update_payload(scan_id, dict(data, spoken_summary=result))
    return result


@lru_cache(maxsize=128)
def _speech(text: str) -> bytes:
    """Replays and repeated sentences don't cost another text-to-speech request."""
    return llm.speak(text)


@app.post("/api/speak", responses={200: {"content": {"audio/wav": {}}, "description": "WAV audio"}})
def speak(req: models.SpeakRequest) -> Response:
    """Read text aloud with Groq text-to-speech. Returns WAV audio, or 503 so the frontend can use the browser's voice."""
    if not llm.groq_available():
        raise HTTPException(status_code=503, detail="Natural voice isn't set up on this server.")
    try:
        audio = _speech(" ".join(req.text.split()))
    except llm.SpeechUnavailable:
        raise HTTPException(status_code=503, detail="Natural voice isn't enabled for this server's Groq account.")
    except llm.RateLimited:
        raise HTTPException(status_code=429, detail="The voice is busy right now. Try again in a minute.")
    except llm.LLMError as e:
        raise HTTPException(status_code=502, detail=f"Couldn't create audio: {e}")
    return Response(content=audio, media_type="audio/wav", headers={"Cache-Control": "private, max-age=3600"})


@app.get("/api/scans/{scan_id}", response_model=models.VerifyResponse)
def get_scan_by_id(scan_id: str) -> dict[str, Any]:
    """
    Retrieve a previously verified scan by its scan ID.
    Used for permalinks and shareable links (e.g., crowd.app/r/{scan_id}).
    """
    data = storage.get_scan(scan_id)
    if not data:
        raise HTTPException(status_code=404, detail=f"Scan '{scan_id}' not found.")
    return data


@app.get("/api/history", response_model=list[models.HistoryItem])
def get_history(
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
) -> list[dict[str, Any]]:
    """
    List recent verifications for user history and dashboard views.
    """
    return storage.list_scans(limit=limit, offset=offset)


@app.get("/api/examples", response_model=list[models.ExampleItem])
def get_sample_examples() -> list[dict[str, str]]:
    """
    Pre-configured examples for 1-click testing in frontend UI.
    """
    return [
        {
            "id": "ex_rental_scam",
            "title": "Rental Listing Scam (Zelle Deposit)",
            "category": "housing",
            "text": "Cozy 2BR near campus, $650/month. I am currently abroad, so please send the deposit by Zelle and I'll mail the keys.",
        },
        {
            "id": "ex_job_scam",
            "title": "Student Ambassador Job Scam (Upfront Fee)",
            "category": "job",
            "text": "Congratulations! You've been selected for our Campus Brand Ambassador program ($35/hr remote). A $150 training deposit is required for your starter materials.",
        },
        {
            "id": "ex_fake_check",
            "title": "Mystery Shopper / Fake Check Scam",
            "category": "finance",
            "text": "We will send you a check for $2,500. Deposit it, keep $400 for your commission, and send the remaining $2,100 back via Bitcoin or wire transfer within 24 hours.",
        },
        {
            "id": "ex_legit_sublet",
            "title": "Legitimate Waterloo Sublet Offer",
            "category": "housing",
            "text": "1 bedroom in a 5x5 apartment at 201 Lester St, Waterloo. $1,450/month including high-speed internet. In-person walkthrough available any weekday after 5 PM. Standard Ontario lease provided.",
        },
        {
            "id": "ex_youtube",
            "title": "YouTube Video (Jobs Report)",
            "category": "finance",
            "text": "https://www.youtube.com/watch?v=4sH30KUfPpM",
        },
        {
            "id": "ex_stat_claim",
            "title": "Economic Statistics Claim",
            "category": "finance",
            "text": "The US unemployment rate is currently 4.0% according to official labor data.",
        },
        {
            "id": "ex_college_claims",
            "title": "Reddit Comment About Colleges",
            "category": "school",
            "text": "Honestly UCLA is way better than UT Austin. It's even cheaper for out-of-state students and almost everyone graduates. And forget MIT, they only admit like 4% of people.",
        },
        {
            "id": "ex_majors",
            "title": "TikTok About Majors and Salaries",
            "category": "school",
            "text": "If you do CS at UT Austin you'll make six figures right out of school. Computer science majors make about $90,000 four years after graduating, while psychology majors barely make $40k.",
        },
        {
            "id": "ex_bank_phishing",
            "title": "Text From 'Your Bank'",
            "category": "finance",
            "text": "Chase Bank Student Offer: open a Chase High-Yield Student Savings account today and earn 12% APY, guaranteed. Limited spots! Verify your identity at chase-student-rewards.com with your online banking login.",
        },
    ]


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8000)


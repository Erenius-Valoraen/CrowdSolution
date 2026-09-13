"""
FastAPI REST API for CrowdSolution / Legit.
Transfers structured verification reports to the frontend in clean JSON.
"""
from __future__ import annotations

import os
from typing import Any

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware

from legit import config, llm

from . import models, service, storage

# Initialize local scan storage
storage.init_storage()

app = FastAPI(
    title="CrowdSolution Verification API",
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


@app.get("/")
def root() -> dict[str, str]:
    return {
        "name": "CrowdSolution Verification API",
        "version": "2.1.0",
        "status": "online",
        "docs_url": "/docs",
    }


@app.get("/api/health")
def health_check() -> dict[str, Any]:
    """Health check endpoint showing Groq API status and available models."""
    return {
        "status": "healthy",
        "groq_api_configured": llm.available(),
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
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Verification failed: {str(e)}")


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
            "id": "ex_stat_claim",
            "title": "Economic Statistics Claim",
            "category": "finance",
            "text": "The US unemployment rate is currently 4.0% according to official labor data.",
        },
    ]


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8000)


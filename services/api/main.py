"""
FastAPI Verification Server for UPSTREAM.
Provides CRUD endpoints for listing verification, receipt inspection,
local rent baselines, scam patterns, and peer-check flywheels.
"""
from __future__ import annotations

import os
from typing import Any

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from services.api import db
from services.api.verifier import run_verification

# Ensure database is initialized
db.init_db()

app = FastAPI(
    title="UPSTREAM Verification API",
    description="Backend server for claim provenance, rental scam detection, and local market baselines.",
    version="2.0.0",
)

# Enable CORS for frontend clients
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Request / Response Models ────────────────────────────────────────────────

class CheckRequest(BaseModel):
    text: str = Field(..., description="The listing text, job offer, or claim to verify.")
    kind: str = Field("rental", description="Artifact kind: rental, job, lease_clause, money_request, id_request.")
    price: float | None = Field(None, description="Optional stated price or monetary amount.")
    bedrooms: int = Field(1, description="Number of bedrooms if rental.")
    postal_prefix: str = Field("N2L", description="Postal prefix (e.g., N2L for Waterloo Northdale).")
    contact: str | None = Field(None, description="Contact email, phone, or handle mentioned in listing.")
    address: str | None = Field(None, description="Physical address mentioned.")
    entity_name: str | None = Field(None, description="Claimed landlord, company, or employer name.")
    url: str | None = Field(None, description="URL of the original listing or source.")


# ── API Endpoints ────────────────────────────────────────────────────────────

@app.get("/api/health")
def health_check() -> dict[str, Any]:
    """Health status and database inventory."""
    conn = db.get_connection()
    try:
        counts = {
            "scam_patterns": conn.execute("SELECT COUNT(*) FROM scam_patterns").fetchone()[0],
            "listings": conn.execute("SELECT COUNT(*) FROM listings").fetchone()[0],
            "local_baselines": conn.execute("SELECT COUNT(*) FROM local_baselines").fetchone()[0],
            "entities": conn.execute("SELECT COUNT(*) FROM entities").fetchone()[0],
            "receipts": conn.execute("SELECT COUNT(*) FROM receipts").fetchone()[0],
        }
        return {
            "status": "healthy",
            "database": str(db.DB_PATH),
            "counts": counts,
        }
    finally:
        conn.close()


@app.post("/api/check")
def check_artifact(req: CheckRequest) -> dict[str, Any]:
    """
    Ingest listing or claim, verify against database, format and return signed Receipt contract.
    """
    if not req.text.strip():
        raise HTTPException(status_code=400, detail="Text cannot be empty.")

    receipt_json = run_verification(
        text=req.text,
        kind=req.kind,
        price=req.price,
        bedrooms=req.bedrooms,
        postal_prefix=req.postal_prefix,
        contact=req.contact,
        address=req.address,
        entity_name=req.entity_name,
        url=req.url,
    )
    return receipt_json


@app.get("/api/receipts/{receipt_id}")
def get_receipt_by_id(receipt_id: str) -> dict[str, Any]:
    """
    Retrieve a signed receipt by receipt_id.
    """
    receipt = db.get_receipt(receipt_id)
    if not receipt:
        raise HTTPException(status_code=404, detail=f"Receipt '{receipt_id}' not found.")
    return receipt


@app.get("/api/receipts")
def list_recent_receipts(
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
) -> list[dict[str, Any]]:
    """
    Retrieve recent verification history.
    """
    return db.list_receipts(limit=limit, offset=offset)


@app.post("/api/receipts/{receipt_id}/recheck")
def recheck_receipt(receipt_id: str) -> dict[str, Any]:
    """
    Re-evaluate an existing receipt against updated server data.
    Enforces append-only rule: writes a new receipt version.
    """
    old_receipt = db.get_receipt(receipt_id)
    if not old_receipt:
        raise HTTPException(status_code=404, detail=f"Receipt '{receipt_id}' not found.")

    # Re-run verification using payload data
    price = old_receipt.get("incentive", {}).get("price_stated")
    postal = old_receipt.get("baseline", {}).get("postal_prefix", "N2L")
    bedrooms = old_receipt.get("baseline", {}).get("bedrooms", 1)

    # Use first claim or headline as text
    text = old_receipt.get("headline", "")
    for s in old_receipt.get("signals", []):
        text += " " + s.get("explanation", "")

    new_receipt = run_verification(
        text=text,
        price=price,
        bedrooms=bedrooms,
        postal_prefix=postal,
    )
    return new_receipt


@app.get("/api/baselines")
def get_baselines(
    postal_prefix: str | None = None,
    bedrooms: int | None = None,
) -> Any:
    """
    Query local rent baselines (median, p10, p90, sample size).
    """
    if postal_prefix:
        bd = bedrooms if bedrooms is not None else 1
        record = db.get_baseline(postal_prefix, bd)
        if not record:
            raise HTTPException(
                status_code=404,
                detail=f"No baseline data for postal prefix '{postal_prefix}' with {bd} bedroom(s).",
            )
        return record
    return db.list_all_baselines()


@app.get("/api/patterns")
def list_scam_patterns() -> list[dict[str, Any]]:
    """
    List known scam patterns and red-flag indicators from CAFC, FTC, and housing authorities.
    """
    return db.list_all_patterns()


@app.get("/api/flywheel/{content_sha256}")
def get_flywheel_stats(content_sha256: str) -> dict[str, Any]:
    """
    Get community peer-check stats: checks count, flagged count, first seen.
    """
    return db.get_flywheel_stats(content_sha256)


@app.get("/api/entities/{entity_name}")
def get_entity_info(entity_name: str) -> dict[str, Any]:
    """
    Look up landlord or corporate entity in official registration records.
    """
    record = db.lookup_entity(entity_name)
    if not record:
        raise HTTPException(status_code=404, detail=f"Entity '{entity_name}' not found in records.")
    return record


@app.get("/api/stats/{variable}")
def get_economic_stats(
    variable: str,
    date: str | None = None,
) -> list[dict[str, Any]]:
    """
    Retrieve economic indicators timeseries (unemployment, CPI, GDP) for statistical fact checks.
    """
    rows = db.get_economic_indicator(variable, date)
    if not rows:
        raise HTTPException(status_code=404, detail=f"No data found for indicator '{variable}'.")
    return rows


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8000)


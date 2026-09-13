"""
Embedded SQLite database manager for UPSTREAM.
Replaces external Snowflake database with an in-repo, zero-config relational store.

Rules enforced:
1. Append-only receipts: never UPDATE, never DELETE receipts.
2. Complete local datasets for verification (scam patterns, listings, baselines, entities).
"""
from __future__ import annotations

import json
import os
import sqlite3
from pathlib import Path
from typing import Any

DB_DIR = Path(__file__).resolve().parent / "data"
DEFAULT_DB_PATH = DB_DIR / "upstream.db"
DB_PATH = Path(os.environ.get("UPSTREAM_DB_PATH", str(DEFAULT_DB_PATH)))


def get_connection() -> sqlite3.Connection:
    """Get a connection with row factory enabled."""
    DB_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn


def init_db() -> None:
    """Initialize database tables according to PLAN.md schema."""
    conn = get_connection()
    try:
        with conn:
            conn.executescript("""
            CREATE TABLE IF NOT EXISTS raw_artifacts (
                artifact_id TEXT PRIMARY KEY,
                source_type TEXT NOT NULL,
                url TEXT,
                raw_content TEXT NOT NULL,
                content_sha256 TEXT NOT NULL,
                fetched_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS artifacts_parsed (
                artifact_id TEXT PRIMARY KEY,
                kind TEXT NOT NULL,
                title TEXT,
                body_text TEXT NOT NULL,
                price REAL,
                bedrooms INTEGER,
                postal_prefix TEXT,
                city TEXT,
                contact_email TEXT,
                contact_phone TEXT,
                entity_name TEXT,
                payment_method TEXT,
                payment_timing TEXT,
                parsed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (artifact_id) REFERENCES raw_artifacts(artifact_id)
            );

            CREATE TABLE IF NOT EXISTS listings (
                listing_id TEXT PRIMARY KEY,
                platform TEXT NOT NULL,
                url TEXT,
                title TEXT NOT NULL,
                body_text TEXT NOT NULL,
                address TEXT,
                postal_prefix TEXT,
                city TEXT,
                price REAL,
                bedrooms INTEGER,
                contact_email TEXT,
                contact_phone TEXT,
                image_hashes TEXT DEFAULT '[]',
                posted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS scam_patterns (
                pattern_id TEXT PRIMARY KEY,
                scam_type TEXT NOT NULL,
                pattern_name TEXT NOT NULL,
                description TEXT NOT NULL,
                keywords TEXT NOT NULL,       -- JSON array of keywords/phrases
                red_flags TEXT NOT NULL,      -- JSON array of red flag strings
                source TEXT NOT NULL,         -- CAFC | FTC | Reddit | University
                evidence_url TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS local_baselines (
                postal_prefix TEXT NOT NULL,
                bedrooms INTEGER NOT NULL,
                city TEXT NOT NULL,
                median_price REAL NOT NULL,
                p10_price REAL NOT NULL,
                p90_price REAL NOT NULL,
                sample_size INTEGER NOT NULL,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (postal_prefix, bedrooms)
            );

            CREATE TABLE IF NOT EXISTS entities (
                entity_key TEXT PRIMARY KEY,   -- lowercased normalized name or domain
                entity_name TEXT NOT NULL,
                entity_type TEXT NOT NULL,     -- landlord | property_mgmt | employer
                registered BOOLEAN NOT NULL,
                jurisdiction TEXT,
                incorporated_on TEXT,
                official_registry_url TEXT,
                notes TEXT
            );

            CREATE TABLE IF NOT EXISTS signals (
                signal_id TEXT PRIMARY KEY,
                receipt_id TEXT NOT NULL,
                artifact_id TEXT NOT NULL,
                analyzer TEXT NOT NULL,
                analyzer_version TEXT NOT NULL,
                subject_type TEXT NOT NULL,
                subject_id TEXT NOT NULL,
                direction TEXT NOT NULL,
                weight REAL NOT NULL,
                confidence REAL NOT NULL,
                explanation TEXT NOT NULL,
                evidence_json TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            -- APPEND ONLY. Never UPDATE, never DELETE.
            CREATE TABLE IF NOT EXISTS receipts (
                receipt_id TEXT PRIMARY KEY,
                artifact_id TEXT NOT NULL,
                content_sha256 TEXT NOT NULL,
                policy_version TEXT NOT NULL,
                verdict TEXT NOT NULL,
                headline TEXT NOT NULL,
                action_checklist TEXT NOT NULL, -- JSON array of strings
                payload TEXT NOT NULL,          -- Complete Receipt JSON contract
                receipt_sha256 TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE INDEX IF NOT EXISTS idx_receipts_hash ON receipts(content_sha256);
            CREATE INDEX IF NOT EXISTS idx_receipts_created ON receipts(created_at DESC);

            CREATE TABLE IF NOT EXISTS economic_indicators (
                variable TEXT NOT NULL,
                variable_name TEXT NOT NULL,
                frequency TEXT NOT NULL,
                unit TEXT NOT NULL,
                source TEXT NOT NULL,
                date TEXT NOT NULL,
                value REAL NOT NULL,
                published_date TEXT NOT NULL,
                PRIMARY KEY (variable, date)
            );
            """)
    finally:
        conn.close()


# ── Query Helpers ────────────────────────────────────────────────────────────

def save_artifact(artifact_id: str, source_type: str, raw_content: str, content_sha256: str, url: str | None = None) -> None:
    """Save raw ingested artifact."""
    conn = get_connection()
    try:
        with conn:
            conn.execute(
                """
                INSERT OR IGNORE INTO raw_artifacts (artifact_id, source_type, url, raw_content, content_sha256)
                VALUES (?, ?, ?, ?, ?)
                """,
                (artifact_id, source_type, url, raw_content, content_sha256),
            )
    finally:
        conn.close()


def save_receipt(receipt_data: dict[str, Any]) -> None:
    """
    Append a signed receipt into storage.
    Enforces append-only semantics.
    """
    conn = get_connection()
    try:
        with conn:
            conn.execute(
                """
                INSERT INTO receipts (
                    receipt_id, artifact_id, content_sha256, policy_version,
                    verdict, headline, action_checklist, payload, receipt_sha256, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    receipt_data["receipt_id"],
                    receipt_data["artifact_id"],
                    receipt_data.get("artifact_sha256", receipt_data.get("content_sha256", "")),
                    receipt_data["policy_version"],
                    receipt_data["verdict"],
                    receipt_data["headline"],
                    json.dumps(receipt_data["action_checklist"]),
                    json.dumps(receipt_data),
                    receipt_data["receipt_sha256"],
                    receipt_data.get("created_at"),
                ),
            )
            # Save associated signals
            for sig in receipt_data.get("signals", []):
                conn.execute(
                    """
                    INSERT INTO signals (
                        signal_id, receipt_id, artifact_id, analyzer,
                        analyzer_version, subject_type, subject_id, direction,
                        weight, confidence, explanation, evidence_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        sig["signal_id"],
                        receipt_data["receipt_id"],
                        receipt_data["artifact_id"],
                        sig["analyzer"],
                        sig["analyzer_version"],
                        sig["subject_type"],
                        sig["subject_id"],
                        sig["direction"],
                        sig["weight"],
                        sig["confidence"],
                        sig["explanation"],
                        json.dumps(sig["evidence"]),
                    ),
                )
    finally:
        conn.close()


def get_receipt(receipt_id: str) -> dict[str, Any] | None:
    """Fetch a receipt by receipt_id."""
    conn = get_connection()
    try:
        cur = conn.execute("SELECT payload FROM receipts WHERE receipt_id = ?", (receipt_id,))
        row = cur.fetchone()
        if row:
            return json.loads(row["payload"])
        return None
    finally:
        conn.close()


def list_receipts(limit: int = 20, offset: int = 0) -> list[dict[str, Any]]:
    """List recent receipts."""
    conn = get_connection()
    try:
        cur = conn.execute(
            """
            SELECT receipt_id, artifact_id, verdict, headline, created_at, receipt_sha256
            FROM receipts
            ORDER BY created_at DESC
            LIMIT ? OFFSET ?
            """,
            (limit, offset),
        )
        return [dict(r) for r in cur.fetchall()]
    finally:
        conn.close()


def get_flywheel_stats(content_sha256: str) -> dict[str, Any]:
    """
    Calculate community peer-checks flywheel:
    'X students checked this listing this week. Y marked it suspicious.'
    """
    conn = get_connection()
    try:
        cur = conn.execute(
            """
            SELECT COUNT(*) AS checks,
                   SUM(CASE WHEN verdict IN ('DO_NOT_PAY', 'UNVERIFIABLE_ENTITY') THEN 1 ELSE 0 END) AS flagged,
                   MIN(created_at) AS first_seen
            FROM receipts
            WHERE content_sha256 = ?
            """,
            (content_sha256,),
        )
        row = cur.fetchone()
        return {
            "checks": row["checks"] if row and row["checks"] is not None else 0,
            "flagged": row["flagged"] if row and row["flagged"] is not None else 0,
            "first_seen": row["first_seen"] if row else None,
        }
    finally:
        conn.close()


def find_matching_patterns(text: str) -> list[dict[str, Any]]:
    """Scan text against the scam-pattern corpus."""
    conn = get_connection()
    text_lower = text.lower()
    matches = []
    try:
        cur = conn.execute("SELECT * FROM scam_patterns")
        for row in cur.fetchall():
            keywords = json.loads(row["keywords"])
            hit_keywords = [kw for kw in keywords if kw.lower() in text_lower]
            if hit_keywords:
                pattern_dict = dict(row)
                pattern_dict["hit_keywords"] = hit_keywords
                pattern_dict["red_flags"] = json.loads(row["red_flags"])
                matches.append(pattern_dict)
        return matches
    finally:
        conn.close()


def find_duplicate_listings(
    title: str = "",
    body: str = "",
    price: float | None = None,
    contact: str | None = None,
) -> list[dict[str, Any]]:
    """
    Detect duplicate listings.
    Catches identical contact info, or similar text/title posted at other addresses/prices.
    """
    conn = get_connection()
    duplicates = []
    try:
        cur = conn.execute("SELECT * FROM listings")
        all_listings = cur.fetchall()
        for row in all_listings:
            r = dict(row)
            reasons = []

            # 1. Contact info reuse
            if contact and (
                (r["contact_email"] and contact.lower() in r["contact_email"].lower())
                or (r["contact_phone"] and contact in r["contact_phone"])
            ):
                reasons.append(f"Contact '{contact}' matches another listing at {r['address']}")

            # 2. Key phrases or title overlap
            if title and len(title) > 10 and title.lower() in r["title"].lower():
                reasons.append(f"Identical title posted at {r['address']} (${r['price']}/mo)")

            # 3. Substantial body overlap
            if body and len(body) > 30:
                words_body = set(body.lower().split())
                words_row = set(r["body_text"].lower().split())
                overlap = len(words_body.intersection(words_row)) / max(len(words_body), 1)
                if overlap > 0.65:
                    reasons.append(
                        f"Listing description has {int(overlap * 100)}% text overlap with {r['address']} (${r['price']}/mo)"
                    )

            if reasons:
                r["duplicate_reasons"] = reasons
                duplicates.append(r)
        return duplicates
    finally:
        conn.close()


def get_baseline(postal_prefix: str, bedrooms: int = 1) -> dict[str, Any] | None:
    """Retrieve local rent distribution for a postal prefix (e.g. N2L) and bedroom count."""
    conn = get_connection()
    try:
        cur = conn.execute(
            """
            SELECT * FROM local_baselines
            WHERE UPPER(postal_prefix) = UPPER(?) AND bedrooms = ?
            """,
            (postal_prefix, bedrooms),
        )
        row = cur.fetchone()
        if row:
            return dict(row)
        return None
    finally:
        conn.close()


def list_all_baselines() -> list[dict[str, Any]]:
    """Retrieve all local rent baselines."""
    conn = get_connection()
    try:
        cur = conn.execute("SELECT * FROM local_baselines ORDER BY city, postal_prefix, bedrooms")
        return [dict(r) for r in cur.fetchall()]
    finally:
        conn.close()


def list_all_patterns() -> list[dict[str, Any]]:
    """Retrieve all known scam patterns."""
    conn = get_connection()
    try:
        cur = conn.execute("SELECT * FROM scam_patterns ORDER BY scam_type, pattern_name")
        res = []
        for row in cur.fetchall():
            d = dict(row)
            d["keywords"] = json.loads(d["keywords"])
            d["red_flags"] = json.loads(d["red_flags"])
            res.append(d)
        return res
    finally:
        conn.close()


def lookup_entity(name_or_domain: str) -> dict[str, Any] | None:
    """Look up an entity in the registered entities directory."""
    conn = get_connection()
    key = name_or_domain.strip().lower()
    try:
        cur = conn.execute(
            """
            SELECT * FROM entities
            WHERE entity_key = ? OR entity_name LIKE ?
            LIMIT 1
            """,
            (key, f"%{key}%"),
        )
        row = cur.fetchone()
        if row:
            return dict(row)
        return None
    finally:
        conn.close()


def get_economic_indicator(variable: str, date: str | None = None) -> list[dict[str, Any]]:
    """Retrieve economic indicator timeseries point for statistical fact-checking."""
    conn = get_connection()
    try:
        if date:
            cur = conn.execute(
                """
                SELECT * FROM economic_indicators
                WHERE variable = ? AND date <= ?
                ORDER BY date DESC LIMIT 1
                """,
                (variable, date),
            )
        else:
            cur = conn.execute(
                """
                SELECT * FROM economic_indicators
                WHERE variable = ?
                ORDER BY date DESC LIMIT 10
                """,
                (variable,),
            )
        return [dict(r) for r in cur.fetchall()]
    finally:
        conn.close()


"""
Lightweight SQLite store for verification history and permalinks.
Enforces append-only storage for scan audits.
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

DB_PATH = Path(__file__).resolve().parent / "history.db"


def get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


def init_storage() -> None:
    conn = get_connection()
    try:
        with conn:
            conn.executescript("""
            CREATE TABLE IF NOT EXISTS scans (
                id TEXT PRIMARY KEY,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                text_snippet TEXT NOT NULL,
                context TEXT NOT NULL,
                overall TEXT NOT NULL,
                overall_color TEXT NOT NULL,
                findings_count INTEGER NOT NULL,
                payload_json TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_scans_created ON scans(created_at DESC);
            """)
    finally:
        conn.close()


def save_scan(
    scan_id: str,
    text: str,
    context: str,
    overall: str,
    overall_color: str,
    findings_count: int,
    payload: dict[str, Any],
) -> None:
    conn = get_connection()
    snippet = text[:120].strip() + ("..." if len(text) > 120 else "")
    try:
        with conn:
            conn.execute(
                """
                INSERT INTO scans (id, text_snippet, context, overall, overall_color, findings_count, payload_json)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (scan_id, snippet, context, overall, overall_color, findings_count, json.dumps(payload)),
            )
    finally:
        conn.close()


def update_payload(scan_id: str, payload: dict[str, Any]) -> None:
    """Replace a saved scan's payload, e.g. to cache its spoken summary. The check results themselves don't change."""
    conn = get_connection()
    try:
        with conn:
            conn.execute("UPDATE scans SET payload_json = ? WHERE id = ?", (json.dumps(payload), scan_id))
    finally:
        conn.close()


def get_scan(scan_id: str) -> dict[str, Any] | None:
    conn = get_connection()
    try:
        cur = conn.execute("SELECT payload_json FROM scans WHERE id = ?", (scan_id,))
        row = cur.fetchone()
        if row:
            return json.loads(row["payload_json"])
        return None
    finally:
        conn.close()


def list_scans(limit: int = 20, offset: int = 0) -> list[dict[str, Any]]:
    conn = get_connection()
    try:
        cur = conn.execute(
            """
            SELECT id, created_at, text_snippet, context, overall, overall_color, findings_count
            FROM scans
            ORDER BY created_at DESC
            LIMIT ? OFFSET ?
            """,
            (limit, offset),
        )
        return [dict(r) for r in cur.fetchall()]
    finally:
        conn.close()

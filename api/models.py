"""
Pydantic models for the Frontend JSON API.
Defines the clean, structured contract sent to the frontend.
"""
from __future__ import annotations

from typing import Any, Literal
from pydantic import BaseModel, Field


class VerifyRequest(BaseModel):
    """Request payload from frontend."""
    text: str = Field(..., description="The listing, job offer, message, or claim text to verify.", min_length=1)
    seen_on: str | None = Field(None, description="Date seen (YYYY-MM-DD), default is today.")
    offline: bool = Field(False, description="Web search is on by default. Set True to use only official data and scam patterns (faster, no web search tokens).")


class EvidenceItem(BaseModel):
    source: str
    detail: str
    kind: str
    kind_label: str
    url: str | None = None


class FindingItem(BaseModel):
    id: int
    kind: str
    status: Literal["red_flag", "caution", "unverified", "info", "ok"]
    status_label: str
    color: str
    title: str
    quote: str
    summary: str
    checker: str
    evidence: list[EvidenceItem] = []
    data: dict[str, Any] = {}


class GroupedFindings(BaseModel):
    red_flags: list[FindingItem] = []
    cautions: list[FindingItem] = []
    ok: list[FindingItem] = []
    context: list[FindingItem] = []
    unverified: list[FindingItem] = []


class OverallBadge(BaseModel):
    label: str
    color: str
    message: str


class ExtractionSummary(BaseModel):
    said_on: str
    context: str
    summary: str
    location_label: str
    parser: str


class VerifyResponse(BaseModel):
    """Clean JSON response tailored for frontend rendering."""
    id: str
    created_at: str
    overall: str
    overall_badge: OverallBadge
    counts: dict[str, int]
    summary: str
    context: str
    location: dict[str, str | None]
    action_checklist: list[str]
    findings: list[FindingItem]
    grouped_findings: GroupedFindings
    notes: list[str]
    raw_report: dict[str, Any]


class HistoryItem(BaseModel):
    id: str
    created_at: str
    text_snippet: str
    context: str
    overall: str
    overall_color: str
    findings_count: int


class ExampleItem(BaseModel):
    id: str
    title: str
    category: str
    text: str


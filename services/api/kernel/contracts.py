"""
UPSTREAM kernel contracts.

POST-PIVOT v2 — user is a university student living independently.
FROZEN. Changing anything in this file requires A announcing it out
loud and B + C acknowledging. This is the API between all three lanes.

Every analyzer returns List[Signal]. Nothing else. Ever.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import uuid
from dataclasses import asdict, dataclass, field
from typing import Any, Literal


def _now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


def _id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


SourceClass = Literal[
    "primary_research",
    "press_release",
    "news_report",
    "aggregator",
    "affiliate_content",
    "forum_ugc",
    "vendor_owned",
    "unknown",
]

Verdict = Literal[
    "DO_NOT_PAY",           # scam structure match, or duplicated across addresses
    "UNVERIFIABLE_ENTITY",  # this landlord/employer exists on no public record
    "RISKY_BUT_NORMAL",     # common arrangement — here is what to check
    "VERIFIED",             # entity confirmed, terms within local norms
    "INSUFFICIENT_DATA",    # we could not establish enough. a valid answer.
]

ArtifactKind = Literal[
    "rental", "job", "lease_clause", "money_request", "id_request", "other",
]


@dataclass
class Evidence:
    url: str
    quote: str = ""
    retrieved_at: str = field(default_factory=_now)
    source_class: SourceClass = "unknown"


@dataclass
class Document:
    doc_id: str
    artifact_id: str
    url: str | None
    domain: str | None
    clean_text: str
    source_type: str                       # which adapter produced this
    published_at: str | None = None
    meta: dict[str, Any] = field(default_factory=dict)


@dataclass
class Claim:
    claim_id: str
    artifact_id: str
    text: str
    claim_type: str = "factual"            # factual | causal | statistical | opinion
    checkability: float = 0.5              # 0..1
    cited_urls: list[str] = field(default_factory=list)


@dataclass
class Signal:
    """The ONLY thing an analyzer may return. Do not extend this."""

    signal_id: str
    analyzer: str
    analyzer_version: str
    subject_type: Literal["claim", "source", "artifact", "entity"]
    subject_id: str
    direction: Literal["supports", "undermines", "context"]
    weight: float                          # 0..1 magnitude
    confidence: float                      # 0..1 how sure the analyzer is
    explanation: str                       # ONE human sentence, rendered in UI
    evidence: list[Evidence] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not self.evidence:
            raise ValueError(
                f"{self.analyzer}: signal without evidence. "
                "Every number we show must be one tap from its source."
            )
        for name, v in (("weight", self.weight), ("confidence", self.confidence)):
            if not 0.0 <= v <= 1.0:
                raise ValueError(f"{self.analyzer}: {name}={v} outside 0..1")


@dataclass
class Receipt:
    receipt_id: str
    artifact_id: str
    policy_version: str
    verdict: Verdict
    headline: str                          # one sentence, shown large
    action_checklist: list[str]            # ← what she does BEFORE she pays.
                                           #   the most important field we emit.
    claims: list[Claim]
    signals: list[Signal]
    provenance_graph: dict[str, Any]       # {"nodes": [...], "edges": [...]}
    independence: dict[str, Any]           # {duplicates found, addresses, prices}
    incentive: dict[str, Any]              # {who asks for money, how, when}
    baseline: dict[str, Any]               # {local median, percentile, n}
    peer_checks: dict[str, Any]            # {checks, flagged, first_seen}
    what_would_change_this: list[str]
    created_at: str = field(default_factory=_now)
    receipt_sha256: str = ""

    def sign(self) -> "Receipt":
        body = asdict(self)
        body.pop("receipt_sha256", None)
        blob = json.dumps(body, sort_keys=True, separators=(",", ":"), default=str)
        self.receipt_sha256 = hashlib.sha256(blob.encode()).hexdigest()
        return self

    def to_json(self) -> dict[str, Any]:
        """The single contract the frontend reads."""
        return asdict(self)


# ── constructors ────────────────────────────────────────────────────────────

def new_signal(**kw: Any) -> Signal:
    kw.setdefault("signal_id", _id("sig"))
    kw.setdefault("analyzer_version", "v1")
    return Signal(**kw)


def new_claim(**kw: Any) -> Claim:
    kw.setdefault("claim_id", _id("clm"))
    return Claim(**kw)


def new_document(**kw: Any) -> Document:
    kw.setdefault("doc_id", _id("doc"))
    return Document(**kw)


def new_receipt(**kw: Any) -> Receipt:
    kw.setdefault("receipt_id", _id("rcp"))
    kw.setdefault("policy_version", "policy-v1")
    return Receipt(**kw)

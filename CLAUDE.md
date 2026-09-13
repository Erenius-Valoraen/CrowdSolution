# UPSTREAM — invariants

## What this is

A claim provenance engine. Input: any artifact (url, text, reviews, AI answer,
image). Output: a signed, versioned Receipt tracing each claim to its origin,
measuring how many of its sources are genuinely independent, and mapping who
profits if you believe it.

## The one rule

**We do not score truth. We trace chain of custody.**

Never emit a "trust score" as the primary output. Never claim a statement is true
or false. We report provenance, independence, incentive, and coordination — every
one of them backed by a clickable link.

Verdicts are classifications, not judgements:
`ORPHAN CLAIM` · `SINGLE SOURCE` · `WELL CORROBORATED` · `INSUFFICIENT DATA`

## Architecture law

Three layers. Changes may ONLY touch `adapters/` and `analyzers/`.

```
adapters/    artifact -> Document        (add freely)
kernel/      Document -> Receipt         (FROZEN — A only)
analyzers/   Document -> List[Signal]    (add freely)
```

If a task seems to require editing `kernel/`, it is the wrong task.
Write a new analyzer instead.

## Non-negotiables

1. Every analyzer returns `List[Signal]`. No exceptions, no new shapes.
2. Storage is append-only. Never UPDATE, never DELETE. Re-running an artifact
   writes a NEW receipt version. This gives us diff-over-time for free.
3. Every Signal carries at least one Evidence item with a real URL.
   A signal with no evidence is a bug, not a signal. Enforced at construction.
4. Scoring weights live in `policy.yaml`. Never hardcode a weight in Python.
5. `DEMO_MODE=true` must replay from `fixtures/` with zero network calls.
   Any change that breaks DEMO_MODE is reverted immediately.
6. Confidence is always explicit. "Unknown" is a valid, shippable answer.

## Ownership

```
A  services/api/kernel/ analyzers/ adapters/ policy.yaml CLAUDE.md README.md
B  services/api/snowflake/ snowflake/ scripts/ evals/ fixtures/ + AWS console
C  apps/web/ (everything)
```

About to edit a file outside your lane? Stop and ask the owner. Every time.

## Style

- Python 3.11, FastAPI, async. No Celery, no Redis, no ORM, no auth.
- Frontend reads ONE JSON contract. Presentation changes never touch backend.
- Snowflake is the system of record. Fixtures are for demo only.
- Mobile-first, `md:` breakpoints for desktop. One codebase, not two.

## Change protocol

1. `git worktree add ../upstream-<name>` — the live version stays live.
2. Classify the change in one sentence: new adapter? new analyzer?
   `policy.yaml` edit?
3. If it is none of those three, stop and re-read it. It almost always is.
4. Run `evals/run_evals.py` against the golden set before merging.
5. Merge to `main` within 45 minutes. Never hold a branch longer.

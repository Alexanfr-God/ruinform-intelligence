# RUINFORM Intelligence

RUINFORM Intelligence is the AI core behind **RUINFORM — an operating system for matter**.

Its mission is to understand physical objects from evidence, discover valuable future forms, test those ideas against engineering reality, guide a human through a real build, verify the result, and preserve the object's transformation history.

## Core loop

`SEE → UNDERSTAND → IMAGINE → ENGINEER → BUILD → VERIFY → OWN → REVALUE`

## Current build

**RFM-INT-0002.1 — Critic Loop + Visual Brief**

The invention path is now:

`TRUSTED PROJECT STATE → FORM ARCHITECT → CANDIDATE POOL → FEASIBILITY CRITIC → BOUNDED REVISION → PASS → RANKING → VISUAL BRIEF`

Form Architect generates a broad internal pool. Feasibility Critic reviews every candidate. Promising candidates marked `revise` may go through a bounded revision loop and are reviewed again. `reject` never becomes visible to the user, and a candidate that still has `revise` status after the allowed rounds is not silently promoted.

Only passed futures receive a renderer-facing Visual Brief. That brief carries material identity, provenance cues, camera/composition direction, unresolved physical unknowns, and a deterministic forbidden-invention list so visual generation cannot quietly turn unknown properties into apparent facts.

A photorealistic render remains a proposal, not physical evidence.

## Local run

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e '.[dev]'
uvicorn ruinform_intelligence.server:app --reload
```

The runtime expects the model API credential to be configured as a server environment secret. Never commit credentials to the repository.

Health check:

```bash
curl http://127.0.0.1:8000/health
```

### 1. Inspect matter

`POST /v1/material-eye/analyze`

### 2. Continue evidence loop

`POST /v1/evidence-loop/continue`

### 3. Discover future forms

`POST /v1/futures/generate`

The future-forms endpoint accepts a contract-valid `ProjectState`, optional user intent, preference weights for originality, artistic impact, usefulness, ease and value, plus a bounded revision-round setting.

## Repository map

- `src/ruinform_intelligence/` — executable AI core and API
- `prompts/` — agent instructions, versioned separately from code
- `evals/` — regression cases and benchmarks
- `docs/` — architecture, build records, decisions, failures and roadmap
- `tests/` — deterministic software tests

## Philosophy

A beautiful render is not a successful object. The physical result is the truth.

See `docs/INTELLIGENCE_CONSTITUTION.md` before changing agent behavior.

# RUINFORM Intelligence

RUINFORM Intelligence is the AI core behind **RUINFORM — an operating system for matter**.

Its mission is to understand physical objects from evidence, discover valuable future forms, test those ideas against engineering reality, guide a human through a real build, verify the result, and preserve the object's transformation history.

## Core loop

`SEE → UNDERSTAND → IMAGINE → ENGINEER → BUILD → VERIFY → OWN → REVALUE`

## Current build

**RFM-INT-0002 — Form Architect + Feasibility Critic**

The first real invention pipeline now exists:

`TRUSTED PROJECT STATE → FORM ARCHITECT → INTERNAL CANDIDATE POOL → FEASIBILITY CRITIC → RANKING → TOP FUTURES`

Form Architect generates a broad internal set of materially honest future forms. Feasibility Critic reviews every candidate against the known matter, tools, skills and constraints, then rejects or revises weak ideas. Only candidates marked `pass` can be exposed to the user.

User preferences can shift ranking toward originality, artistic impact, usefulness, ease, or value without overriding the physical feasibility gates.

The current pipeline deliberately returns fewer than three visible futures if fewer than three concepts pass review. It never fills missing slots with weak ideas just to make the UI look complete.

## Local run

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e '.[dev]'
export OPENAI_API_KEY='...'
uvicorn ruinform_intelligence.server:app --reload
```

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

The future-forms endpoint accepts a contract-valid `ProjectState`, optional user intent, and preference weights for originality, artistic impact, usefulness, ease and value.

Never commit API keys. `.env.example` contains names only.

## Repository map

- `src/ruinform_intelligence/` — executable AI core and API
- `prompts/` — agent instructions, versioned separately from code
- `evals/` — regression cases and benchmarks
- `docs/` — architecture, build records, decisions, failures and roadmap
- `tests/` — deterministic software tests

## Philosophy

A beautiful render is not a successful object. The physical result is the truth.

See `docs/INTELLIGENCE_CONSTITUTION.md` before changing agent behavior.

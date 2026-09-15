# RUINFORM Intelligence

RUINFORM Intelligence is the AI core behind **RUINFORM — an operating system for matter**.

Its mission is to understand physical objects from evidence, discover valuable future forms, test those ideas against engineering reality, guide a human through a real build, verify the result, and preserve the object's transformation history.

## Core loop

`SEE → UNDERSTAND → IMAGINE → ENGINEER → RENDER → BUILD → VERIFY → OWN → REVALUE`

## Current build

**RFM-INT-0002.3 — First Live Transformation**

The product path is now persistent and callable:

`SOURCE IMAGES → MATERIAL EYE → EVIDENCE LOOP → FUTURE DISCOVERY → USER CHOICE → HIGGSFIELD RENDER → RENDER TRUST GATE → ACCEPTED FUTURE`

Transformation sessions preserve `ProjectState`, future candidates, selected candidate, render attempts, critique results, and the accepted image. A session can stop for missing evidence and resume later without pretending that the conversation itself is physical truth.

The Higgsfield adapter uses source-image references and an asynchronous generation lifecycle. The renderer remains an execution tool: only feasibility-approved futures can be rendered, and only renders that survive the visual trust gate are accepted.

A photorealistic render remains a proposal, not physical evidence.

## Local run

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e '.[dev]'
uvicorn ruinform_intelligence.server:app --reload
```

Runtime credentials belong in server environment secrets. Never commit them to the repository.

Health check:

```bash
curl http://127.0.0.1:8000/health
```

### Modular endpoints

- `POST /v1/material-eye/analyze`
- `POST /v1/evidence-loop/continue`
- `POST /v1/futures/generate`
- `POST /v1/renders/prepare`
- `POST /v1/renders/review`

### Persistent live transformation endpoints

- `POST /v1/live-transformations/start`
- `GET /v1/live-transformations/{session_id}`
- `POST /v1/live-transformations/{session_id}/evidence`
- `POST /v1/live-transformations/{session_id}/futures`
- `POST /v1/live-transformations/{session_id}/render/{candidate_id}`

For the prototype, persistent sessions use SQLite. The storage boundary is intentionally isolated so a production datastore can replace it as the workflow scales.

## Container run

```bash
docker build -t ruinform-intelligence .
docker run --rm -p 8000:8000 --env-file .env ruinform-intelligence
```

## Repository map

- `src/ruinform_intelligence/` — executable AI core and API
- `prompts/` — agent instructions, versioned separately from code
- `evals/` — regression cases and benchmarks
- `docs/` — architecture, build records, decisions, failures and roadmap
- `tests/` — deterministic software tests

## Philosophy

A beautiful render is not a successful object. The physical result is the truth.

See `docs/INTELLIGENCE_CONSTITUTION.md` before changing agent behavior.

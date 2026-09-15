# RUINFORM Intelligence

RUINFORM Intelligence is the AI core behind **RUINFORM — an operating system for matter**.

Its mission is to understand physical objects from evidence, discover valuable future forms, test those ideas against engineering reality, guide a human through a real build, verify the result, and preserve the object's transformation history.

## Core loop

`SEE → UNDERSTAND → IMAGINE → ENGINEER → BUILD → VERIFY → OWN → REVALUE`

## Current build

**RFM-INT-0001.1 — Real Material Eye**

The first live intelligence path now exists:

`IMAGE(S) → MATERIAL EYE → PROJECT STATE → EVIDENCE GATE → FOLLOW-UP REQUEST`

The system separates facts, hypotheses and unknowns, links observations back to image evidence, and blocks ideation while high-consequence physical unknowns remain unresolved.

No design concept is allowed to outrun the evidence.

## Local run

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e '.[dev]'
export OPENAI_API_KEY='...'
uvicorn ruinform_intelligence.api:app --reload
```

Health check:

```bash
curl http://127.0.0.1:8000/health
```

Material inspection:

```bash
curl -X POST http://127.0.0.1:8000/v1/material-eye/analyze \
  -H 'Content-Type: application/json' \
  -d '{
    "image_urls": ["https://example.com/object.jpg"],
    "user_context": "Found in my workshop. I want to reuse it.",
    "constraints": {"tools_available": ["scissors", "drill"]}
  }'
```

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

# RUINFORM Intelligence

RUINFORM Intelligence is the AI core behind **RUINFORM — an operating system for matter**.

Its mission is to understand physical objects from evidence, discover valuable future forms, test those ideas against engineering reality, guide a human through a real build, verify the result, and preserve the object's transformation history.

## Core loop

`SEE → UNDERSTAND → IMAGINE → ENGINEER → RENDER → BUILD → VERIFY → OWN → REVALUE`

## Current build

**RFM-INT-0002.2 — Render Gateway + Render Trust Gate**

The current invention path is:

`TRUSTED PROJECT STATE → FORM ARCHITECT → FEASIBILITY CRITIC → BOUNDED REVISION → TOP FUTURES → VISUAL BRIEF → RENDER REQUEST → RENDER REVIEW → PASS / REGENERATE`

The renderer is treated as an execution tool, not as a source of physical truth. Each approved future carries its source-material image references into the render request. Generated images are reviewed against the approved Visual Brief and source evidence before they can be shown as accepted future forms.

The deterministic Render Trust Gate can override an optimistic model review when visual fidelity is too low, source-material identity is lost, invention risk is too high, or a blocking violation is present.

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

### 4. Prepare a render

`POST /v1/renders/prepare`

Returns the provider-neutral `RenderRequest`: prompt, negative constraints, source image references, candidate ID and aspect ratio. A Higgsfield adapter can consume this request without owning product reasoning.

### 5. Review a generated render

`POST /v1/renders/review`

Accepts the approved future, exact render request and generated image URL. The multimodal review is followed by a deterministic trust gate before returning `pass`, `regenerate`, or `reject`.

## Repository map

- `src/ruinform_intelligence/` — executable AI core and API
- `prompts/` — agent instructions, versioned separately from code
- `evals/` — regression cases and benchmarks
- `docs/` — architecture, build records, decisions, failures and roadmap
- `tests/` — deterministic software tests

## Philosophy

A beautiful render is not a successful object. The physical result is the truth.

See `docs/INTELLIGENCE_CONSTITUTION.md` before changing agent behavior.

# RUINFORM Intelligence

RUINFORM Intelligence is the AI core behind **RUINFORM — an operating system for matter**.

Its mission is to understand physical objects from evidence, discover valuable future forms, test those ideas against engineering reality, guide a human through a real build, verify the result, and preserve the object's transformation history.

## Core loop

`SEE → UNDERSTAND → IMAGINE → ENGINEER → BUILD → VERIFY → OWN → REVALUE`

## Current build

**RFM-INT-0001 — Material Intelligence**

The first build deliberately solves one narrow problem well: given evidence about physical objects, create a structured project state that separates facts, hypotheses, unknowns, confidence, and required follow-up evidence.

No design concept is allowed to outrun the evidence.

## Repository map

- `src/ruinform_intelligence/` — executable AI core
- `schemas/` — machine-readable contracts for project state and evidence
- `prompts/` — agent instructions, versioned separately from code
- `evals/` — regression cases and benchmarks
- `docs/` — architecture, build records, decisions, failures and roadmap
- `tests/` — deterministic software tests

## Philosophy

A beautiful render is not a successful object. The physical result is the truth.

See `docs/INTELLIGENCE_CONSTITUTION.md` before changing agent behavior.

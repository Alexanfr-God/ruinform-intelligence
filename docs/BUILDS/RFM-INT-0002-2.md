# RFM-INT-0002.2 — Render Gateway + Render Trust Gate

## Goal

Turn an approved RUINFORM future form into a visual concept without allowing the renderer to silently rewrite the physical truth.

## Pipeline

`VISUAL BRIEF → RENDER REQUEST → RENDER PROVIDER → RENDER REVIEW → PASS / REGENERATE / REJECT`

A passed render may be shown to the user. A failed render is not promoted merely because it looks attractive.

## Added

- provider-neutral `RenderProvider` protocol
- deterministic render prompt compiler
- source-evidence image references carried into every render request
- multimodal render review agent
- deterministic visual trust thresholds after the model review
- bounded regeneration loop (default: 3 attempts)
- render attempt lineage for later learning/evals
- `/v1/renders/prepare`
- `/v1/renders/review`

## Visual trust dimensions

- brief fidelity
- source-material fidelity
- provenance visibility
- geometry consistency
- invention risk (lower is better)

The deterministic gate currently requires:

- brief fidelity >= 78
- source-material fidelity >= 72
- invention risk <= 25
- zero blocking violations

These thresholds are initial engineering defaults, not product truth. They must be tuned from real builds and evals.

## Provider boundary

RUINFORM Intelligence does not hard-code a renderer vendor. The intelligence layer exposes a small `RenderProvider` contract. A Higgsfield adapter can satisfy that contract while preserving the same review and retry logic. This lets us compare renderers later without rewriting THE MAKER.

## Important non-goal

A generated image is still a concept visualization. Passing the Render Trust Gate does not prove dimensions, strength, safety, manufacturing correctness, or structural performance.

## Learning record

Every attempt preserves:

- exact render request
- provider output and job id
- visual review
- regeneration instructions
- final accepted or failed result

This becomes training/eval material for learning which prompts, renderers and visual constraints best preserve real source matter.

## Next

RFM-INT-0002.3 should connect a real rendering adapter, run the first end-to-end image generation from actual user material, and persist render attempts in project storage rather than returning them only in memory.

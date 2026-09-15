# RFM-INT-0002 — Form Architect + Feasibility Critic

## Goal

Give RUINFORM its first real invention loop: discover many possible future forms internally, then expose only ideas that survive physical critique.

## Pipeline

`TRUSTED PROJECT STATE → FORM ARCHITECT → CANDIDATE POOL → FEASIBILITY CRITIC → RANKING → TOP FUTURES`

## Added

- `Form Architect` specialist with strict structured output.
- Internal candidate pool targeting roughly 12 distinct future forms.
- Source-material allocation by exact material item IDs.
- Explicit added materials, tools, operations and unresolved dependencies.
- `Feasibility Critic` specialist reviewing every candidate exactly once.
- Pass / revise / reject statuses.
- Separate scores for feasibility, material fit, buildability, originality, artistic impact, usefulness and value potential.
- Deterministic ranking that combines physical quality with user preferences.
- User preference controls for originality, artistic impact, usefulness, ease and value.
- `only_use_owned_materials` constraint.
- API endpoint `POST /v1/futures/generate`.
- Regression tests for invalid material references, ranking behavior and rejection filtering.

## Important design rule

The visible user experience is not a raw brainstorm. RUINFORM may consider many futures internally, but only candidates that pass critique are eligible to be shown.

If fewer than three candidates pass, the system returns fewer than three and marks `needs_regeneration=true`. It does not fill the UI with weak concepts.

## Current limitation

This build performs one generation pass and one critic pass. It does not yet automatically send rejected or revise-status concepts back to Form Architect for repair. It also produces semantic concepts, not final rendered images.

## Next build

**RFM-INT-0002.1 — Critic Loop + Visual Brief**

Add automatic candidate repair/regeneration until three strong futures survive, then produce a render-ready visual brief for each selected future. This becomes the bridge to Higgsfield image generation and the cinematic `FINDING THE FORM INSIDE THE MATTER` reveal.

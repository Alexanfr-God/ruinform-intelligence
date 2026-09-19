# RFM-INT-0019 — PRE-RENDER MEMORY CRITIC

## Goal

Move Wave 3 from retrieval-only memory toward retrieval + self-critique before paid image rendering.

## Changes

- Relax source participation: strongest coherent subset beats forced 100% coverage.
- Add a Memory Influence Cap so retrieved examples teach operators/warnings rather than dictating silhouettes, categories, or mechanisms.
- Strengthen four-future diversity: no more than two mechanism-driven directions by default, at least one no-motion direction, and less repetition of tension/balance/light families.
- Reuse Feasibility Critic as a second, low-reasoning pre-render gate over all four preview concepts.
- Pass the compact Wave 3 retrieval trace into the critic so it can detect memory overfit.
- Add standardized pre-render warning tags such as `FORCED_SOURCE_PARTICIPATION`, `MECHANISM_CREEP`, `REQUIRES_TOO_MUCH_CRAFT_SKILL`, `BACKGROUND_DEPENDENCY`, `MEMORY_OVERFIT`, and `CONCEPT_FAMILY_DUPLICATE`.
- Stop using raw source-count coverage as the preview quality signal. Critic `material_fit_score` now represents necessity, provenance, economy, and coherence.
- Rank preview concepts using critic feasibility, material fit, originality, artistic impact, buildability, value, usefulness, and gate status.
- Critic failure is non-fatal: Studio still returns the four Design Brain concepts with fallback scoring.
- Persist the pre-render critic trace inside the existing Wave 3 retrieval trace for later inspection and Idea Room snapshots.

## Product lesson from the pedal-cycle / umbrella test

A good interaction lesson improved `Pedal Eclipse`, but the batch also revealed two failure modes:

1. source participation pressure forced leather and chain into concepts that did not need them;
2. several futures converged on mechanism / tension / balance behavior.

Wave 3 must remember without becoming a template machine. Current source geometry remains the highest authority.

## Expected test

Generate a fresh 3–4 object project with `RUINFORM decides`.

Pass condition:

- at least one future intentionally omits a weak source when appropriate;
- the four futures span meaningfully different operator families;
- critic warnings appear inside the saved future data before rendering;
- an over-engineered idea is downgraded to `revise` or `reject` rather than receiving a high rank solely because it uses every source;
- concept generation remains available if the critic call fails.
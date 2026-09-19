# RFM-INT-0022 — Retriever v2

## Why

Retriever v1 expanded every matched synonym group into all of its terms, then counted those synthetic terms as separate overlaps. A single generic material cue such as `metal` could therefore behave like many matches (`steel`, `wire`, `rod`, `bolt`, `nut`, `washer`, etc.). The result was unbounded-looking relevance values such as `184.25` and weak memories receiving too much influence.

## Contract

Retriever v2 remains deterministic and inspectable. It does not add embeddings yet.

Each memory match is split into bounded evidence channels:

- exact source terms
- source-family match
- material / geometry behavior
- transformation operator
- explicit direction / intent
- difficulty

Semantic families are counted once per channel. They are never exploded into multiple synonym hits.

The final match score is normalized to `0–100` and measures retrieval relevance only, never idea quality.

## Guardrails

- Human Eval memory requires a minimum normalized match plus a strong signal from exact source, source family, or explicit operator.
- At most one strongest relevant example is retrieved from each of SUCCESS / MIXED / FAIL.
- Shortlisted / unjudged ideas use a higher match threshold than human-rated examples and remain capped at two.
- Archived ideas remain excluded.
- Conditional lessons are triggered by user/context intent, not merely because a source object is capable of movement or interaction.
- Current source photographs and explicit Creative Direction always outrank memory.

## Trace

`retrieval_trace` now records:

- `version = wave3_retriever_v2`
- `strategy = deterministic_field_aware_normalized`
- query source families / behaviors / operators
- normalized match score for Taste, Eval and Shortlist rows
- human-readable match reasons
- per-channel score components

## Regression case

The tricycle + chain + brown sheet offcuts + umbrella project must no longer allow a generic metal-heavy memory to produce an enormous relevance score simply because the v1 synonym graph expanded `metal` into many hardware words.

Expected behavior:

- every displayed memory score is within 0–100
- generic metal-only memories fall below the retrieval floor unless there is a genuine source/operator match
- interaction lessons do not trigger merely because a tricycle or umbrella can move
- relevant source-family memories can still be retrieved without requiring exact object names

## Wave 3 acceptance test

After deployment, run one fresh concept generation with the same four source photographs and the same controls used for the 0021 validation. Do not render images.

Inspect `IDEA ROOM -> newest batch -> WAVE 3 / MEMORY ROUTER`.

Acceptance:

1. Router shows `wave3_retriever_v2`.
2. No Eval or Shortlist match exceeds 100.
3. The old `UNCOILING WOMAN 180.25` style inflation is gone.
4. Selected memories have defensible source/operator relevance.
5. Final four concepts still satisfy the 0021 self-healing gate: no REJECT after one bounded pass, ideally 3–4 PASS.

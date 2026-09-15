# RFM-INT-0002.1 — Critic Loop + Visual Brief

Goal: turn one-pass ideation into a bounded design-review loop and produce a renderer-safe visual contract for concepts that survive.

## Why this build exists

A single pass from design to critique is not enough. Promising ideas should be revised when the critic finds a fixable flaw; weak ideas should be rejected; only defensible concepts should reach visualization.

## Added

- bounded Architect → Critic → Revision loop
- explicit revision lineage per candidate
- deterministic stopping rules
- no silent promotion of `revise` or `reject` to `pass`
- generation of structured Visual Briefs only for passed futures
- renderer constraints that separate known physical facts from artistic interpretation
- explicit unresolved-property handling so visual generation cannot silently resolve unknowns
- regression tests for renderer evidence boundaries

## Runtime target

`TRUSTED MATTER → CANDIDATES → CRITIC → REVISE → CRITIC → PASS → VISUAL BRIEF`

The renderer remains downstream. A photorealistic image must never become a new source of physical truth.

## Next

Connect Visual Briefs to a rendering tool and create a render-evaluation loop that checks source-material identity, silhouette fidelity, provenance visibility, and forbidden invention violations before any image reaches the user.

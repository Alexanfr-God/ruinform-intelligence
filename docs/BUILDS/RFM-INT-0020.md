# RFM-INT-0020 — DIVERSITY + CRITIC CONTRACT

## Goal

Make Wave 3 useful before paid rendering: four futures should represent different ways of thinking, Critic scores must use one stable scale, and weak concepts must be visibly gated before image-generation tokens are spent.

## Triggering test

Source matter: pink three-wheeled cycle + umbrella + leather scraps + chain.

RFM-INT-0019 improved source economy, but the batch still revealed four defects:

1. three of four concepts kept forcing most source items together;
2. the umbrella dominated most concepts and repeated the same source role;
3. several futures were variations of mechanism / tension behavior rather than genuinely different operators;
4. Critic scores drifted to values such as 3/5 despite the product contract being 0–100, and its verdict was not explicit in the Studio UI.

## Changes

### Design Brain batch diversity

- Require at least three genuinely different transformation families across four futures.
- Category names do not count as diversity.
- At least one concept must work without a moving mechanism unless the user explicitly requests motion.
- No more than two concepts should share a dominant mechanism family.
- When three or more sources are available, vary the source subsets and avoid making one obvious object the hero of all four futures.
- Add a final side-by-side batch self-check before structured output.

### Critic contract

- Mandate a 0–100 integer scale for all seven Critic score fields.
- Add explicit score anchors and state that `5` means 5/100, not 5/5.
- Add `SOURCE_ROLE_REPETITION` alongside existing Wave 3 failure tags.
- Strengthen batch-level comparison for repeated mechanism/operator/source roles.
- Normalize obvious accidental 1–5 or 1–10 model scoring to 0–100 as a defensive server-side repair and record that normalization in the audit reasons.

### Source economy

- Stop fallback scoring from using percentage of source items included as `material_fit_score`.
- Treat source coverage as an audit fact only, never as a quality reward.

### Studio pre-render gate

Each concept card now shows a dedicated pre-render Critic panel:

- `PASS` — normal render path;
- `REVISE` — user must explicitly acknowledge the warning before spending a render;
- `REJECT` — render is blocked and no image-generation request is sent.

The Studio also exposes Critic failure tags and actionable required changes before the render button.

## Expected A/B test

Use exactly the same four source images and settings as the triggering test:

- Difficulty: MEDIUM
- Creative Direction: RUINFORM decides
- Creative Mode: HYBRID
- Background: RUINFORM WORLD
- Session Adjustment: empty

Generate four concepts only.

Pass conditions:

- scores appear on the 0–100 scale;
- every card visibly shows PASS / REVISE / REJECT;
- REJECT has no paid render path;
- REVISE requires explicit acknowledgement;
- at least one future can omit weak source items;
- the four futures show meaningfully different transformation families and source roles;
- the same obvious source does not automatically dominate the full batch.

## Next

After this contract is stable, move to Retriever v2. The next known defect is inflated lexical relevance (for example an unrelated prior evaluation receiving an implausibly high similarity score), which should be fixed independently so retrieval quality can be measured without mixing it with Critic behavior.

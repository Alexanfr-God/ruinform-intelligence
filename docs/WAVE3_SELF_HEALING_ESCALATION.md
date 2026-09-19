# RFM-INT-0021.2 — Self-Healing Escalation

The first production audit of the bounded self-healing pass proved that the pipeline works, but exposed a policy weakness: some concepts enter the repair stage as `REVISE` even when their failure profile is severe enough that preserving the original core wastes the only repair pass.

Observed production case:

- `Weather Scar`: REVISE -> PASS. Repair was the right action.
- `Rear-Up Valet`: REVISE -> REJECT. The original core should have been replaced rather than preserved.
- `Weather Drum`: REVISE -> REVISE. The repair did not remove the critical failure modes.

0021.2 keeps the one-pass budget, but changes the action selector:

- light/moderate REVISE -> `revise`
- severe REVISE -> `replace`
- REJECT -> `replace`

A severe REVISE is one where preserving the current mechanism is likely to waste the single repair opportunity. The selector uses critic evidence rather than category/name heuristics.

Escalation signals:

- `LOW_PHYSICAL_CREDIBILITY` + `MECHANISM_NOT_VISUALLY_READABLE`
- three or more distinct critic failure tags
- feasibility score below 55
- buildability score below 50
- `MECHANISM_CREEP` combined with `WEAK_SIGNATURE_GESTURE` or `MECHANISM_NOT_VISUALLY_READABLE`

Replacement instructions are also stronger: the model must abandon the current concept thesis, silhouette, mechanism recipe, and source-role pattern rather than cosmetically simplifying the same idea.

The budget remains bounded: each flagged slot receives exactly one text-only repair/replacement generation and one second critic review. There is still no recursive repair loop and no image generation during self-healing.

# RFM-INT-0023 — BUILD MASTER V1

Status: implementation candidate

## Why this build exists

Wave 3 now reliably produces and filters concepts before paid image generation. The next stage must not mix design ideation with engineering. `MAKE IT REAL` therefore becomes a separate post-approval pipeline.

Pipeline:

`APPROVED FUTURE → APPROVED RENDER → BUILD MASTER V1 → ENGINEERING CRITIC → optional one repair → BUILD HANDOFF`

Detailed engineering is generated only after the user explicitly approves a rendered visual.

## Build Master v1 contract

The plan separates four kinds of information instead of flattening them into confident prose:

1. `known_facts` — facts supported by project state/evidence.
2. `measurements_required` — real-world geometry that must be measured before dependent steps.
3. `engineering_assumptions` — low-risk provisional assumptions, clearly labeled as assumptions.
4. build instructions — materials, tools, sequence, stop conditions, safety gates and final verification.

Unknown source dimensions must use measure-to-fit logic. A generated image is not measurement evidence.

A deterministic validation layer rejects numeric physical dimensions/ratings that appear in the plan but not in the project state.

## Engineering Critic

After Build Master drafts the plan, Engineering Critic audits:

- evidence grounding
- physical credibility
- sequence quality
- approved-render fidelity
- materials/tools completeness
- safety completeness

Statuses:

- `PASS` — release the build sequence.
- `REVISE` — run exactly one text-only Build Master repair, then critic again.
- `BLOCK` — do not auto-repair; new evidence or a changed physical premise is required.

Standard issue tags include:

- `INVENTED_DIMENSION`
- `MISSING_MEASUREMENT`
- `HIDDEN_ASSUMPTION`
- `SOURCE_ID_ERROR`
- `MISSING_TOOL_OR_PART`
- `SEQUENCE_ERROR`
- `LOW_PHYSICAL_CREDIBILITY`
- `UNVERIFIED_LOAD`
- `VISUAL_DRIFT`
- `OVERENGINEERED`
- `SAFETY_GATE_MISSING`
- `UNSUPPORTED_MATERIAL_PROPERTY`

No recursive engineering loop is allowed.

## Studio behavior

`MAKE IT REAL` now shows:

- approved visual / build target
- Engineering Critic status and scores
- bounded revision audit
- WHAT WE KNOW
- ENGINEERING ASSUMPTIONS
- MEASURE BEFORE CUTTING
- shopping list
- tools
- substitute options
- preflight
- build sequence only if final engineering status is PASS
- safety gates
- unresolved-before-use list
- final visual/physical verification

If the final Engineering Critic status is `REVISE` or `BLOCK`, Studio suppresses the step-by-step execution sequence rather than presenting an unapproved plan as ready to build.

## Backward compatibility

Stored v0.2 BuildPlan payloads are upgraded on read with empty v1 evidence fields and `plan_version=legacy_v0_2`. Old sessions remain readable.

A new concept generation or a new render invalidates any previous build plan/review so a stale plan cannot be attached to a different approved image.

## Acceptance test

Use one already-approved render whose selected future is `PASS`.

1. Press `MAKE IT REAL`.
2. Confirm the Build page displays `BUILD MASTER V1`.
3. Confirm `ENGINEERING CRITIC / PASS|REVISE|BLOCK` is visible.
4. Confirm `WHAT WE KNOW` does not contain guessed source dimensions.
5. Confirm unknown geometry appears under `MEASURE BEFORE CUTTING` with an explanation of what it controls.
6. Confirm any `REVISE` shows the one-pass revision audit.
7. Confirm `BLOCK` or final `REVISE` hides the execution steps.
8. Confirm a `PASS` exposes a concise step sequence with per-step `Verify` and `Stop if` checks.
9. Confirm the approved render remains visible as the build target.

RFM-INT-0023 passes when the system can turn an approved visual into a grounded handoff without inventing measurements or releasing a plan that its own Engineering Critic has not passed.

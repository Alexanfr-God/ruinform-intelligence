# RFM-INT-0024 — Evidence Request / Resume Build

Status target: post-0023 MAKE IT REAL continuation.

## Problem

RFM-INT-0023 correctly suppresses build execution when the final Engineering Critic verdict is `REVISE` or `BLOCK`, but the user is left with a technical report and no direct route to add the missing real-world evidence.

The product should not force a new project, a new concept batch, or a new image render just because engineering needs a wall fact, mass, clearance, condition check, or workshop photo.

## Pipeline

```text
APPROVED FUTURE + APPROVED RENDER
        ↓
BUILD MASTER
        ↓
ENGINEERING CRITIC
        ↓
PASS ───────────────→ release execution
REVISE / BLOCK
        ↓
EVIDENCE REQUEST
        ↓
user measurement / inspection / photo
        ↓
resume SAME candidate + SAME approved render
        ↓
new bounded Build Master → Critic round
```

Each resumed round still has the 0023 contract: at most one automatic plan repair. Evidence rounds are not recursive critic loops.

## Build evidence request

For a non-PASS final engineering review, RUINFORM derives up to five concrete workshop tasks from:

- final `blocking_unknowns`
- evidence-oriented critic tags such as `UNVERIFIED_LOAD`, `MISSING_MEASUREMENT`, `HIDDEN_ASSUMPTION`, and `UNSUPPORTED_MATERIAL_PROPERTY`
- the Build Plan's real `measurements_required`
- mounting context, which can request an evidence photo

Pure plan defects such as `SEQUENCE_ERROR` are not falsely converted into fake measurements.

## Evidence submission

The Studio page now exposes:

`ADD EVIDENCE → RESUME BUILD`

A user may supply:

- measured or inspected text findings
- numeric measurements with units
- JPEG / PNG / WebP evidence photos up to 8 MB

Evidence is stored in `ProjectState.evidence` with a candidate-scoped property key:

```text
build:<candidate_id>:<property_key>
```

This preserves the audit trail while preventing evidence for one future from contaminating another candidate in the same project.

## Image evidence

Build Master and Engineering Critic receive the approved render first and candidate-scoped workshop evidence photos after it. Prompts explicitly forbid inferring hidden structure, dimensions, material grade, or load ratings from appearance alone.

## Resume behavior

The evidence route:

1. verifies the same approved render is still active;
2. requires at least one real answer or photo;
3. appends candidate-scoped evidence;
4. resumes the same approved future and render;
5. runs one fresh bounded Build Master → Engineering Critic round;
6. records a build-evidence round marker in the project evidence trail.

A hard cap of six evidence-resume rounds prevents the workflow from degenerating into an endless loop.

## Acceptance test

Use the existing `Chainbound Index` approved render that ended RFM-INT-0023 in final `REVISE`.

Expected UI:

- existing Engineering Critic remains visible;
- `RFM-INT-0024 / EVIDENCE REQUEST` appears before the engineering detail;
- tasks should include mounting/load-related facts and/or relevant M-measurements;
- no new concept generation or image render is required;
- submitting at least one real fact resumes the same build;
- new result may be `PASS`, `REVISE`, or `BLOCK` based on the added evidence;
- execution is released only on final `PASS`.

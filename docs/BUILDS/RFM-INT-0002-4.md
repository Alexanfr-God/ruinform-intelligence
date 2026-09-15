# RFM-INT-0002.4 — Evidence Dialogue + Founder Lab Continuation

## Goal

Turn the private founder lab from a one-shot Material Eye demo into a persistent evidence conversation that can continue through the evidence gate and into future-form discovery.

## Product hypothesis

A trustworthy physical AI should not stop after saying that evidence is missing. It should ask for the missing evidence and give the user several ways to supply it: a quick categorical answer, a precise written answer, a structured measurement, or another photograph.

## Changes

- The first Material Eye analysis is now persisted as a `TransformationSession`.
- Blocked projects render an Evidence Dialogue directly in the browser.
- Every unknown can be answered with suggested choices or a custom answer.
- Users can submit exact measurements using `property = number unit` lines; these become structured measurement evidence.
- Users can add corrections, descriptions, and up to four follow-up photographs per turn.
- Each evidence turn runs `continue_evidence_loop`, reconciles against prior state, records claim history, and re-evaluates the evidence gate.
- Once the gate opens, the lab exposes Future Discovery with simple preference controls.
- Approved futures are shown with feasibility/material/buildability/originality/value scores and can be sent to the existing render pipeline.
- Form Architect, Feasibility Critic, Revision Architect, Visual Brief, and Render Critic now use the deployment-safe prompt loader so the full path works on Render.

## Reliability rules preserved

- User answers are evidence, not automatic truth.
- Measurements are kept distinct from free-form statements.
- Unknowns remain unknown when the user selects `not sure`.
- Future generation is still blocked by the deterministic Evidence Gate.
- Only feasibility-passed candidates receive Visual Briefs.
- Render acceptance still passes through the Render Critic.

## Known next risk

The private lab currently stores uploaded source photographs as data URLs so OpenAI can inspect them without a separate storage service. Higgsfield reference-image support may require externally reachable image URLs rather than data URLs. If live rendering rejects these references, the next build should add a private object-storage upload adapter (R2/S3) and use signed or scoped URLs for renderer references.

## Regression coverage

Added tests for:

- dimension unknowns offering a measurement path;
- material unknowns offering useful categorical choices;
- combining quick and custom answers;
- parsing structured measurements;
- rejecting malformed measurement lines.

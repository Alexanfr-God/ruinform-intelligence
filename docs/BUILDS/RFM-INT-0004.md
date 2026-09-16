# RFM-INT-0004 — Preview → Render → Build

## Goal
Stop spending expensive reasoning before the user has chosen an idea. The product should first show desirable future forms, then render only the selected concept, then generate fabrication guidance only after the user accepts the visual direction.

## Product flow
1. Existing Material Eye creates a durable project state.
2. `/studio/{session_id}` runs one Concept Architect call and returns exactly four concept previews.
3. No detailed feasibility critic, revision loop, visual brief, or build plan is generated at preview time.
4. The user selects one concept.
5. Visual Director creates the visual brief and Higgsfield render only for that concept. Existing render critic remains the trust gate for the image.
6. Only after the user selects `MAKE IT REAL` does Build Master create the post-production build plan.

## Why
The previous pipeline generated many candidates and critique passes before the user knew whether the creative direction was interesting. That increased latency and token spend and made the UI appear frozen.

## Trust boundary
Preview scores are directional UX hints, not engineering approval. Missing ordinary dimensions may use scale-to-fit assumptions. Electrical, thermal, load-bearing, pressure, chemical, structural, and regulatory unknowns remain unverified until the build stage.

## Success criteria
- First visible concepts require one reasoning call after Material Eye.
- Four distinct concepts are shown.
- Higgsfield is called only after the user selects a concept.
- Build Master is called only after a render is accepted.
- Existing Postgres session durability is preserved.

# RFM-INT-0002.7 — Fast Concept Discovery

## Problem

The first live Concept Mode test reached the future-discovery stage but the browser appeared to hang for minutes. No Higgsfield request was visible because the synchronous pipeline was still performing multiple OpenAI reasoning calls before the user had even selected a concept.

The previous sequence could include:

1. Form Architect
2. batched Feasibility Critic
3. several revision + re-critique calls
4. three sequential Visual Brief calls
5. only then show the three futures

This is correct as an offline quality pipeline, but wrong for the first interactive product loop.

## Change

Concept Mode now uses a low-latency discovery path:

`Form Architect → batched Feasibility Critic → visible futures`

Visual Brief generation is deferred until the user selects `RENDER THIS FUTURE`. The render trust gate remains unchanged.

Verified Mode keeps the deeper revision pipeline.

## Product rule

The user should never wait for renderer preparation for concepts they may never select.

## Observability

Server logs now mark Concept Mode discovery and render phases so a long-running external model call can be located without guessing.

## Expected impact

- substantially fewer OpenAI calls before the futures screen;
- faster first WOW moment;
- Higgsfield is called only after a user chooses a future, which is intentional;
- Visual Brief and Render Critic still protect the renderer boundary.

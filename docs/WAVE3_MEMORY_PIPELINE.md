# RUINFORM Wave 3 — Two-Stage Memory

Wave 3 separates generated thinking from judged learning.

## Pipeline

```text
SOURCE MATTER
    ↓
GENERATE 4 FUTURES
    ↓
IDEA ROOM
    ↓
SELECT + RENDER
    ↓
REVIEW INBOX
    ↓
HUMAN EVALUATION
    ↓
SUCCESS / MIXED / FAIL
    ↓
EVAL LIBRARY
    ↓
WAVE 3 RETRIEVAL
```

## Idea Room

Route: `/studio/ideas`

Purpose: no paid concept generation should disappear just because the user rendered a different candidate or generated another set.

Each batch freezes:
- source item names and IDs;
- Creative Direction;
- difficulty and background controls;
- all four candidate concepts;
- model preview scores and reviews;
- shortlist state;
- which candidates were later rendered.

The room is **generated memory**, not yet truth. Model scores are retained for context but do not become training labels until a human judges the result.

## Review Inbox

Route: `/studio/reviews`

Purpose: no approved image generation should disappear before human evaluation.

Every approved render is frozen with the concept, source set and render snapshot. It remains PENDING until a human saves an evaluation.

Important implementation detail: GPT Image may return a large `data:` URL. Never place the full render URL in a PostgreSQL btree index. Matching uses the small `(session_id, candidate_id)` index and compares render URL only after narrowing the rows.

## Eval Library

Route: `/studio/evals`

This is **learned memory**. Only human-rated examples reach this layer.

Labels:
- SUCCESS
- MIXED
- FAIL

The next retrieval layer should use all three groups: successes provide positive patterns, mixed cases provide boundary conditions, and failures provide explicit warnings.

## Product principle

**Generated work is not disposable. Human judgment is what turns generated work into learning.**

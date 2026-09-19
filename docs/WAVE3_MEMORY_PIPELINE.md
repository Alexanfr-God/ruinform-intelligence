# RUINFORM Wave 3 — Two-Stage Memory

Wave 3 separates generated thinking from judged learning.

## Pipeline

```text
SOURCE MATTER
    ↓
MEMORY ROUTER
    ↓
2-4 TASTE CARDS + RELEVANT EVALS + CONDITIONAL LESSONS + SHORTLISTED HYPOTHESES
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

## Memory Router

Wave 3 must not send the whole growing memory library to Design Brain.

For each new concept request it builds a small context pack from the current source matter, Material Eye labels/observations, Creative Direction, difficulty and creative mode.

The v1 pack contains:
- normally 3 Taste Library cards, hard-limited to 2-4;
- at most one relevant SUCCESS, MIXED and FAIL human evaluation;
- conditional lessons whose retrieval cues match the current project;
- at most two relevant SHORTLISTED ideas.

Current source photographs and explicit user direction always outrank retrieved memory.

The v1 selector is deterministic and inspectable. This is deliberate: with ten curated cards we value debuggability over opaque semantic ranking. When the library grows to dozens/hundreds of cards, embeddings can be added behind the same retrieval contract.

Each generated four-future batch persists a `retrieval_trace`, visible in Idea Room, so we can inspect exactly which memories influenced that generation.

## Idea Room

Route: `/studio/ideas`

Purpose: no paid concept generation should disappear just because the user rendered a different candidate or generated another set.

Each batch freezes:
- source item names and IDs;
- Creative Direction;
- difficulty and background controls;
- all four candidate concepts;
- model preview scores and reviews;
- retrieval trace;
- shortlist state;
- which candidates were later rendered.

The room is **generated memory**, not yet truth. Model scores are retained for context but do not become training labels until a human judges the result.

### Shortlist

`SHORTLIST THIS IDEA` means: *this unrendered/generated concept is interesting enough to keep available as a future hypothesis.*

A shortlisted concept may be retrieved for a later similar project, but it is explicitly labelled **UNJUDGED**. It must never be treated as a SUCCESS until a human renders and evaluates it.

### Archive

`ARCHIVE THIS BATCH` means: keep the batch as historical record, but remove its shortlisted concepts from active retrieval. Archive is cold storage, not deletion.

### Rendered

When a candidate is actually rendered, the Idea Room marks that candidate and its batch as rendered. The image then enters Review Inbox separately.

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

Retrieval uses all three groups: successes provide positive patterns, mixed cases provide boundary conditions, and failures provide explicit warnings.

## Product principle

**Generated work is not disposable. Human judgment is what turns generated work into learning.**

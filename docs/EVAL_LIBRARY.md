# RUINFORM Eval Library — Wave 2

## Purpose

Taste Library answers:

> What does strong RUINFORM design look like?

Eval Library answers:

> What happened when RUINFORM tried, what worked, what failed, and what should the next system learn from it?

The two libraries serve different purposes and should not be merged.

## Record unit

One EvalRecord represents one concrete rendered concept at one moment in project history.

It snapshots:

- source item names and IDs
- Creative Direction
- difficulty mode
- background mode
- selected concept
- concept review
- accepted render
- human outcome: SUCCESS / MIXED / FAIL
- idea score
- WOW score
- physical credibility
- source participation
- collectible quality
- would keep/build: YES / MAYBE / NO
- failure tags
- GOOD notes
- BAD notes

Later project edits or re-renders must not mutate an existing evaluation.

## Storage

Production uses the existing Render PostgreSQL connection through `DATABASE_URL` / `RUINFORM_DATABASE_URL`.

Local development uses the same SQLite file as the session store unless a separate database path is configured.

Table: `evaluation_records`

The full structured record is preserved as JSON while a small number of fields are promoted to indexed SQL columns for filtering.

## Human feedback UX

After an approved render, Studio appends a compact `TEACH RUINFORM` panel.

The user classifies the result and scores it using 1–5 controls. Failure tags are optional and intentionally coarse.

Current failure tags:

- too_diy
- too_complex
- requires_too_much_craft_skill
- overdesigned
- weak_idea
- too_many_added_parts
- bad_render
- lost_source
- weak_signature_gesture
- low_physical_credibility
- world_rescues_object
- other

`requires_too_much_craft_skill` is intentionally separate from `too_complex`: a concept may be mechanically simple but still demand professional sculptural, welding, sewing, finishing, or other craft skill that conflicts with RUINFORM's achievable-WOW goal.

`overdesigned` captures a different failure: the concept may work, but it spends too much fabrication, detail, or authored complexity to produce the visual payoff. This supports the emerging RUINFORM rule: maximize visual leverage — preserve most of the impact with much less craft.

The goal is low-friction structured feedback, not a long design critique.

## Library views

`/studio/evals`

Filters:

- ALL
- SUCCESS
- MIXED
- FAIL

Keeping all outcomes in one dataset matters. A mixed concept may contain a strong idea but weak rendering or weak physics; throwing it into a generic failure bucket would destroy that signal.

## Wave 3 handoff

Wave 3 will retrieve a small relevant memory pack rather than dump the whole history into Design Brain.

Target retrieval packet:

- 2–4 relevant Taste Library operators
- 1–2 relevant Eval Library successes
- 1–2 relevant Eval Library warnings/failures
- only the distilled Wave 3 lessons whose retrieval cues match the current source set and concept direction

This makes the system learn from prior attempts without fine-tuning and without turning the prompt into an ever-growing history dump.

Distilled reusable lessons live in:

`docs/WAVE3_RETRIEVAL_LESSONS.md`

Important: these lessons are **conditional memory**, not permanent prompt bloat. A lesson should influence Design Brain only when the current materials, intended interaction, or failure pattern make it relevant.

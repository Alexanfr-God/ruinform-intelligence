# RFM-INT-0002.5 — Concept Mode + Persistent Evidence Drafts

## Why this build exists

Live founder testing exposed a product failure: the Evidence Dialogue could become exhausting before a user ever reached the creative payoff. A user may not know exact dimensions, material subtype, electrical ratings, or hidden condition — and requiring every answer turns RUINFORM into an inspection form instead of an intelligent maker.

The second failure was UX trust: if a submission failed or the user navigated back, typed answers could disappear from the form even though the project state itself was persistent.

## Product decision

RUINFORM now has two explicit paths:

- **Verified Path** — evidence gate remains strict. High-consequence unknowns block future discovery.
- **Concept Mode** — user explicitly acknowledges incomplete evidence and asks THE MAKER to explore anyway. Unknowns remain unknown, assumptions are marked as assumptions, and any PASS means only acceptable for concept visualization — never approval to build or use.

Concept Mode does not weaken the global Evidence Gate. It is an explicit session-level override with a recorded acknowledgement and notice version.

## UX changes

- Show at most five evidence questions first, ranked by consequence.
- Collapse remaining questions under an optional-details disclosure.
- Add a fast-path Concept Mode block for users without exact dimensions/specifications.
- Concept Mode acknowledgement and preferences can launch Future Discovery immediately.
- Evidence forms auto-save text/select/checkbox drafts to browser localStorage using a state-specific key, so validation errors and back-navigation do not erase work.
- Once evidence is successfully accepted, the next state uses a new draft key; submitted answers are represented in a visible Saved Evidence ledger instead of being re-entered.
- Improve quick-answer choices for textiles, insulation, glass type, electrical properties, weather resistance, cutting intervals, and adhesives.

## Concept Mode safety / trust contract

Concept Mode output is explicitly labeled exploratory. It must not claim verified:

- dimensions;
- material grade/composition;
- structural integrity or load capacity;
- electrical compatibility;
- heat/flame performance;
- pressure resistance;
- food-contact safety;
- regulatory compliance;
- manufacturability.

Form Architect must preserve unresolved properties as dependencies. Feasibility Critic treats PASS as concept-visualization approval only. Visual Brief keeps unknown properties visually ambiguous and forbids engineering-proof presentation.

The UI notice explains that the limitation notice is not itself a guarantee that all legal liability is waived. Production terms, jurisdiction-specific disclosures, and product-liability review remain separate legal work.

## Runtime efficiency improvement

Text reasoning agents no longer receive full base64 image payloads embedded inside ProjectState on every call. `reasoning_state.compact_state_json` preserves evidence IDs while replacing image bytes with compact references. The actual image evidence remains intact in persistent state for multimodal review and rendering.

## Data added to transformation sessions

- `reasoning_mode`: `verified | concept`
- `concept_mode_acknowledged`: boolean
- `concept_notice_version`: versioned acknowledgement text identifier

This creates auditable lineage for whether a future form came from verified evidence or an explicitly speculative path.

## What this build does not claim

Concept Mode is not a substitute for engineering verification, qualified professional review, product testing, certification, or applicable legal/regulatory compliance.

## Next bottleneck to test

Run a real blocked object set through Concept Mode and confirm:

1. future discovery completes with unresolved evidence;
2. assumptions remain visible in candidate dependencies;
3. the user reaches three concepts without answering every question;
4. render references are accepted by the active Higgsfield endpoint.

If Higgsfield rejects `data:` source references, the next build is the Evidence Upload Bridge using external object storage and scoped URLs.

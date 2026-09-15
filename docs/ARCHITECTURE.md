# RUINFORM Intelligence Architecture

## Product thesis

RUINFORM is not a chatbot. It is a stateful physical-transformation system.

The visible assistant is **THE MAKER**. Internally it coordinates specialist capabilities that each own a narrow responsibility.

## Current agent graph

### THE MAKER
Orchestrates the project. It decides what evidence is missing, which specialist to call, when to stop, and what the user should see.

### Material Eye
Turns user evidence into structured observations. It identifies likely materials, condition, reusable regions and uncertainty. It is forbidden to infer hidden physical properties without evidence.

### Evidence Contract
A deterministic runtime layer between model output and downstream agents. It checks provenance, stable property keys, claim history, prior-claim relationships, and important unknowns. Model output that fails this contract is not admitted into trusted `ProjectState`.

### Form Architect
Generates candidate future forms only after Material Eye has produced sufficient evidence and the Evidence Contract passes.

### Feasibility Critic
Critiques candidate forms against available matter, tools, skill, time and unresolved dependencies. It returns `pass`, `revise`, or `reject`.

### Revision Architect
Receives only promising `revise` candidates plus explicit requested changes. It can repair a concept but may not invent missing physical facts. Revision is bounded to stop recursive cost and drift.

### Visual Brief
Converts a passed future form into a renderer-safe visual contract: silhouette, material mapping, visible connections, composition, camera, provenance cues, unresolved unknowns and forbidden inventions.

### Render Gateway
Compiles the Visual Brief into a provider-neutral `RenderRequest`, carries source-material image references forward, calls a pluggable rendering provider, and preserves every render attempt.

### Render Review
A multimodal review compares generated imagery against the approved future and source references. A deterministic Render Trust Gate can override an optimistic model result when fidelity is below threshold, invention risk is too high, or a blocking violation exists.

### Later specialists
Value Engine, Build Master, Verifier and Archivist will be added after the evidence, invention and render loops are reliable.

## Runtime loop

1. Ingest evidence into an append-only evidence ledger.
2. Material Eye turns the ledger into current observations and unknowns.
3. Evidence Contract rejects ungrounded or historically inconsistent claims.
4. Evidence Gate decides whether consequential uncertainty remains.
5. If yes, THE MAKER requests the smallest useful follow-up action.
6. New photos, measurements, statements or tool results receive stable evidence IDs.
7. Material Eye reconciles new evidence with claim history as `confirmed`, `revised`, `contradicted`, or `new`.
8. If evidence is sufficient, Form Architect generates an internal candidate pool.
9. Feasibility Critic scores each candidate and marks it `pass`, `revise`, or `reject`.
10. A bounded Revision Architect loop repairs only the strongest promising candidates when needed.
11. THE MAKER ranks and exposes only passed futures.
12. Each visible future receives a renderer-safe Visual Brief.
13. Render Gateway creates a provider-neutral request with source references.
14. The generated image is evaluated by Render Review and the deterministic Render Trust Gate.
15. Failed renders are regenerated within a bounded attempt budget; only passed renders may become visible accepted concepts.
16. User selects a future and build planning begins.

## State is first-class

Conversation text is not the source of truth. `ProjectState` is.

Every consequential physical statement should be traceable to one of:
- user image evidence
- user declaration
- direct measurement
- trusted tool output
- model hypothesis grounded in one or more of those sources

`ProjectState` keeps both current observations and `claim_history`, allowing the system to audit how its understanding changed over time.

Design and render lineage are also first-class. RUINFORM preserves candidate revisions, render requests, provider outputs and review results so successful and failed transformations become future eval/training data.

## Evidence before agents

Downstream agents are not allowed to consume arbitrary prose from prior model turns as physical truth. They consume contract-valid structured state.

This creates a trust boundary:

`untrusted model output → Evidence Contract → trusted project state`

A second trust boundary protects visual output:

`approved concept → renderer → untrusted generated image → Render Trust Gate → visible concept`

The contracts are code, not prompt text. Prompt instructions improve behavior; deterministic validation decides what is admitted.

## Tool design rule

Use typed local function tools for RUINFORM-owned logic. Use MCP for external systems or independently deployed services where a standard tool boundary is useful.

Candidate tool families:
- `vision.*`
- `measure.*`
- `materials.*`
- `geometry.*`
- `render.*`
- `parts.*`
- `pricing.*`
- `market.*`
- `build.*`
- `safety.*`
- `passport.*`

For V1, rendering is intentionally a small typed provider contract rather than a full MCP dependency. A future remote Render MCP can expose the same contract without changing THE MAKER.

## Reliability loop

Every production failure must become either:
- a deterministic unit test,
- an agent eval case,
- or a new invariant in the Constitution.

We optimize eval pass rate, physical success rate, calibration, source-material fidelity and user correction rate — not prose quality alone.

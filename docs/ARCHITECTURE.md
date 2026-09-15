# RUINFORM Intelligence Architecture

## Product thesis

RUINFORM is not a chatbot. It is a stateful physical-transformation system.

The visible assistant is **THE MAKER**. Internally it coordinates specialist capabilities that each own a narrow responsibility.

## Initial agent graph

### THE MAKER
Orchestrates the project. It decides what evidence is missing, which specialist to call, when to stop, and what the user should see.

### Material Eye
Turns user evidence into structured observations. It identifies likely materials, condition, reusable regions and uncertainty. It is forbidden to infer hidden physical properties without evidence.

### Evidence Contract
A deterministic runtime layer between model output and downstream agents. It checks provenance, stable property keys, claim history, prior-claim relationships, and important unknowns. Model output that fails this contract is not admitted into trusted `ProjectState`.

### Form Architect
Generates candidate future forms only after Material Eye has produced sufficient evidence and the Evidence Contract passes.

### Feasibility Engineer
Critiques candidate forms against available matter, geometry, tools, skill, time, safety and budget. Failed concepts return to Form Architect with explicit reasons.

### Later specialists
Value Engine, Build Master, Verifier and Archivist will be added after the evidence and feasibility loop is reliable.

## Runtime loop

1. Ingest evidence into an append-only evidence ledger.
2. Material Eye turns the ledger into current observations and unknowns.
3. Evidence Contract rejects ungrounded or historically inconsistent claims.
4. Evidence Gate decides whether consequential uncertainty remains.
5. If yes, THE MAKER requests the smallest useful follow-up action.
6. New photos, measurements, statements or tool results receive stable evidence IDs.
7. Material Eye reconciles new evidence with claim history as `confirmed`, `revised`, `contradicted`, or `new`.
8. If evidence is sufficient, Form Architect generates an internal candidate pool.
9. Feasibility Engineer scores, rejects or sends candidates back for revision.
10. THE MAKER exposes only the strongest feasible futures.
11. User selects a future and build planning begins.

## State is first-class

Conversation text is not the source of truth. `ProjectState` is.

Every consequential statement should be traceable to one of:
- user image evidence
- user declaration
- direct measurement
- trusted tool output
- model hypothesis grounded in one or more of those sources

`ProjectState` keeps both current observations and `claim_history`, allowing the system to audit how its understanding changed over time.

## Evidence before agents

Downstream agents are not allowed to consume arbitrary prose from prior model turns as physical truth. They consume contract-valid structured state.

This creates a trust boundary:

`untrusted model output → Evidence Contract → trusted project state`

The contract is code, not prompt text. Prompt instructions improve behavior; deterministic validation decides what is admitted.

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

## Reliability loop

Every production failure must become either:
- a deterministic unit test,
- an agent eval case,
- or a new invariant in the Constitution.

We optimize eval pass rate, physical success rate, calibration and user correction rate — not prose quality alone.

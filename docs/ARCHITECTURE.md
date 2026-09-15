# RUINFORM Intelligence Architecture

## Product thesis

RUINFORM is not a chatbot. It is a stateful physical-transformation system.

The visible assistant is **THE MAKER**. Internally it coordinates specialist capabilities that each own a narrow responsibility.

## Initial agent graph

### THE MAKER
Orchestrates the project. It decides what evidence is missing, which specialist to call, when to stop, and what the user should see.

### Material Eye
Turns user evidence into structured observations. It identifies likely materials, condition, reusable regions and uncertainty. It is forbidden to infer hidden physical properties without evidence.

### Form Architect
Generates candidate future forms only after Material Eye has produced sufficient evidence.

### Feasibility Engineer
Critiques candidate forms against available matter, geometry, tools, skill, time, safety and budget. Failed concepts return to Form Architect with explicit reasons.

### Later specialists
Value Engine, Build Master, Verifier and Archivist will be added after the evidence and feasibility loop is reliable.

## Runtime loop

1. Ingest evidence.
2. Normalize it into `ProjectState`.
3. Material Eye creates observations and unknowns.
4. Evidence Gate decides whether consequential uncertainty remains.
5. If yes, THE MAKER requests the smallest useful follow-up action.
6. If no, Form Architect generates an internal candidate pool.
7. Feasibility Engineer scores/rejects each candidate.
8. THE MAKER exposes only the strongest feasible futures.
9. User selects a future.
10. Build planning begins in a later milestone.

## State is first-class

Conversation text is not the source of truth. `ProjectState` is.

Every consequential statement should be traceable to one of:
- user evidence
- user declaration
- trusted tool output
- model hypothesis

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

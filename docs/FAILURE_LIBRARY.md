# RUINFORM Failure Library

Every meaningful production failure must become a durable learning artifact. This file indexes recurring failure classes; detailed examples belong in eval cases and build notes.

| ID | Failure class | Example symptom | Required defense |
| --- | --- | --- | --- |
| F-001 | Invented physical fact | Model infers wall thickness from a single exterior photo | Evidence Contract + targeted evidence request |
| F-002 | Unsupported material identity | Visual similarity is promoted to exact grade/composition | FACT/HYPOTHESIS separation + confidence + evidence |
| F-003 | Impossible material allocation | Candidate consumes more source matter than evidence supports | Form validation + Feasibility Critic |
| F-004 | Tool mismatch | Design requires equipment the user does not have | Project constraints + Feasibility Critic |
| F-005 | Pretty but unbuildable concept | Strong visual idea cannot survive construction constraints | Architect → Critic → bounded revision loop |
| F-006 | Generic upcycling collapse | System returns common craft ideas despite strong source character | Form Architect evals for originality/artistic thesis |
| F-007 | Render material substitution | Generator replaces worn source matter with pristine generic texture | Source-image references + Render Review |
| F-008 | Render invents components | Generated image adds undeclared supports, fasteners or parts | Visual Brief forbidden-invention list + Render Trust Gate |
| F-009 | Render resolves unknowns | Image visually asserts a dimension/property that remains unknown | Unknown propagation into Visual Brief + Render Trust Gate |
| F-010 | Renderer drift across retries | Regeneration moves away from approved candidate instead of fixing one defect | Exact candidate ID, immutable Visual Brief, attempt lineage |

## Rule

When a new failure is observed in a real user build:

1. assign or reuse a failure ID;
2. save the triggering evidence and expected behavior in `evals/cases/`;
3. decide whether the defense belongs in prompt, deterministic code, tool contract, or all three;
4. add a regression test when deterministic behavior can enforce it;
5. record the fix and before/after behavior in the current build note.

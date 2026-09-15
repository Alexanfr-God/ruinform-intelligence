# RFM-INT-0001.3 — Evidence Contract

## Goal

Make every consequential physical claim auditable before RUINFORM is allowed to design from it.

## Hypothesis

Material intelligence becomes materially safer and easier to improve when the model is not allowed to return free-floating claims. Every current claim should be bound to stable property keys, exact evidence IDs, and explicit prior claim relationships.

## Added

- Stable `property_key` on observations and structured evidence.
- Structured measurement evidence with value, unit, and property key.
- Exact provenance validation for facts and hypotheses.
- Persistent `claim_history` in `ProjectState`.
- Claim evolution states: `new`, `confirmed`, `revised`, `contradicted`.
- Exact `prior_observation_ids` for follow-up claims.
- Deterministic Evidence Contract validator.
- Rejection of invented evidence IDs and invalid prior references.
- Regression tests for grounded claims and claim history.
- GitHub Actions CI on Python 3.11 and 3.12.

## Invariants introduced

1. A fact or hypothesis without evidence fails the contract.
2. A current observation without a stable property key fails the contract.
3. A follow-up claim must point to a real observation in claim history.
4. A property already present in history cannot silently reappear as `new`.
5. Evidence source type must match the actual ledger item.
6. Medium/high consequence unknowns require a stable property key.

## Why this matters

The next specialist, Form Architect, must receive a state that can distinguish observed reality from model inference and unresolved uncertainty. Otherwise visual creativity can compound an early hallucination into geometry, instructions, cost, and safety errors.

## Next build

**RFM-INT-0002 — Form Architect + Feasibility Critic**

Generate a broad internal candidate pool from contract-valid matter state, then reject or revise concepts against material quantity, geometry, user constraints, build operations, and safety before exposing the strongest futures.

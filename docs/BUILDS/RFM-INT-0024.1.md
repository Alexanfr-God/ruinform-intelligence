# RFM-INT-0024.1 — Resume Navigation

## Why

RFM-INT-0024 made BUILD evidence resumable, but `BACK TO FUTURES` could strand users on the concepts page with no obvious route back to an already-approved render or stored MAKE IT REAL handoff.

The underlying render/build session was still durable; this was a navigation trap, not data loss.

## Changes

- Concepts page shows `SAVED OUTPUT / RESUME` when the session already has an approved render.
- Adds `OPEN APPROVED RENDER` without spending image tokens.
- Adds `OPEN MAKE IT REAL` when a build plan already exists.
- MAKE IT REAL pages add `BACK TO APPROVED RENDER` alongside `BACK TO FUTURES`.
- Navigation wrappers are UI-only and do not mutate session state or call generation providers.

## Acceptance

A user can go BUILD -> FUTURES -> APPROVED RENDER -> BUILD without rerendering or regenerating anything.

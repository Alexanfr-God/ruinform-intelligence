# RFM-INT-0024.2 — Workshop Evidence UX

Goal: make evidence requests executable by a normal maker instead of asking the user to perform engineering analysis.

## Contract

- The user supplies raw facts only: measurements, inspection findings, manufacturer facts, and workshop photos.
- RUINFORM derives engineering implications from those facts.
- Evidence tasks are phase-aware: NOW, AFTER MOCK-UP, AFTER ASSEMBLY, BEFORE INSTALLATION.
- Only the earliest actionable phase exposes input controls.
- Later tasks remain visible as a locked queue so the maker understands what comes next.
- Partial evidence is valid. A round may submit any real fact/photo available in the active phase.
- No render or concept regeneration is triggered by evidence submission.

## Acceptance

For a wall-mounted concept with unknown load and final mass, the user should be asked for simple facts available now (source geometry/material inspection/location photo) while completed assembly mass is deferred to AFTER ASSEMBLY rather than blocking the first evidence round.

# RFM-INT-0001.2 — Evidence Loop

Goal: make Material Eye iterative instead of one-shot.

Added:
- follow-up turns with images, statements and measurements
- reconciliation against existing ProjectState
- resolved/new unknown tracking
- optional stable property keys
- evidence-loop API router
- deterministic tests

Runtime:
`PROJECT STATE → NEW EVIDENCE → RE-INSPECTION → UNKNOWN DIFF → EVIDENCE GATE`

Current limitation: measurement and statement evidence is preserved in the ledger and supplied to the next inspection, but direct claim-to-measurement citation will be tightened in a later evidence-contract revision.

Next: RFM-INT-0002 Form Architect after the evidence gate passes.

# RFM-INT-0001 — Material Intelligence

## Goal
Build the first reliable intelligence layer: understand user-provided physical matter without hallucinating hidden properties.

## Scope
This build covers:
- evidence ingestion
- structured `ProjectState`
- material observations with confidence
- fact / hypothesis / unknown separation
- follow-up evidence requests
- regression eval cases

This build does **not** yet cover:
- final product ideation quality
- geometry solving
- BOM generation
- live pricing
- build instructions
- verification
- provenance

## Success criteria
1. No unsupported physical dimension may be emitted as fact.
2. Material identity may be probabilistic, but confidence and basis must be explicit.
3. Consequential unknowns generate a targeted follow-up request.
4. The system can explain which evidence supports each important observation.
5. Project state survives across turns independently of chat prose.

## First benchmark family
- denim + leather + steel hardware from multiple photos
- ambiguous sheet material that could be leather or synthetic
- metal tube with unknown wall thickness
- damaged electrical object with unsafe reuse ambiguity
- single image with poor scale reference

## Learning ledger
For every meaningful change record:
- hypothesis
- changed component
- eval cases added
- failures before
- failures after
- regression status
- next constraint to attack

## Status
`BOOTSTRAPPED`

# RUINFORM TASTE LIBRARY — v0

This folder is the future visual reference library for RUINFORM.

It is intentionally small at first. Do not fill it with random inspiration. Every reference must teach the Design Brain a specific taste rule.

## MVP rule

Start with only **6–10 strong references**. That is enough to test whether visual few-shot calibration improves consistency.

Do not wait for 50 images before testing.

## First buckets

```text
lighting/
wall-art/
sculpture/
furniture/
small-objects/
materials/
backgrounds/
post-apocalyptic-world/
```

## Reference metadata

Each approved reference should have metadata shaped roughly like:

```json
{
  "id": "lighting_001",
  "category": "lighting",
  "source": "user-provided-or-licensed-reference",
  "why_good": [
    "strong single silhouette",
    "source material remains recognizable",
    "lighting reveals construction rather than becoming decoration",
    "looks collectible but physically plausible"
  ],
  "formal_traits": [
    "asymmetric",
    "negative-space",
    "soft-vs-rigid"
  ],
  "world_traits": [
    "salvage-luxury",
    "post-consumer-artifact"
  ],
  "avoid_copying": [
    "exact geometry",
    "branding",
    "artist-specific signature details"
  ]
}
```

## Selection rule

At generation time, retrieve only 2–4 references that match the current object category/material problem.

Do not feed the entire library to the model.

## What belongs here

Good references show at least two of these:

- surprising transformation of ordinary matter
- strong silhouette
- visible provenance
- buildable material logic
- excellent material photography
- post-consumer / salvage character without generic cyberpunk styling
- meaningful tension between materials
- contemporary collectible design quality

## What does NOT belong here

- images saved only because they look cool
- generic Midjourney cyberpunk
- pure moodboards with no object logic
- polished product shots with no reclaimed-material relevance
- copies of one artist/style repeated many times

## Current status

Structure ready. First 6–10 references still need to be curated with the user.

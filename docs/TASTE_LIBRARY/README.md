# RUINFORM TASTE LIBRARY - v0.1

This is not a moodboard. It is a small teaching set for the RUINFORM Design Brain.

Every card must teach a **transferable design operator**. The visual world is secondary to the object logic.

## Current design grammar

| Card | Operator | Core lesson |
|---|---|---|
| `001_watcher` | Mutate behavior | Make a found object do something it normally never does. |
| `002_loadbearer` | Turn force into story | Make structural necessity visible as narrative. |
| `003_wastelight` | Recompose simply | Strong form can come from a minimal recombination of ordinary parts. |
| `004_trashlight` | Reassign roles | Do not upgrade the material; give the waste a new role. |
| `005_floatrelic` | Expose invisible force | Make a physical phenomenon part of the visible design. |

See `index.json` for machine-readable retrieval metadata.

## Required folder format

```text
NNN_slug/
  concept.md
  concept.json
  assets/
    manifest.json
    01_source_parts.jpg
    02_principle_assembly.jpg
    03_clean_product.jpg
    04_hero_world.jpg
```

The reusable starter files live in `_TEMPLATE/`.

## Four required visual roles

1. **source_parts** - the actual parts, source matter or closest available evidence of the components.
2. **principle_assembly** - how the transformation, physical principle or intervention works.
3. **clean_product** - object-first view with the least possible world/style interference.
4. **hero_world** - the object placed in a cinematic RUINFORM context.

The clean-product image matters because it prevents the model from confusing RUINFORM with one background, color grade or bunker aesthetic.

## Card rule

A card must include:

- one design operator
- one core transferable lesson
- what the Brain should learn
- what the Brain must **not** copy
- material language
- retrieval tags
- provenance
- a four-role visual manifest

## Retrieval rule

At generation time, retrieve only **2-4** cards or visual layers that match the current material/problem.

Do not feed the whole library to the model.

## Important distinction

RUINFORM is **not**:

- rust everywhere
- orange bunker lighting
- radiation symbols
- gas masks
- generic cyberpunk
- a specific artist's style

RUINFORM is:

- found matter
- visible provenance
- role/function/behavior transformation
- surprising but legible physical logic
- contemporary collectible value

## MVP scope

Keep the library intentionally small. The first target is 6-10 excellent cards with genuinely different design operators, not 50 visually similar references.

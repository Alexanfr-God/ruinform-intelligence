# TASTE LIBRARY ASSET INGEST

The first ten cards are structurally complete: `concept.md`, `concept.json`, and an exact source mapping for the four required visual roles.

The four binary image targets per card are:

1. `assets/01_source_parts.jpg`
2. `assets/02_principle_assembly.jpg`
3. `assets/03_clean_product.jpg`
4. `assets/04_hero_world.jpg`

Current status: the source page / supplied-image mapping is committed in each `assets/manifest.json`. Binary JPG materialization is intentionally tracked separately so the future Taste Library bucket can become the canonical visual store instead of scattering duplicate binary assets across chat, PDFs and the repository.

When the bucket is connected, ingestion should preserve these exact card IDs and roles. The Design Brain should retrieve a small number of matching cards (normally 2-4), not the entire library.

## Safety metadata

Cards that describe real mains-powered electrical objects may include explicit safety metadata in `concept.json`, such as `electrical_safety_required`. This is part of buildability and should not be stripped during ingestion or retrieval.

from __future__ import annotations

"""Keep Object Passport forward-compatible with append-only provenance fields.

The original V0 Pydantic model intentionally described only the stable core. As
verification, wallet identity, economics and NFT provenance were added, those
fields were persisted in the same JSON document. Pydantic's default `extra=ignore`
meant a read -> model_dump round-trip could silently drop newer fields.

RUINFORM passports are append-only records: a legacy core model must never erase
provenance it does not yet understand. Configure the model to preserve extras and
rebuild its validator/serializer once at application startup.
"""

from .object_passport import ObjectPassport


ObjectPassport.model_config["extra"] = "allow"
ObjectPassport.model_rebuild(force=True)

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
from pathlib import Path

from . import object_economics as legacy


# RF-CREATOR-v1.2 defines the canonical NFT Passport as RUINFORM's digital
# certificate of provenance and ownership-chain continuity for a registered
# physical object. A token alone does not claim physical possession; supported
# transfer completes the digital record together with physical handoff/receipt.
TERMS_VERSION = "RF-CREATOR-v1.2"
TERMS_TEXT = """RUINFORM CREATOR AGREEMENT — RF-CREATOR-v1.2

1. CREATOR REGISTRATION
The signing wallet confirms that it controls the wallet used to register this RUINFORM Object Passport and is authorized to register the referenced object and creative work in RUINFORM.

2. CANONICAL OBJECT IDENTITY
The referenced RuF Object ID is the canonical RUINFORM identity for this registered object. Creator attribution is permanent provenance and does not transfer when ownership changes.

3. ONE CANONICAL NFT PASSPORT
RUINFORM will recognize no more than one canonical RUINFORM NFT Passport mint for the referenced RuF Object ID. A transfer, resale, burn, duplicate image, copy, fork, or derivative does not authorize a second canonical mint for the same RuF Object ID.

4. NFT PASSPORT AS PROVENANCE CERTIFICATE
The canonical RUINFORM NFT Passport is intended to function inside the RUINFORM system as the digital certificate of provenance and ownership-chain continuity for the referenced registered physical object. It records canonical identity, creator provenance, agreement version/hash, verification history and supported ownership transfers. The token by itself does not represent that RUINFORM has physically inspected, possessed, shipped or delivered the object and does not by itself establish legal title under every jurisdiction.

5. LIVE PHYSICAL PROOF AND NFT ELIGIBILITY
A canonical NFT Passport becomes eligible to mint after the registered creator accepts this agreement and RUINFORM has recorded valid fresh live-camera proof for the referenced physical object. The AI Object Match score is a descriptive fidelity assessment and does not by itself block minting. A low, partial, disputed, or later-improved Object Match score remains part of the object's provenance.

6. AI ASSESSMENT AND CREATOR APPEAL
RUINFORM verification is an evidence-based AI assessment, not an infallible judgment. The registered creator may dispute a verification result. The original result remains preserved. A later review may uphold the result, override the assessment, or request new proof without changing the canonical RuF Object ID or authorizing a second canonical NFT mint.

7. RUINFORM RESALE ROYALTY
Qualifying resales completed through RUINFORM or a RUINFORM-recognized marketplace/transfer protocol are subject to a RUINFORM platform resale royalty of 5.00% (500 basis points), subject to applicable law and the mechanics of the marketplace or transfer protocol. This royalty is a platform resale royalty and does not state that RUINFORM owns 5% of the physical object.

8. PHYSICAL AND DIGITAL TRANSFER / CHAIN OF CUSTODY
A supported transfer of a registered physical object is intended to move the physical object and its canonical Object Passport/NFT Passport together. The transferor represents that it is authorized to transfer the physical object and the canonical Passport. RUINFORM may require buyer/recipient confirmation, QR or camera evidence, delivery evidence or another supported handoff step before recording the new current owner. Creator provenance never changes when current ownership changes.

9. OWNERSHIP RECORD AND PHYSICAL POSSESSION
The current-owner field and NFT ownership are RUINFORM provenance records. A blockchain transfer without the corresponding supported physical handoff may be marked incomplete, disputed or out of good standing. Likewise, an off-platform physical transfer that does not transfer the canonical Passport may break the documented chain of custody until resolved through a supported RUINFORM process.

10. ON-CHAIN RECORD
When the canonical NFT Passport is minted, RUINFORM may anchor the RuF Object ID, this agreement version, the exact agreement hash, the royalty configuration, the then-current verification state, and a content hash of the mint snapshot on Solana or in the canonical NFT metadata/plugins.

11. GOOD-STANDING PROGRAM
RUINFORM may offer badges, reduced fees, visibility, rewards, free or reduced-cost minting, or other benefits for verified, accurately transferred and good-standing objects and participants. Such benefits are optional program features and are not guaranteed consideration under this agreement.

12. IMMUTABLE ACCEPTANCE RECORD
Acceptance is object-specific. RUINFORM records the signing wallet, RuF Object ID, agreement version, exact agreement SHA-256 hash, signature, and timestamp. A later agreement version does not silently replace the version accepted for this object.
"""
TERMS_HASH = hashlib.sha256(TERMS_TEXT.encode("utf-8")).hexdigest()


# Capture the implementation before replacing the module-level name used by the
# already-declared FastAPI route handlers in object_economics.py.
_legacy_read_object_economics = legacy.read_object_economics


def _database_url() -> str | None:
    return os.getenv("DATABASE_URL") or os.getenv("RUINFORM_DATABASE_URL")


def _sqlite_path() -> Path:
    return Path(os.getenv("RUINFORM_DB_PATH", ".ruinform/ruinform.db"))


def _backend_object_id(object_id: str) -> str:
    value = object_id.strip().upper().replace("RUF-", "RF-")
    return value


def _live_proof_status(object_id: str) -> str | None:
    backend_id = _backend_object_id(object_id)
    row = None
    database_url = _database_url()
    if database_url:
        import psycopg

        with psycopg.connect(database_url) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT payload_json FROM ruinform_objects WHERE object_id=%s", (backend_id,))
                row = cur.fetchone()
    else:
        path = _sqlite_path()
        if not path.exists():
            return None
        with sqlite3.connect(path) as conn:
            try:
                row = conn.execute("SELECT payload_json FROM ruinform_objects WHERE object_id=?", (backend_id,)).fetchone()
            except sqlite3.OperationalError as exc:
                # Economics tables can exist before the Object Passport store has
                # initialized its own table. In that state there is simply no
                # durable live proof yet; it must not become a server error.
                if "no such table" in str(exc).lower():
                    return None
                raise
    if not row:
        return None
    try:
        payload = json.loads(row[0])
    except (TypeError, ValueError):
        return None
    value = payload.get("verification_proof_status")
    return str(value).lower() if value is not None else None


def read_object_economics(object_id: str):
    result = _legacy_read_object_economics(object_id)
    blockers: list[str] = []
    if not result.creator_wallet:
        blockers.append("CREATOR_NOT_REGISTERED")
    if result.agreement_status != "SIGNED":
        blockers.append("CREATOR_AGREEMENT_NOT_SIGNED")
    if _live_proof_status(object_id) != "valid":
        blockers.append("LIVE_PHYSICAL_PROOF_REQUIRED")
    if result.nft_status == "MINTED":
        blockers.append("CANONICAL_NFT_ALREADY_MINTED")
    result.blockers = blockers
    result.eligible_to_mint = not blockers
    return result


# Patch the globals referenced by the route functions already attached to legacy.router.
legacy.TERMS_VERSION = TERMS_VERSION
legacy.TERMS_TEXT = TERMS_TEXT
legacy.TERMS_HASH = TERMS_HASH
legacy.read_object_economics = read_object_economics

router = legacy.router

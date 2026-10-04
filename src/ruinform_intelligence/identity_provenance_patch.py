from __future__ import annotations

import os
import re

import httpx

from . import nft_devnet


_ID_REGISTRY_URL = os.getenv(
    "RUINFORM_ID_REGISTRY_URL",
    "https://ruinform.higgsfield.app/api/passport-public",
)
_HASH_RE = re.compile(r"^[a-f0-9]{64}$")

_original_snapshot = nft_devnet._snapshot
_original_read_snapshot_metadata = nft_devnet.read_snapshot_metadata


def _creator_identity(wallet: str) -> dict | None:
    # Unit tests and local isolated stores must not depend on the production web
    # registry. Production requests resolve the already chain-verified ID record.
    if os.getenv("PYTEST_CURRENT_TEST"):
        return None
    try:
        response = httpx.get(
            _ID_REGISTRY_URL,
            params={"wallet": wallet},
            timeout=3.0,
            follow_redirects=True,
        )
        if response.status_code != 200:
            return None
        payload = response.json()
    except (httpx.HTTPError, ValueError, TypeError):
        return None
    if not isinstance(payload, dict) or payload.get("active") is not True:
        return None
    if str(payload.get("walletAddress") or "") != wallet:
        return None
    ruinform_id = str(payload.get("ruinformId") or "")
    asset_address = str(payload.get("assetAddress") or "")
    record_hash = str(payload.get("recordHash") or "").lower()
    if not ruinform_id.startswith("RUI-") or len(asset_address) < 32 or not _HASH_RE.fullmatch(record_hash):
        return None
    return {
        "ruinform_id": ruinform_id,
        "asset_address": asset_address,
        "record_hash": record_hash,
        "creator_name": str(payload.get("creatorName") or ""),
        "origin": str(payload.get("origin") or ""),
        "discipline": str(payload.get("discipline") or ""),
        "artifact_style": str(payload.get("artifactStyle") or ""),
        "issued_at": str(payload.get("issuedAt") or ""),
        "identity_standard": "RF-ID-v1",
        "soulbound": True,
    }


def _snapshot_with_identity(*, object_id: str, wallet: str, asset_address: str):
    snapshot, economics = _original_snapshot(
        object_id=object_id,
        wallet=wallet,
        asset_address=asset_address,
    )
    identity = _creator_identity(wallet)
    if identity:
        snapshot["creator_identity"] = identity
    return snapshot, economics


def _metadata_with_identity(object_id: str, snapshot_hash: str) -> dict:
    metadata = _original_read_snapshot_metadata(object_id, snapshot_hash)
    properties = metadata.get("properties") if isinstance(metadata, dict) else None
    snapshot = properties.get("ruinform") if isinstance(properties, dict) else None
    identity = snapshot.get("creator_identity") if isinstance(snapshot, dict) else None
    if not isinstance(identity, dict):
        return metadata
    attributes = metadata.setdefault("attributes", [])
    known = {str(row.get("trait_type")) for row in attributes if isinstance(row, dict)}
    for trait_type, value in (
        ("Creator RUINFORM ID", identity.get("ruinform_id")),
        ("Creator Identity Asset", identity.get("asset_address")),
        ("Creator Identity Record", identity.get("record_hash")),
        ("Creator Identity Standard", identity.get("identity_standard")),
    ):
        if value and trait_type not in known:
            attributes.append({"trait_type": trait_type, "value": str(value)})
    return metadata


nft_devnet._snapshot = _snapshot_with_identity
nft_devnet.read_snapshot_metadata = _metadata_with_identity

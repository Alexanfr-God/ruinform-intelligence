from __future__ import annotations

import hashlib
import json
import sqlite3
from urllib.parse import parse_qs, urlparse

from fastapi import Header, HTTPException
from pydantic import Field

from . import nft_devnet, nft_public


MEDIA_STANDARD = "RF-NFT-MEDIA-v1"
EXPECTED_IMAGE_SIZE = "1600x2000"
ALLOWED_MEDIA_HOST = "ruinform.higgsfield.app"
ALLOWED_MEDIA_PATH = "/api/artifact-passport-image"


class MediaMintMetadata(nft_public.EditableMintMetadata):
    artifact_image_url: str = Field(min_length=20, max_length=2000)
    artifact_image_sha256: str = Field(min_length=64, max_length=64)


def _validate_media(payload: MediaMintMetadata) -> tuple[str, str]:
    image_url = payload.artifact_image_url.strip()
    digest = payload.artifact_image_sha256.strip().lower()
    if len(digest) != 64 or any(ch not in "0123456789abcdef" for ch in digest):
        raise HTTPException(status_code=400, detail="A valid Artifact Passport PNG SHA-256 is required")
    parsed = urlparse(image_url)
    if parsed.scheme != "https" or parsed.hostname != ALLOWED_MEDIA_HOST or parsed.path != ALLOWED_MEDIA_PATH:
        raise HTTPException(status_code=400, detail="Artifact Passport media must be sealed by RUINFORM")
    query = parse_qs(parsed.query)
    if query.get("hash", [""])[0].lower() != digest:
        raise HTTPException(status_code=400, detail="Artifact Passport media URL does not match its SHA-256")
    return image_url, digest


def _database_url() -> str | None:
    return nft_public._database_url()


def _load_intent_snapshot(intent_id: str) -> tuple[dict, str]:
    database_url = _database_url()
    row = None
    if database_url:
        import psycopg

        with psycopg.connect(database_url) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT snapshot_json,object_id FROM ruinform_devnet_mint_intents WHERE intent_id=%s AND status='PENDING'",
                    (intent_id,),
                )
                row = cur.fetchone()
    else:
        with sqlite3.connect(nft_public._sqlite_path()) as conn:
            row = conn.execute(
                "SELECT snapshot_json,object_id FROM ruinform_devnet_mint_intents WHERE intent_id=? AND status='PENDING'",
                (intent_id,),
            ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Devnet mint intent not found")
    return json.loads(row[0]), str(row[1])


def _persist_snapshot(intent_id: str, snapshot: dict, object_id: str) -> tuple[str, str]:
    canonical_json = json.dumps(snapshot, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    snapshot_hash = hashlib.sha256(canonical_json.encode("utf-8")).hexdigest()
    public_url = nft_public._metadata_url(object_id, snapshot_hash)
    database_url = _database_url()
    if database_url:
        import psycopg

        with psycopg.connect(database_url) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE ruinform_devnet_mint_intents SET snapshot_hash=%s,snapshot_json=%s,metadata_url=%s WHERE intent_id=%s AND status='PENDING'",
                    (snapshot_hash, canonical_json, public_url, intent_id),
                )
                if cur.rowcount != 1:
                    raise HTTPException(status_code=409, detail="Artifact Passport media could not be locked")
            conn.commit()
    else:
        with sqlite3.connect(nft_public._sqlite_path()) as conn:
            cursor = conn.execute(
                "UPDATE ruinform_devnet_mint_intents SET snapshot_hash=?,snapshot_json=?,metadata_url=? WHERE intent_id=? AND status='PENDING'",
                (snapshot_hash, canonical_json, public_url, intent_id),
            )
            if cursor.rowcount != 1:
                raise HTTPException(status_code=409, detail="Artifact Passport media could not be locked")
    return snapshot_hash, public_url


def _rewrite_with_media(intent_id: str, payload: MediaMintMetadata) -> tuple[dict, str, str]:
    # First apply the editable public fields using the existing canonical path.
    nft_public._rewrite_intent_snapshot(intent_id, payload)
    snapshot, object_id = _load_intent_snapshot(intent_id)
    image_url, image_sha256 = _validate_media(payload)
    snapshot.update(
        {
            "schema": "ruinform-canonical-nft-passport-v0.3",
            "nft_media_standard": MEDIA_STANDARD,
            "artifact_image_url": image_url,
            "artifact_image_sha256": image_sha256,
            "artifact_image_mime": "image/png",
            "artifact_image_dimensions": EXPECTED_IMAGE_SIZE,
        }
    )
    snapshot_hash, public_url = _persist_snapshot(intent_id, snapshot, object_id)
    return snapshot, snapshot_hash, public_url


@nft_public.router.post(
    "/v1/nft-passports/{object_id}/devnet/intent-media",
    response_model=nft_devnet.DevnetMintIntentResponse,
)
async def create_devnet_mint_intent_with_media(
    object_id: str,
    payload: MediaMintMetadata,
    x_ruinform_wallet_session: str | None = Header(default=None, alias="x-ruinform-wallet-session"),
):
    result = nft_public._original_issue_devnet_mint_intent(
        object_id=object_id,
        asset_address=payload.asset_address,
        wallet_session=x_ruinform_wallet_session,
    )
    snapshot, snapshot_hash, public_url = _rewrite_with_media(result.intent_id, payload)
    attributes = [
        {"key": item["key"], "value": snapshot_hash if item["key"] == "Snapshot SHA256" else item["value"]}
        for item in result.attributes
    ]
    if snapshot.get("edition_label"):
        attributes.append({"key": "Edition", "value": str(snapshot["edition_label"])})
    if snapshot.get("tags"):
        attributes.append({"key": "Tags", "value": ", ".join(snapshot["tags"])})
    attributes.append({"key": "Media SHA256", "value": str(snapshot["artifact_image_sha256"])})
    attributes.append({"key": "Media Standard", "value": MEDIA_STANDARD})
    return result.model_copy(
        update={
            "name": str(snapshot["display_name"]),
            "metadata_url": public_url,
            "snapshot_hash": snapshot_hash,
            "attributes": attributes,
        }
    )


_original_read_snapshot_metadata = nft_devnet.read_snapshot_metadata


def _read_snapshot_metadata_with_media(object_id: str, snapshot_hash: str) -> dict:
    metadata = _original_read_snapshot_metadata(object_id, snapshot_hash)
    properties = metadata.get("properties") if isinstance(metadata, dict) else None
    snapshot = properties.get("ruinform") if isinstance(properties, dict) else None
    if not isinstance(snapshot, dict):
        return metadata
    image_url = str(snapshot.get("artifact_image_url") or "").strip()
    image_sha = str(snapshot.get("artifact_image_sha256") or "").strip().lower()
    if image_url and len(image_sha) == 64:
        metadata["image"] = image_url
        metadata["category"] = "image"
        if isinstance(properties, dict):
            properties["category"] = "image"
            properties["files"] = [{"uri": image_url, "type": "image/png"}]
    return metadata


nft_devnet.read_snapshot_metadata = _read_snapshot_metadata_with_media

_original_public_metadata = nft_public._public_metadata


def _public_metadata_with_media(object_id: str, snapshot_hash: str) -> dict:
    metadata = _original_public_metadata(object_id, snapshot_hash)
    properties = metadata.get("properties") if isinstance(metadata, dict) else None
    snapshot = properties.get("ruinform") if isinstance(properties, dict) else None
    if not isinstance(snapshot, dict):
        return metadata
    image_url = str(snapshot.get("artifact_image_url") or "").strip()
    image_sha = str(snapshot.get("artifact_image_sha256") or "").strip().lower()
    if image_url and len(image_sha) == 64:
        vector_url = nft_public._card_url(object_id, snapshot_hash)
        metadata["image"] = image_url
        metadata["category"] = "image"
        if isinstance(properties, dict):
            properties["category"] = "image"
            properties["files"] = [
                {"uri": image_url, "type": "image/png"},
                {"uri": vector_url, "type": "image/svg+xml"},
            ]
            properties["media_standard"] = MEDIA_STANDARD
            properties["media_sha256"] = image_sha
            properties["media_dimensions"] = EXPECTED_IMAGE_SIZE
    return metadata


nft_public._public_metadata = _public_metadata_with_media

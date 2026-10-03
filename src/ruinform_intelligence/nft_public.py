from __future__ import annotations

import hashlib
import html
import json
import os
import sqlite3
from urllib.parse import quote

from fastapi import APIRouter, Header, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel, Field

from . import nft_devnet


router = APIRouter(tags=["public-nft-passport"])
PUBLIC_ORIGIN = os.getenv("RUINFORM_PUBLIC_ORIGIN", "https://ruinform-intelligence.onrender.com").rstrip("/")

# Keep a handle to the original implementation, then patch the name resolved by
# nft_devnet's already-declared FastAPI intent route. This lets the canonical
# on-chain URI use the public read-only origin without duplicating mint logic.
_original_issue_devnet_mint_intent = nft_devnet.issue_devnet_mint_intent


class EditableMintMetadata(BaseModel):
    asset_address: str = Field(min_length=32, max_length=64)
    display_name: str | None = Field(default=None, max_length=120)
    public_description: str | None = Field(default=None, max_length=1200)
    artist_note: str | None = Field(default=None, max_length=1200)
    tags: list[str] = Field(default_factory=list, max_length=8)
    edition_label: str | None = Field(default=None, max_length=64)


def _public_id(value: str) -> str:
    raw = value.strip().upper().replace("RUF-", "RF-")
    if not raw.startswith("RF-") or not raw[3:].isdigit():
        raise HTTPException(status_code=400, detail="A valid RuF Object ID is required")
    return raw.replace("RF-", "RuF-", 1)


def _metadata_url(object_id: str, snapshot_hash: str) -> str:
    public_id = _public_id(object_id)
    return f"{PUBLIC_ORIGIN}/public/nft-passport/{quote(public_id)}/{quote(snapshot_hash)}.json"


def _card_url(object_id: str, snapshot_hash: str) -> str:
    public_id = _public_id(object_id)
    return f"{PUBLIC_ORIGIN}/public/nft-passport/{quote(public_id)}/{quote(snapshot_hash)}.svg"


def _database_url() -> str | None:
    return os.getenv("DATABASE_URL") or os.getenv("RUINFORM_DATABASE_URL")


def _sqlite_path() -> str:
    return os.getenv("RUINFORM_DB_PATH", ".ruinform/ruinform.db")


def _persist_public_metadata_url(intent_id: str, url: str) -> None:
    database_url = _database_url()
    if database_url:
        import psycopg

        with psycopg.connect(database_url) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE ruinform_devnet_mint_intents SET metadata_url=%s WHERE intent_id=%s AND status='PENDING'",
                    (url, intent_id),
                )
            conn.commit()
        return
    with sqlite3.connect(_sqlite_path()) as conn:
        conn.execute(
            "UPDATE ruinform_devnet_mint_intents SET metadata_url=? WHERE intent_id=? AND status='PENDING'",
            (url, intent_id),
        )


def _sanitize_tags(values: list[str]) -> list[str]:
    tags: list[str] = []
    seen: set[str] = set()
    for value in values[:8]:
        tag = " ".join(str(value).strip().split())[:32]
        key = tag.casefold()
        if tag and key not in seen:
            tags.append(tag)
            seen.add(key)
    return tags


def _editable_value(value: str | None, max_length: int) -> str:
    return " ".join((value or "").strip().split())[:max_length]


def _rewrite_intent_snapshot(intent_id: str, metadata: EditableMintMetadata):
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
        with sqlite3.connect(_sqlite_path()) as conn:
            row = conn.execute(
                "SELECT snapshot_json,object_id FROM ruinform_devnet_mint_intents WHERE intent_id=? AND status='PENDING'",
                (intent_id,),
            ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Devnet mint intent not found")

    snapshot = json.loads(row[0])
    object_id = str(row[1])
    original_title = str(snapshot.get("passport_title") or snapshot.get("title") or _public_id(object_id))
    display_name = _editable_value(metadata.display_name, 120) or original_title
    public_description = (metadata.public_description or "").strip()[:1200]
    artist_note = (metadata.artist_note or "").strip()[:1200]
    edition_label = _editable_value(metadata.edition_label, 64)
    tags = _sanitize_tags(metadata.tags)

    snapshot.update(
        {
            "schema": "ruinform-canonical-nft-passport-v0.2",
            "passport_title": original_title,
            "title": display_name,
            "display_name": display_name,
            "public_description": public_description,
            "artist_note": artist_note,
            "tags": tags,
            "edition_label": edition_label,
        }
    )
    canonical_json = json.dumps(snapshot, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    snapshot_hash = hashlib.sha256(canonical_json.encode("utf-8")).hexdigest()
    public_url = _metadata_url(object_id, snapshot_hash)

    if database_url:
        import psycopg

        with psycopg.connect(database_url) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE ruinform_devnet_mint_intents SET snapshot_hash=%s,snapshot_json=%s,metadata_url=%s WHERE intent_id=%s AND status='PENDING'",
                    (snapshot_hash, canonical_json, public_url, intent_id),
                )
                if cur.rowcount != 1:
                    raise HTTPException(status_code=409, detail="Mint metadata draft could not be locked")
            conn.commit()
    else:
        with sqlite3.connect(_sqlite_path()) as conn:
            cursor = conn.execute(
                "UPDATE ruinform_devnet_mint_intents SET snapshot_hash=?,snapshot_json=?,metadata_url=? WHERE intent_id=? AND status='PENDING'",
                (snapshot_hash, canonical_json, public_url, intent_id),
            )
            if cursor.rowcount != 1:
                raise HTTPException(status_code=409, detail="Mint metadata draft could not be locked")

    return snapshot, snapshot_hash, public_url


def issue_devnet_mint_intent_public(*, object_id: str, asset_address: str, wallet_session: str | None):
    result = _original_issue_devnet_mint_intent(
        object_id=object_id,
        asset_address=asset_address,
        wallet_session=wallet_session,
    )
    public_url = _metadata_url(result.object_id, result.snapshot_hash)
    _persist_public_metadata_url(result.intent_id, public_url)
    return result.model_copy(update={"metadata_url": public_url})


# Patch the global looked up by nft_devnet.create_devnet_mint_intent at request time.
nft_devnet.issue_devnet_mint_intent = issue_devnet_mint_intent_public


@router.post("/v1/nft-passports/{object_id}/devnet/intent-custom", response_model=nft_devnet.DevnetMintIntentResponse)
async def create_devnet_mint_intent_with_metadata(
    object_id: str,
    payload: EditableMintMetadata,
    x_ruinform_wallet_session: str | None = Header(default=None, alias="x-ruinform-wallet-session"),
):
    result = _original_issue_devnet_mint_intent(
        object_id=object_id,
        asset_address=payload.asset_address,
        wallet_session=x_ruinform_wallet_session,
    )
    snapshot, snapshot_hash, public_url = _rewrite_intent_snapshot(result.intent_id, payload)
    attributes = list(result.attributes)
    if snapshot.get("edition_label"):
        attributes.append({"key": "Edition", "value": str(snapshot["edition_label"])})
    if snapshot.get("tags"):
        attributes.append({"key": "Tags", "value": ", ".join(snapshot["tags"])})
    return result.model_copy(
        update={
            "name": str(snapshot["display_name"]),
            "metadata_url": public_url,
            "snapshot_hash": snapshot_hash,
            "attributes": attributes,
        }
    )


def _public_metadata(object_id: str, snapshot_hash: str) -> dict:
    metadata = nft_devnet.read_snapshot_metadata(object_id, snapshot_hash)
    card_url = _card_url(object_id, snapshot_hash)
    properties = metadata.get("properties")
    snapshot = properties.get("ruinform") if isinstance(properties, dict) else None
    if isinstance(snapshot, dict):
        display_name = str(snapshot.get("display_name") or snapshot.get("title") or metadata.get("name") or "RUINFORM Passport")
        public_description = str(snapshot.get("public_description") or "").strip()
        metadata["name"] = display_name
        if public_description:
            metadata["description"] = public_description
        attributes = metadata.get("attributes")
        if isinstance(attributes, list):
            edition = str(snapshot.get("edition_label") or "").strip()
            tags = snapshot.get("tags")
            artist_note = str(snapshot.get("artist_note") or "").strip()
            if edition:
                attributes.append({"trait_type": "Edition", "value": edition})
            if isinstance(tags, list) and tags:
                attributes.append({"trait_type": "Tags", "value": ", ".join(str(tag) for tag in tags)})
            if artist_note:
                attributes.append({"trait_type": "Artist Note", "value": artist_note})
    metadata["image"] = card_url
    if isinstance(properties, dict):
        properties["files"] = [{"uri": card_url, "type": "image/svg+xml"}]
    return metadata


@router.get("/public/nft-passport/{object_id}/{snapshot_hash}.json")
async def public_nft_metadata(object_id: str, snapshot_hash: str) -> dict:
    if len(snapshot_hash) != 64 or any(ch not in "0123456789abcdefABCDEF" for ch in snapshot_hash):
        raise HTTPException(status_code=400, detail="A valid snapshot hash is required")
    return _public_metadata(object_id, snapshot_hash)


@router.get("/public/nft-passport/{object_id}/{snapshot_hash}.svg")
async def public_nft_card(object_id: str, snapshot_hash: str) -> Response:
    if len(snapshot_hash) != 64 or any(ch not in "0123456789abcdefABCDEF" for ch in snapshot_hash):
        raise HTTPException(status_code=400, detail="A valid snapshot hash is required")
    metadata = _public_metadata(object_id, snapshot_hash)
    properties = metadata.get("properties") if isinstance(metadata, dict) else None
    snapshot = properties.get("ruinform") if isinstance(properties, dict) else None
    if not isinstance(snapshot, dict):
        raise HTTPException(status_code=404, detail="NFT Passport snapshot not found")

    public_id = html.escape(str(snapshot.get("object_id") or _public_id(object_id)))
    title = html.escape(str(snapshot.get("display_name") or snapshot.get("title") or "RUINFORM OBJECT"))
    creator = html.escape(str(snapshot.get("creator_wallet") or "UNKNOWN"))
    creator_short = f"{creator[:6]}…{creator[-6:]}" if len(creator) > 15 else creator
    live = html.escape(str(snapshot.get("live_proof_status") or "UNKNOWN").upper())
    score_raw = snapshot.get("object_match_score_at_mint")
    score = f"{int(score_raw)}/100" if isinstance(score_raw, (int, float)) else "NOT SCORED"
    terms = html.escape(str(snapshot.get("terms_version") or "—"))
    edition = html.escape(str(snapshot.get("edition_label") or "ONE OF ONE"))
    digest = html.escape(snapshot_hash)

    svg = f'''<svg xmlns="http://www.w3.org/2000/svg" width="1200" height="1500" viewBox="0 0 1200 1500">
<rect width="1200" height="1500" fill="#090a08"/>
<rect x="44" y="44" width="1112" height="1412" rx="18" fill="#10110e" stroke="#8b6737" stroke-width="2"/>
<rect x="72" y="72" width="1056" height="1356" rx="10" fill="none" stroke="#3e382e" stroke-width="1"/>
<text x="96" y="132" fill="#d7a75e" font-family="monospace" font-size="24" letter-spacing="5">RUINFORM / CANONICAL NFT PASSPORT</text>
<text x="96" y="246" fill="#f0ece3" font-family="sans-serif" font-weight="700" font-size="76">{public_id}</text>
<text x="96" y="322" fill="#aaa296" font-family="sans-serif" font-size="34">{title}</text>
<line x1="96" y1="370" x2="1104" y2="370" stroke="#3e382e"/>
<text x="96" y="440" fill="#776e62" font-family="monospace" font-size="20" letter-spacing="3">CERTIFICATE</text>
<text x="96" y="492" fill="#e1b46d" font-family="monospace" font-size="32">PROVENANCE / CHAIN OF CUSTODY</text>
<text x="96" y="590" fill="#776e62" font-family="monospace" font-size="20">CREATOR</text>
<text x="96" y="636" fill="#e8e1d5" font-family="monospace" font-size="28">{creator_short}</text>
<text x="96" y="728" fill="#776e62" font-family="monospace" font-size="20">LIVE PHYSICAL PROOF</text>
<text x="96" y="774" fill="#8bc69b" font-family="monospace" font-size="30">{live}</text>
<text x="628" y="728" fill="#776e62" font-family="monospace" font-size="20">OBJECT MATCH AT MINT</text>
<text x="628" y="774" fill="#e1b46d" font-family="monospace" font-size="30">{score}</text>
<text x="96" y="866" fill="#776e62" font-family="monospace" font-size="20">EDITION</text>
<text x="96" y="912" fill="#e1b46d" font-family="monospace" font-size="30">{edition}</text>
<text x="628" y="866" fill="#776e62" font-family="monospace" font-size="20">AGREEMENT</text>
<text x="628" y="912" fill="#e8e1d5" font-family="monospace" font-size="28">{terms}</text>
<line x1="96" y1="980" x2="1104" y2="980" stroke="#3e382e"/>
<text x="96" y="1044" fill="#776e62" font-family="monospace" font-size="18">IMMUTABLE SNAPSHOT SHA-256</text>
<text x="96" y="1088" fill="#aaa296" font-family="monospace" font-size="17">{digest[:32]}</text>
<text x="96" y="1122" fill="#aaa296" font-family="monospace" font-size="17">{digest[32:]}</text>
<rect x="96" y="1200" width="1008" height="130" rx="6" fill="#0b0c0a" stroke="#57482f"/>
<text x="126" y="1250" fill="#d7a75e" font-family="monospace" font-size="20">SOLANA DEVNET / CANONICAL TEST CERTIFICATE</text>
<text x="126" y="1292" fill="#8f877c" font-family="monospace" font-size="17">ONE RuF ID · ONE RUINFORM-RECOGNIZED CANONICAL NFT</text>
<text x="96" y="1390" fill="#645e55" font-family="monospace" font-size="15">Physical possession is confirmed through the RUINFORM transfer protocol; the token alone is not physical delivery.</text>
</svg>'''
    return Response(
        content=svg,
        media_type="image/svg+xml",
        headers={"Cache-Control": "public, max-age=31536000, immutable"},
    )

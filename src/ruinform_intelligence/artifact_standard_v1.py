from __future__ import annotations

import hashlib
import html
import json
import sqlite3

import httpx
from fastapi import APIRouter, HTTPException
from fastapi.responses import Response

from . import nft_devnet
from . import nft_public
from . import object_transfers
from . import release_channels


router = APIRouter(tags=["artifact-standard"])

ARTIFACT_STANDARD = "RUINFORM ARTIFACT PASSPORT v1"
ARTIFACT_SCHEMA = "ruinform-artifact-passport-v1.0"
ARTIFACT_ORIGIN = "RUINFORM NATIVE"
ASSET_CLASS = "PHYSICAL + DIGITAL ARTIFACT"
CUSTODY_MODEL = "PHYSICAL ARTIFACT + DIGITAL PASSPORT = ONE ARTIFACT"
FEE_SCHEDULE_VERSION = "RF-FEES-v1"
DEVNET_FEE_VAULT = "4gJFf1t5GmFBPFhMeX3FQgp7BiZ2scBzxRk39QNc7Kjr"
MINT_SERVICE_FEE_LAMPORTS = 100_000_000
TRANSFER_SERVICE_FEE_LAMPORTS = 10_000_000
RESALE_ROYALTY_BPS = 500
LAMPORTS_PER_SOL = 1_000_000_000

# DEVNET receives this release only. MAINNET remains explicitly gated and is not
# promoted by importing this module.
release_channels.DEVNET_RELEASE = "RF-DEV-0.5"
for capability in ("artifact-standard-v1", "fees-v1"):
    if capability not in release_channels.DEVNET_CAPABILITIES:
        release_channels.DEVNET_CAPABILITIES.append(capability)


@router.get("/v1/fee-schedule")
async def fee_schedule() -> dict:
    return {
        "version": FEE_SCHEDULE_VERSION,
        "resale_royalty_bps": RESALE_ROYALTY_BPS,
        "devnet": {
            "network": "solana-devnet",
            "enforced": True,
            "treasury_mode": "TEST_FEE_VAULT",
            "treasury_wallet": DEVNET_FEE_VAULT,
            "mint_service_fee_lamports": MINT_SERVICE_FEE_LAMPORTS,
            "mint_service_fee_sol": MINT_SERVICE_FEE_LAMPORTS / LAMPORTS_PER_SOL,
            "transfer_service_fee_lamports": TRANSFER_SERVICE_FEE_LAMPORTS,
            "transfer_service_fee_sol": TRANSFER_SERVICE_FEE_LAMPORTS / LAMPORTS_PER_SOL,
        },
        "mainnet": {
            "network": "solana-mainnet-beta",
            "enforced": False,
            "treasury_mode": "NOT_CONFIGURED",
            "treasury_wallet": None,
            "mint_service_fee_lamports": MINT_SERVICE_FEE_LAMPORTS,
            "mint_service_fee_sol": MINT_SERVICE_FEE_LAMPORTS / LAMPORTS_PER_SOL,
            "transfer_service_fee_lamports": TRANSFER_SERVICE_FEE_LAMPORTS,
            "transfer_service_fee_sol": TRANSFER_SERVICE_FEE_LAMPORTS / LAMPORTS_PER_SOL,
        },
    }


async def _require_service_fee(*, signature: str, minimum_lamports: int, operation: str) -> None:
    payload = {
        "jsonrpc": "2.0",
        "id": 91,
        "method": "getTransaction",
        "params": [
            signature,
            {"encoding": "jsonParsed", "commitment": "confirmed", "maxSupportedTransactionVersion": 0},
        ],
    }
    async with httpx.AsyncClient(timeout=14.0) as client:
        response = await client.post(nft_devnet.DEVNET_RPC, json=payload)
    response.raise_for_status()
    result = response.json().get("result")
    if not result or (result.get("meta") or {}).get("err") is not None:
        raise HTTPException(status_code=409, detail=f"Devnet {operation} transaction is not confirmed successfully")

    message = ((result.get("transaction") or {}).get("message") or {})
    keys_raw = message.get("accountKeys") or []
    keys: list[str] = []
    for entry in keys_raw:
        if isinstance(entry, str):
            keys.append(entry)
        elif isinstance(entry, dict) and entry.get("pubkey"):
            keys.append(str(entry["pubkey"]))
    try:
        index = keys.index(DEVNET_FEE_VAULT)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=f"RUINFORM {FEE_SCHEDULE_VERSION} service fee is missing from the {operation} transaction") from exc

    meta = result.get("meta") or {}
    pre = meta.get("preBalances") or []
    post = meta.get("postBalances") or []
    if index >= len(pre) or index >= len(post):
        raise HTTPException(status_code=409, detail="RUINFORM service-fee balance proof is unavailable")
    received = int(post[index]) - int(pre[index])
    if received < minimum_lamports:
        expected = minimum_lamports / LAMPORTS_PER_SOL
        got = received / LAMPORTS_PER_SOL
        raise HTTPException(status_code=409, detail=f"RUINFORM service fee is short: expected {expected:.3f} SOL, received {got:.9f} SOL")


_original_mint_verify = nft_devnet._verify_devnet_transaction
_original_transfer_verify = object_transfers._verify_transfer_transaction
_original_recipient_message = object_transfers._recipient_message
_original_rewrite_snapshot = nft_public._rewrite_intent_snapshot
_original_public_metadata = nft_public._public_metadata
_original_base_issue = nft_public._original_issue_devnet_mint_intent


async def _verify_mint_with_fee(*, signature: str, asset_address: str, wallet: str) -> None:
    await _original_mint_verify(signature=signature, asset_address=asset_address, wallet=wallet)
    await _require_service_fee(signature=signature, minimum_lamports=MINT_SERVICE_FEE_LAMPORTS, operation="Artifact Passport mint")


async def _verify_transfer_with_fee(*, signature: str, asset_address: str, from_wallet: str, to_wallet: str) -> None:
    await _original_transfer_verify(
        signature=signature,
        asset_address=asset_address,
        from_wallet=from_wallet,
        to_wallet=to_wallet,
    )
    await _require_service_fee(signature=signature, minimum_lamports=TRANSFER_SERVICE_FEE_LAMPORTS, operation="Artifact Passport transfer")


nft_devnet._verify_devnet_transaction = _verify_mint_with_fee
object_transfers._verify_transfer_transaction = _verify_transfer_with_fee


def _artifact_recipient_message(*, transfer_id: str, object_id: str, asset: str, from_wallet: str, to_wallet: str, expires_at: str) -> str:
    return "\n".join(
        [
            "RUINFORM PHYSICAL ARTIFACT RECEIPT",
            "",
            f"Transfer: {transfer_id}",
            f"Artifact Passport: {object_transfers._public_object_id(object_id)}",
            "Network: Solana Devnet",
            f"Digital Passport asset: {asset}",
            f"From: {from_wallet}",
            f"To: {to_wallet}",
            f"Expires: {expires_at}",
            f"Fee schedule: {FEE_SCHEDULE_VERSION}",
            f"Owner transfer service fee: {TRANSFER_SERVICE_FEE_LAMPORTS / LAMPORTS_PER_SOL:.2f} SOL + network cost (paid by current owner at completion)",
            "",
            "I confirm that I have received, or am physically accepting, the referenced physical artifact together with its RUINFORM Artifact Passport.",
            "I understand that the physical artifact and digital passport are intended to move as one artifact; creator provenance does not change when ownership changes.",
            "This receipt signature is not a blockchain transaction and does not cost SOL.",
        ]
    )


object_transfers._recipient_message = _artifact_recipient_message


def _persist_artifact_snapshot(intent_id: str, snapshot: dict) -> tuple[str, str]:
    canonical_json = json.dumps(snapshot, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    snapshot_hash = hashlib.sha256(canonical_json.encode("utf-8")).hexdigest()
    public_url = nft_public._metadata_url(str(snapshot["object_id"]), snapshot_hash)
    database_url = nft_public._database_url()
    if database_url:
        import psycopg

        with psycopg.connect(database_url) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE ruinform_devnet_mint_intents SET snapshot_hash=%s,snapshot_json=%s,metadata_url=%s WHERE intent_id=%s AND status='PENDING'",
                    (snapshot_hash, canonical_json, public_url, intent_id),
                )
                if cur.rowcount != 1:
                    raise HTTPException(status_code=409, detail="Artifact Passport metadata could not be locked")
            conn.commit()
    else:
        with sqlite3.connect(nft_public._sqlite_path()) as conn:
            cursor = conn.execute(
                "UPDATE ruinform_devnet_mint_intents SET snapshot_hash=?,snapshot_json=?,metadata_url=? WHERE intent_id=? AND status='PENDING'",
                (snapshot_hash, canonical_json, public_url, intent_id),
            )
            if cursor.rowcount != 1:
                raise HTTPException(status_code=409, detail="Artifact Passport metadata could not be locked")
    return snapshot_hash, public_url


def _rewrite_artifact_snapshot(intent_id: str, metadata):
    snapshot, _old_hash, _old_url = _original_rewrite_snapshot(intent_id, metadata)
    snapshot.update(
        {
            "schema": ARTIFACT_SCHEMA,
            "platform": "RUINFORM",
            "artifact_standard": ARTIFACT_STANDARD,
            "origin": ARTIFACT_ORIGIN,
            "asset_class": ASSET_CLASS,
            "physical_pair": True,
            "created_through": "RUINFORM",
            "custody_model": CUSTODY_MODEL,
            "fee_schedule_version": FEE_SCHEDULE_VERSION,
            "mint_service_fee_lamports": MINT_SERVICE_FEE_LAMPORTS,
            "transfer_service_fee_lamports": TRANSFER_SERVICE_FEE_LAMPORTS,
            "ruinform_resale_royalty_bps": RESALE_ROYALTY_BPS,
            "certificate_statement": "RUINFORM Native Artifact Passport: digital provenance and ownership-chain record paired with a physical artifact.",
            "acquisition_note": "The Artifact Passport is intended to transfer together with the paired physical artifact. A token-only or off-protocol transfer may leave physical custody unconfirmed in RUINFORM.",
        }
    )
    snapshot_hash, public_url = _persist_artifact_snapshot(intent_id, snapshot)
    return snapshot, snapshot_hash, public_url


def _issue_artifact_base(*, object_id: str, asset_address: str, wallet_session: str | None):
    result = _original_base_issue(object_id=object_id, asset_address=asset_address, wallet_session=wallet_session)
    extras = [
        {"key": "Platform", "value": "RUINFORM"},
        {"key": "Artifact Standard", "value": ARTIFACT_STANDARD},
        {"key": "Origin", "value": ARTIFACT_ORIGIN},
        {"key": "Asset Class", "value": ASSET_CLASS},
        {"key": "Physical Pair", "value": "YES"},
        {"key": "Fee Schedule", "value": FEE_SCHEDULE_VERSION},
    ]
    keys = {str(item.get("key")) for item in result.attributes}
    attributes = list(result.attributes) + [item for item in extras if item["key"] not in keys]
    return result.model_copy(update={"attributes": attributes})


nft_public._rewrite_intent_snapshot = _rewrite_artifact_snapshot
nft_public._original_issue_devnet_mint_intent = _issue_artifact_base


def _artifact_card_url(object_id: str, snapshot_hash: str) -> str:
    public_id = nft_public._public_id(object_id)
    return f"{nft_public.PUBLIC_ORIGIN}/public/artifact-passport/{public_id}/{snapshot_hash}.svg"


def _artifact_public_metadata(object_id: str, snapshot_hash: str) -> dict:
    metadata = _original_public_metadata(object_id, snapshot_hash)
    properties = metadata.get("properties") if isinstance(metadata, dict) else None
    snapshot = properties.get("ruinform") if isinstance(properties, dict) else None
    if not isinstance(snapshot, dict) or snapshot.get("schema") != ARTIFACT_SCHEMA:
        return metadata

    card_url = _artifact_card_url(object_id, snapshot_hash)
    public_description = str(snapshot.get("public_description") or "").strip()
    if not public_description:
        public_description = "A RUINFORM Native Artifact paired with a physical object. This Artifact Passport records origin, creator, physical proof and chain of custody."
    metadata["description"] = public_description
    metadata["external_url"] = str(snapshot.get("passport_url") or metadata.get("external_url") or "")
    metadata["image"] = card_url
    attributes = metadata.setdefault("attributes", [])
    existing = {str(item.get("trait_type")) for item in attributes if isinstance(item, dict)}
    extra_traits = [
        ("Platform", "RUINFORM"),
        ("Artifact Standard", ARTIFACT_STANDARD),
        ("Origin", ARTIFACT_ORIGIN),
        ("Passport ID", str(snapshot.get("object_id") or nft_public._public_id(object_id))),
        ("Asset Class", ASSET_CLASS),
        ("Physical Pair", "YES"),
        ("Created Through", "RUINFORM"),
        ("Fee Schedule", FEE_SCHEDULE_VERSION),
        ("RUINFORM Resale Royalty", "5.00%"),
    ]
    for key, value in extra_traits:
        if key not in existing:
            attributes.append({"trait_type": key, "value": value})
    if isinstance(properties, dict):
        properties["files"] = [{"uri": card_url, "type": "image/svg+xml"}]
        properties["artifact_standard"] = ARTIFACT_STANDARD
        properties["physical_pair"] = True
    return metadata


nft_public._public_metadata = _artifact_public_metadata


@router.get("/public/artifact-passport/{object_id}/{snapshot_hash}.svg")
async def public_artifact_card(object_id: str, snapshot_hash: str) -> Response:
    if len(snapshot_hash) != 64 or any(ch not in "0123456789abcdefABCDEF" for ch in snapshot_hash):
        raise HTTPException(status_code=400, detail="A valid snapshot hash is required")
    metadata = _artifact_public_metadata(object_id, snapshot_hash)
    properties = metadata.get("properties") if isinstance(metadata, dict) else None
    snapshot = properties.get("ruinform") if isinstance(properties, dict) else None
    if not isinstance(snapshot, dict) or snapshot.get("schema") != ARTIFACT_SCHEMA:
        raise HTTPException(status_code=404, detail="Artifact Passport snapshot not found")

    public_id = html.escape(str(snapshot.get("object_id") or nft_public._public_id(object_id)))
    title = html.escape(str(snapshot.get("display_name") or snapshot.get("title") or "RUINFORM ARTIFACT"))
    creator = html.escape(str(snapshot.get("creator_wallet") or "UNKNOWN"))
    creator_short = f"{creator[:6]}…{creator[-6:]}" if len(creator) > 15 else creator
    live = html.escape(str(snapshot.get("live_proof_status") or "UNKNOWN").upper())
    score_raw = snapshot.get("object_match_score_at_mint")
    score = f"{int(score_raw)}/100" if isinstance(score_raw, (int, float)) else "NOT SCORED"
    digest = html.escape(snapshot_hash)

    svg = f'''<svg xmlns="http://www.w3.org/2000/svg" width="1200" height="1500" viewBox="0 0 1200 1500">
<rect width="1200" height="1500" fill="#090a08"/><rect x="44" y="44" width="1112" height="1412" rx="18" fill="#10110e" stroke="#8b6737" stroke-width="2"/><rect x="72" y="72" width="1056" height="1356" rx="10" fill="none" stroke="#3e382e"/>
<text x="96" y="132" fill="#d7a75e" font-family="monospace" font-size="24" letter-spacing="5">RUINFORM / ARTIFACT PASSPORT</text>
<text x="96" y="222" fill="#8bc69b" font-family="monospace" font-size="21" letter-spacing="4">RUINFORM NATIVE ARTIFACT</text>
<text x="96" y="316" fill="#f0ece3" font-family="sans-serif" font-weight="700" font-size="72">{public_id}</text>
<text x="96" y="380" fill="#aaa296" font-family="sans-serif" font-size="32">{title}</text><line x1="96" y1="430" x2="1104" y2="430" stroke="#3e382e"/>
<text x="96" y="500" fill="#776e62" font-family="monospace" font-size="18">ARTIFACT STANDARD</text><text x="96" y="544" fill="#e1b46d" font-family="monospace" font-size="27">RUINFORM ARTIFACT PASSPORT v1</text>
<text x="96" y="642" fill="#776e62" font-family="monospace" font-size="18">CREATOR</text><text x="96" y="686" fill="#e8e1d5" font-family="monospace" font-size="26">{creator_short}</text>
<text x="96" y="776" fill="#776e62" font-family="monospace" font-size="18">PHYSICAL PAIR</text><text x="96" y="820" fill="#8bc69b" font-family="monospace" font-size="27">YES · LIVE PROOF {live}</text>
<text x="648" y="776" fill="#776e62" font-family="monospace" font-size="18">OBJECT MATCH AT MINT</text><text x="648" y="820" fill="#e1b46d" font-family="monospace" font-size="27">{score}</text>
<line x1="96" y1="900" x2="1104" y2="900" stroke="#3e382e"/>
<text x="96" y="972" fill="#d7a75e" font-family="monospace" font-size="22">PHYSICAL ARTIFACT + DIGITAL PASSPORT = ONE ARTIFACT</text>
<text x="96" y="1055" fill="#776e62" font-family="monospace" font-size="17">IMMUTABLE SNAPSHOT SHA-256</text><text x="96" y="1097" fill="#aaa296" font-family="monospace" font-size="16">{digest[:32]}</text><text x="96" y="1130" fill="#aaa296" font-family="monospace" font-size="16">{digest[32:]}</text>
<rect x="96" y="1210" width="1008" height="120" rx="6" fill="#0b0c0a" stroke="#57482f"/><text x="126" y="1260" fill="#d7a75e" font-family="monospace" font-size="20">SOLANA DEVNET · {FEE_SCHEDULE_VERSION}</text><text x="126" y="1300" fill="#8f877c" font-family="monospace" font-size="17">ONE ARTIFACT · ONE PASSPORT · CREATED THROUGH RUINFORM</text>
<text x="96" y="1392" fill="#645e55" font-family="monospace" font-size="15">Token-only transfers may leave physical custody unconfirmed until RUINFORM handoff is completed.</text></svg>'''
    return Response(content=svg, media_type="image/svg+xml", headers={"Cache-Control": "public, max-age=31536000, immutable"})

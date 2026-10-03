from __future__ import annotations

import hashlib
import json
import os
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Literal
from uuid import uuid4

import httpx
from fastapi import APIRouter, Header, HTTPException, Query
from pydantic import BaseModel, Field

from .object_economics_v2 import read_object_economics
from .wallet_identity import _identity_row, _validated_wallet, resolve_wallet_session


router = APIRouter(prefix="/v1/nft-passports", tags=["nft-passport-devnet"])

DEVNET_RPC = "https://api.devnet.solana.com"
CORE_PROGRAM_ID = "CoREENxT6tW1HoK8ypY1SxRMZTcVPm7R94rH4PZNhX7d"
NETWORK = "devnet"
_INTENT_TTL_MINUTES = 20


class DevnetMintIntentRequest(BaseModel):
    asset_address: str = Field(min_length=32, max_length=64)


class DevnetMintIntentResponse(BaseModel):
    intent_id: str
    object_id: str
    asset_address: str
    wallet_address: str
    network: Literal["devnet"] = "devnet"
    rpc_url: str = DEVNET_RPC
    name: str
    metadata_url: str
    snapshot_hash: str
    terms_version: str
    terms_hash: str
    royalty_bps: int
    royalty_recipient: str
    live_proof_status: str
    object_match_score: int | None = None
    verification_verdict: str | None = None
    verification_confidence: int | None = None
    expires_at_iso: str
    attributes: list[dict[str, str]]


class DevnetMintConfirmRequest(BaseModel):
    intent_id: str = Field(min_length=16, max_length=80)
    transaction_signature: str = Field(min_length=64, max_length=120)


class DevnetNftStatusResponse(BaseModel):
    object_id: str
    network: Literal["devnet"] = "devnet"
    status: Literal["NOT_MINTED", "MINTED"]
    asset_address: str | None = None
    transaction_signature: str | None = None
    owner_wallet: str | None = None
    snapshot_hash: str | None = None
    metadata_url: str | None = None
    minted_at_iso: str | None = None


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _parse_iso(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _database_url() -> str | None:
    return os.getenv("DATABASE_URL") or os.getenv("RUINFORM_DATABASE_URL")


def _sqlite_path() -> Path:
    path = Path(os.getenv("RUINFORM_DB_PATH", ".ruinform/ruinform.db"))
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _backend_object_id(object_id: str) -> str:
    value = object_id.strip().upper().replace("RUF-", "RF-")
    if not value.startswith("RF-") or not value[3:].isdigit():
        raise HTTPException(status_code=400, detail="A valid RuF Object ID is required")
    return value


def _public_object_id(object_id: str) -> str:
    return object_id.replace("RF-", "RuF-", 1)


def _ensure_sqlite_schema(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS ruinform_devnet_mint_intents (
            intent_id TEXT PRIMARY KEY,
            object_id TEXT NOT NULL,
            asset_address TEXT NOT NULL UNIQUE,
            wallet_address TEXT NOT NULL,
            status TEXT NOT NULL,
            snapshot_hash TEXT NOT NULL,
            snapshot_json TEXT NOT NULL,
            metadata_url TEXT NOT NULL,
            created_at_iso TEXT NOT NULL,
            expires_at_iso TEXT NOT NULL,
            transaction_signature TEXT,
            confirmed_at_iso TEXT
        )
        """
    )
    for statement in (
        "ALTER TABLE ruinform_nft_passports ADD COLUMN network TEXT",
        "ALTER TABLE ruinform_nft_passports ADD COLUMN transaction_signature TEXT",
        "ALTER TABLE ruinform_nft_passports ADD COLUMN snapshot_hash TEXT",
        "ALTER TABLE ruinform_nft_passports ADD COLUMN owner_wallet TEXT",
        "ALTER TABLE ruinform_nft_passports ADD COLUMN metadata_uri TEXT",
    ):
        try:
            conn.execute(statement)
        except sqlite3.OperationalError as exc:
            if "duplicate column name" not in str(exc).lower():
                raise


def _ensure_postgres_schema(conn) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS ruinform_devnet_mint_intents (
                intent_id TEXT PRIMARY KEY,
                object_id TEXT NOT NULL,
                asset_address TEXT NOT NULL UNIQUE,
                wallet_address TEXT NOT NULL,
                status TEXT NOT NULL,
                snapshot_hash TEXT NOT NULL,
                snapshot_json TEXT NOT NULL,
                metadata_url TEXT NOT NULL,
                created_at_iso TEXT NOT NULL,
                expires_at_iso TEXT NOT NULL,
                transaction_signature TEXT,
                confirmed_at_iso TEXT
            )
            """
        )
        cur.execute("ALTER TABLE ruinform_nft_passports ADD COLUMN IF NOT EXISTS network TEXT")
        cur.execute("ALTER TABLE ruinform_nft_passports ADD COLUMN IF NOT EXISTS transaction_signature TEXT")
        cur.execute("ALTER TABLE ruinform_nft_passports ADD COLUMN IF NOT EXISTS snapshot_hash TEXT")
        cur.execute("ALTER TABLE ruinform_nft_passports ADD COLUMN IF NOT EXISTS owner_wallet TEXT")
        cur.execute("ALTER TABLE ruinform_nft_passports ADD COLUMN IF NOT EXISTS metadata_uri TEXT")
    conn.commit()


def _read_raw_object(object_id: str) -> dict:
    database_url = _database_url()
    row = None
    if database_url:
        import psycopg

        with psycopg.connect(database_url) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT payload_json FROM ruinform_objects WHERE object_id=%s", (object_id,))
                row = cur.fetchone()
    else:
        with sqlite3.connect(_sqlite_path()) as conn:
            row = conn.execute("SELECT payload_json FROM ruinform_objects WHERE object_id=?", (object_id,)).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Object Passport not found")
    try:
        return json.loads(row[0])
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=500, detail="Object Passport payload is unreadable") from exc


def _read_minted_row(object_id: str) -> tuple | None:
    database_url = _database_url()
    if database_url:
        import psycopg

        with psycopg.connect(database_url) as conn:
            _ensure_postgres_schema(conn)
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT status,mint_address,transaction_signature,owner_wallet,snapshot_hash,metadata_uri,minted_at_iso FROM ruinform_nft_passports WHERE object_id=%s",
                    (object_id,),
                )
                return cur.fetchone()
    with sqlite3.connect(_sqlite_path()) as conn:
        _ensure_sqlite_schema(conn)
        return conn.execute(
            "SELECT status,mint_address,transaction_signature,owner_wallet,snapshot_hash,metadata_uri,minted_at_iso FROM ruinform_nft_passports WHERE object_id=?",
            (object_id,),
        ).fetchone()


def _mint_status(object_id: str) -> DevnetNftStatusResponse:
    backend_id = _backend_object_id(object_id)
    row = _read_minted_row(backend_id)
    if not row or str(row[0]) != "MINTED":
        return DevnetNftStatusResponse(object_id=_public_object_id(backend_id), status="NOT_MINTED")
    return DevnetNftStatusResponse(
        object_id=_public_object_id(backend_id),
        status="MINTED",
        asset_address=str(row[1]) if row[1] else None,
        transaction_signature=str(row[2]) if row[2] else None,
        owner_wallet=str(row[3]) if row[3] else None,
        snapshot_hash=str(row[4]) if row[4] else None,
        metadata_url=str(row[5]) if row[5] else None,
        minted_at_iso=str(row[6]) if row[6] else None,
    )


def _snapshot(*, object_id: str, wallet: str, asset_address: str) -> tuple[dict, object]:
    raw = _read_raw_object(object_id)
    economics = read_object_economics(object_id)
    if economics.creator_wallet != wallet:
        raise HTTPException(status_code=403, detail="Only the registered creator can mint the initial canonical NFT Passport")
    if not economics.eligible_to_mint:
        raise HTTPException(status_code=409, detail={"message": "NFT Passport is not eligible to mint yet", "blockers": economics.blockers})

    live_proof = str(raw.get("verification_proof_status") or "unknown").lower()
    score_raw = raw.get("verification_score")
    score = int(score_raw) if isinstance(score_raw, (int, float)) else None
    confidence_raw = raw.get("verification_confidence")
    confidence = int(confidence_raw) if isinstance(confidence_raw, (int, float)) else None
    verdict = str(raw.get("verification_verdict")) if raw.get("verification_verdict") is not None else None
    title = str(raw.get("title") or _public_object_id(object_id))
    public_id = _public_object_id(object_id)

    snapshot = {
        "schema": "ruinform-canonical-nft-passport-v0.1",
        "network": NETWORK,
        "object_id": public_id,
        "title": title,
        "creator_wallet": wallet,
        "initial_owner_wallet": wallet,
        "asset_address": asset_address,
        "terms_version": economics.terms_version,
        "terms_hash": economics.terms_hash,
        "ruinform_resale_royalty_bps": economics.royalty_bps,
        "live_proof_status": live_proof,
        "object_match_score_at_mint": score,
        "verification_verdict_at_mint": verdict,
        "verification_confidence_at_mint": confidence,
        "verification_updated_at_iso": raw.get("verification_updated_at_iso"),
        "passport_url": f"https://ruinform.higgsfield.app/object/{public_id}",
        "certificate_statement": "Canonical RUINFORM digital certificate of provenance and ownership-chain continuity for the registered physical object. Physical possession is confirmed through the RUINFORM transfer protocol, not by the token alone.",
    }
    return snapshot, economics


def issue_devnet_mint_intent(
    *,
    object_id: str,
    asset_address: str,
    wallet_session: str | None,
) -> DevnetMintIntentResponse:
    backend_id = _backend_object_id(object_id)
    wallet = resolve_wallet_session(wallet_session).wallet_address
    asset_address, _ = _validated_wallet(asset_address)
    existing = _mint_status(backend_id)
    if existing.status == "MINTED":
        raise HTTPException(status_code=409, detail="The canonical NFT Passport for this RuF Object ID is already minted")

    snapshot, economics = _snapshot(object_id=backend_id, wallet=wallet, asset_address=asset_address)
    canonical_json = json.dumps(snapshot, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    snapshot_hash = hashlib.sha256(canonical_json.encode("utf-8")).hexdigest()
    public_id = _public_object_id(backend_id)
    metadata_url = f"https://ruinform.higgsfield.app/api/nft-passport-metadata?objectId={public_id}&snapshot={snapshot_hash}"
    now = _utc_now()
    expires = now + timedelta(minutes=_INTENT_TTL_MINUTES)
    intent_id = uuid4().hex

    database_url = _database_url()
    if database_url:
        import psycopg

        with psycopg.connect(database_url) as conn:
            _ensure_postgres_schema(conn)
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO ruinform_devnet_mint_intents(intent_id,object_id,asset_address,wallet_address,status,snapshot_hash,snapshot_json,metadata_url,created_at_iso,expires_at_iso) VALUES (%s,%s,%s,%s,'PENDING',%s,%s,%s,%s,%s)",
                    (intent_id, backend_id, asset_address, wallet, snapshot_hash, canonical_json, metadata_url, _iso(now), _iso(expires)),
                )
            conn.commit()
    else:
        with sqlite3.connect(_sqlite_path()) as conn:
            _ensure_sqlite_schema(conn)
            conn.execute(
                "INSERT INTO ruinform_devnet_mint_intents(intent_id,object_id,asset_address,wallet_address,status,snapshot_hash,snapshot_json,metadata_url,created_at_iso,expires_at_iso) VALUES (?,?,?,?,'PENDING',?,?,?,?,?)",
                (intent_id, backend_id, asset_address, wallet, snapshot_hash, canonical_json, metadata_url, _iso(now), _iso(expires)),
            )

    score = snapshot["object_match_score_at_mint"]
    attributes = [
        {"key": "RuF ID", "value": public_id},
        {"key": "Certificate", "value": "CANONICAL PROVENANCE"},
        {"key": "Creator", "value": wallet},
        {"key": "Agreement", "value": economics.terms_version},
        {"key": "Terms SHA256", "value": economics.terms_hash},
        {"key": "Royalty BPS", "value": str(economics.royalty_bps)},
        {"key": "Live Proof", "value": str(snapshot["live_proof_status"]).upper()},
        {"key": "Object Match", "value": f"{score}/100" if score is not None else "NOT SCORED"},
        {"key": "Snapshot SHA256", "value": snapshot_hash},
    ]
    return DevnetMintIntentResponse(
        intent_id=intent_id,
        object_id=public_id,
        asset_address=asset_address,
        wallet_address=wallet,
        name=f"RUINFORM Passport · {public_id}",
        metadata_url=metadata_url,
        snapshot_hash=snapshot_hash,
        terms_version=economics.terms_version,
        terms_hash=economics.terms_hash,
        royalty_bps=economics.royalty_bps,
        royalty_recipient=wallet,
        live_proof_status=str(snapshot["live_proof_status"]),
        object_match_score=score,
        verification_verdict=snapshot["verification_verdict_at_mint"],
        verification_confidence=snapshot["verification_confidence_at_mint"],
        expires_at_iso=_iso(expires),
        attributes=attributes,
    )


def _load_intent(intent_id: str, object_id: str) -> tuple:
    database_url = _database_url()
    if database_url:
        import psycopg

        with psycopg.connect(database_url) as conn:
            _ensure_postgres_schema(conn)
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT asset_address,wallet_address,status,snapshot_hash,snapshot_json,metadata_url,expires_at_iso FROM ruinform_devnet_mint_intents WHERE intent_id=%s AND object_id=%s",
                    (intent_id, object_id),
                )
                row = cur.fetchone()
    else:
        with sqlite3.connect(_sqlite_path()) as conn:
            _ensure_sqlite_schema(conn)
            row = conn.execute(
                "SELECT asset_address,wallet_address,status,snapshot_hash,snapshot_json,metadata_url,expires_at_iso FROM ruinform_devnet_mint_intents WHERE intent_id=? AND object_id=?",
                (intent_id, object_id),
            ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Devnet mint intent not found")
    return row


async def _verify_devnet_transaction(*, signature: str, asset_address: str, wallet: str) -> None:
    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "getTransaction",
        "params": [signature, {"encoding": "json", "commitment": "confirmed", "maxSupportedTransactionVersion": 0}],
    }
    account_payload = {
        "jsonrpc": "2.0",
        "id": 2,
        "method": "getAccountInfo",
        "params": [asset_address, {"encoding": "base64", "commitment": "confirmed"}],
    }
    async with httpx.AsyncClient(timeout=14.0) as client:
        tx_response, account_response = await client.post(DEVNET_RPC, json=payload), await client.post(DEVNET_RPC, json=account_payload)
    tx_response.raise_for_status()
    account_response.raise_for_status()
    tx_result = tx_response.json().get("result")
    if not tx_result or (tx_result.get("meta") or {}).get("err") is not None:
        raise HTTPException(status_code=409, detail="The Devnet mint transaction is not confirmed successfully")
    keys_raw = (((tx_result.get("transaction") or {}).get("message") or {}).get("accountKeys") or [])
    keys: list[str] = []
    for entry in keys_raw:
        if isinstance(entry, str):
            keys.append(entry)
        elif isinstance(entry, dict) and entry.get("pubkey"):
            keys.append(str(entry["pubkey"]))
    for required in (asset_address, wallet, CORE_PROGRAM_ID):
        if required not in keys:
            raise HTTPException(status_code=409, detail="The confirmed transaction does not match the reserved RUINFORM Core mint")
    account_value = (account_response.json().get("result") or {}).get("value")
    if not account_value or str(account_value.get("owner")) != CORE_PROGRAM_ID:
        raise HTTPException(status_code=409, detail="Reserved asset address is not an MPL Core Asset on Solana Devnet")


async def confirm_devnet_mint(
    *,
    object_id: str,
    payload: DevnetMintConfirmRequest,
    wallet_session: str | None,
) -> DevnetNftStatusResponse:
    backend_id = _backend_object_id(object_id)
    wallet = resolve_wallet_session(wallet_session).wallet_address
    row = _load_intent(payload.intent_id, backend_id)
    asset_address, intent_wallet, status, snapshot_hash, _snapshot_json, metadata_url, expires_at_iso = row
    if str(intent_wallet) != wallet:
        raise HTTPException(status_code=403, detail="This mint intent belongs to a different wallet")
    if str(status) == "MINTED":
        return _mint_status(backend_id)
    if _parse_iso(str(expires_at_iso)) <= _utc_now():
        raise HTTPException(status_code=410, detail="Devnet mint intent expired; create a fresh mint request")
    existing = _mint_status(backend_id)
    if existing.status == "MINTED":
        raise HTTPException(status_code=409, detail="The canonical NFT Passport for this RuF Object ID is already minted")

    await _verify_devnet_transaction(signature=payload.transaction_signature, asset_address=str(asset_address), wallet=wallet)
    now = _iso(_utc_now())
    economics = read_object_economics(backend_id)

    database_url = _database_url()
    if database_url:
        import psycopg

        with psycopg.connect(database_url) as conn:
            _ensure_postgres_schema(conn)
            with conn.cursor() as cur:
                cur.execute("SELECT status FROM ruinform_nft_passports WHERE object_id=%s FOR UPDATE", (backend_id,))
                nft_row = cur.fetchone()
                if nft_row and str(nft_row[0]) == "MINTED":
                    raise HTTPException(status_code=409, detail="The canonical NFT Passport was already minted by another request")
                if nft_row:
                    cur.execute(
                        "UPDATE ruinform_nft_passports SET chain='solana',network=%s,status='MINTED',mint_address=%s,royalty_bps=%s,terms_hash=%s,minted_at_iso=%s,transaction_signature=%s,snapshot_hash=%s,owner_wallet=%s,metadata_uri=%s WHERE object_id=%s AND status<>'MINTED'",
                        (NETWORK, asset_address, economics.royalty_bps, economics.terms_hash, now, payload.transaction_signature, snapshot_hash, wallet, metadata_url, backend_id),
                    )
                    if cur.rowcount != 1:
                        raise HTTPException(status_code=409, detail="Canonical NFT mint lock was already consumed")
                else:
                    cur.execute(
                        "INSERT INTO ruinform_nft_passports(object_id,chain,network,status,mint_address,royalty_bps,terms_hash,minted_at_iso,transaction_signature,snapshot_hash,owner_wallet,metadata_uri) VALUES (%s,'solana',%s,'MINTED',%s,%s,%s,%s,%s,%s,%s,%s)",
                        (backend_id, NETWORK, asset_address, economics.royalty_bps, economics.terms_hash, now, payload.transaction_signature, snapshot_hash, wallet, metadata_url),
                    )
                cur.execute(
                    "UPDATE ruinform_devnet_mint_intents SET status='MINTED',transaction_signature=%s,confirmed_at_iso=%s WHERE intent_id=%s",
                    (payload.transaction_signature, now, payload.intent_id),
                )
                cur.execute("SELECT owner_wallet FROM ruinform_object_identity WHERE object_id=%s FOR UPDATE", (backend_id,))
                owner_row = cur.fetchone()
                if owner_row and owner_row[0] and str(owner_row[0]) != wallet:
                    raise HTTPException(status_code=409, detail="Object Passport already records a different current owner")
                cur.execute(
                    "UPDATE ruinform_object_identity SET owner_wallet=COALESCE(owner_wallet,%s),ownership_claimed_at_iso=COALESCE(ownership_claimed_at_iso,%s) WHERE object_id=%s",
                    (wallet, now, backend_id),
                )
            conn.commit()
    else:
        with sqlite3.connect(_sqlite_path()) as conn:
            _ensure_sqlite_schema(conn)
            nft_row = conn.execute("SELECT status FROM ruinform_nft_passports WHERE object_id=?", (backend_id,)).fetchone()
            if nft_row and str(nft_row[0]) == "MINTED":
                raise HTTPException(status_code=409, detail="The canonical NFT Passport was already minted by another request")
            if nft_row:
                cursor = conn.execute(
                    "UPDATE ruinform_nft_passports SET chain='solana',network=?,status='MINTED',mint_address=?,royalty_bps=?,terms_hash=?,minted_at_iso=?,transaction_signature=?,snapshot_hash=?,owner_wallet=?,metadata_uri=? WHERE object_id=? AND status<>'MINTED'",
                    (NETWORK, asset_address, economics.royalty_bps, economics.terms_hash, now, payload.transaction_signature, snapshot_hash, wallet, metadata_url, backend_id),
                )
                if cursor.rowcount != 1:
                    raise HTTPException(status_code=409, detail="Canonical NFT mint lock was already consumed")
            else:
                conn.execute(
                    "INSERT INTO ruinform_nft_passports(object_id,chain,network,status,mint_address,royalty_bps,terms_hash,minted_at_iso,transaction_signature,snapshot_hash,owner_wallet,metadata_uri) VALUES (?,'solana',?,'MINTED',?,?,?,?,?,?,?,?,?)",
                    (backend_id, NETWORK, asset_address, economics.royalty_bps, economics.terms_hash, now, payload.transaction_signature, snapshot_hash, wallet, metadata_url),
                )
            conn.execute(
                "UPDATE ruinform_devnet_mint_intents SET status='MINTED',transaction_signature=?,confirmed_at_iso=? WHERE intent_id=?",
                (payload.transaction_signature, now, payload.intent_id),
            )
            owner_row = conn.execute("SELECT owner_wallet FROM ruinform_object_identity WHERE object_id=?", (backend_id,)).fetchone()
            if owner_row and owner_row[0] and str(owner_row[0]) != wallet:
                raise HTTPException(status_code=409, detail="Object Passport already records a different current owner")
            conn.execute(
                "UPDATE ruinform_object_identity SET owner_wallet=COALESCE(owner_wallet,?),ownership_claimed_at_iso=COALESCE(ownership_claimed_at_iso,?) WHERE object_id=?",
                (wallet, now, backend_id),
            )

    return _mint_status(backend_id)


def read_snapshot_metadata(object_id: str, snapshot_hash: str) -> dict:
    backend_id = _backend_object_id(object_id)
    database_url = _database_url()
    row = None
    if database_url:
        import psycopg

        with psycopg.connect(database_url) as conn:
            _ensure_postgres_schema(conn)
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT snapshot_json FROM ruinform_devnet_mint_intents WHERE object_id=%s AND snapshot_hash=%s ORDER BY created_at_iso DESC LIMIT 1",
                    (backend_id, snapshot_hash),
                )
                row = cur.fetchone()
    else:
        with sqlite3.connect(_sqlite_path()) as conn:
            _ensure_sqlite_schema(conn)
            row = conn.execute(
                "SELECT snapshot_json FROM ruinform_devnet_mint_intents WHERE object_id=? AND snapshot_hash=? ORDER BY created_at_iso DESC LIMIT 1",
                (backend_id, snapshot_hash),
            ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="NFT Passport metadata snapshot not found")
    snapshot = json.loads(row[0])
    score = snapshot.get("object_match_score_at_mint")
    public_id = snapshot["object_id"]
    image_url = f"https://ruinform.higgsfield.app/api/object-passport-card.svg?objectId={public_id}"
    return {
        "name": f"RUINFORM Passport · {public_id}",
        "description": snapshot["certificate_statement"],
        "image": image_url,
        "external_url": snapshot["passport_url"],
        "category": "image",
        "attributes": [
            {"trait_type": "RuF Object ID", "value": public_id},
            {"trait_type": "Network", "value": NETWORK},
            {"trait_type": "Certificate", "value": "Canonical provenance"},
            {"trait_type": "Live Proof", "value": str(snapshot.get("live_proof_status", "unknown")).upper()},
            {"trait_type": "Object Match At Mint", "value": f"{score}/100" if score is not None else "Not scored"},
            {"trait_type": "Verification Verdict", "value": snapshot.get("verification_verdict_at_mint") or "unknown"},
            {"trait_type": "RUINFORM Royalty", "value": "5.00%"},
            {"trait_type": "Agreement", "value": snapshot["terms_version"]},
            {"trait_type": "Snapshot SHA-256", "value": snapshot_hash},
        ],
        "properties": {
            "category": "image",
            "files": [{"uri": image_url, "type": "image/svg+xml"}],
            "ruinform": snapshot,
        },
    }


@router.get("/{object_id}/devnet", response_model=DevnetNftStatusResponse)
async def get_devnet_nft_status(object_id: str) -> DevnetNftStatusResponse:
    return _mint_status(object_id)


@router.post("/{object_id}/devnet/intent", response_model=DevnetMintIntentResponse)
async def create_devnet_mint_intent(
    object_id: str,
    payload: DevnetMintIntentRequest,
    x_ruinform_wallet_session: str | None = Header(default=None, alias="x-ruinform-wallet-session"),
) -> DevnetMintIntentResponse:
    return issue_devnet_mint_intent(object_id=object_id, asset_address=payload.asset_address, wallet_session=x_ruinform_wallet_session)


@router.post("/{object_id}/devnet/confirm", response_model=DevnetNftStatusResponse)
async def confirm_devnet_nft_mint(
    object_id: str,
    payload: DevnetMintConfirmRequest,
    x_ruinform_wallet_session: str | None = Header(default=None, alias="x-ruinform-wallet-session"),
) -> DevnetNftStatusResponse:
    return await confirm_devnet_mint(object_id=object_id, payload=payload, wallet_session=x_ruinform_wallet_session)


@router.get("/{object_id}/devnet/metadata")
async def get_devnet_nft_metadata(
    object_id: str,
    snapshot: str = Query(min_length=64, max_length=64),
) -> dict:
    return read_snapshot_metadata(object_id, snapshot)

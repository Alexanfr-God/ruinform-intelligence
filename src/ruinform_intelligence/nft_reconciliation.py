from __future__ import annotations

import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

import httpx
from fastapi import APIRouter, Header, HTTPException

from . import nft_devnet
from .object_economics_v2 import read_object_economics
from .wallet_identity import _identity_row, resolve_wallet_session


router = APIRouter(prefix="/v1/nft-passports", tags=["nft-passport-reconciliation"])


def _database_url() -> str | None:
    return os.getenv("DATABASE_URL") or os.getenv("RUINFORM_DATABASE_URL")


def _sqlite_path() -> Path:
    path = Path(os.getenv("RUINFORM_DB_PATH", ".ruinform/ruinform.db"))
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _pending_intents(object_id: str, wallet: str) -> list[tuple[str, str, str]]:
    database_url = _database_url()
    if database_url:
        import psycopg

        with psycopg.connect(database_url) as conn:
            nft_devnet._ensure_postgres_schema(conn)
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT intent_id,asset_address,created_at_iso FROM ruinform_devnet_mint_intents WHERE object_id=%s AND wallet_address=%s AND status='PENDING' ORDER BY created_at_iso ASC",
                    (object_id, wallet),
                )
                return [(str(a), str(b), str(c)) for a, b, c in cur.fetchall()]
    with sqlite3.connect(_sqlite_path()) as conn:
        nft_devnet._ensure_sqlite_schema(conn)
        rows = conn.execute(
            "SELECT intent_id,asset_address,created_at_iso FROM ruinform_devnet_mint_intents WHERE object_id=? AND wallet_address=? AND status='PENDING' ORDER BY created_at_iso ASC",
            (object_id, wallet),
        ).fetchall()
        return [(str(a), str(b), str(c)) for a, b, c in rows]


async def _confirmed_signature(asset_address: str, wallet: str) -> tuple[str, int] | None:
    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "getSignaturesForAddress",
        "params": [asset_address, {"limit": 8}],
    }
    async with httpx.AsyncClient(timeout=12.0) as client:
        response = await client.post(nft_devnet.DEVNET_RPC, json=payload)
    response.raise_for_status()
    rows = response.json().get("result") or []
    candidates: list[tuple[str, int]] = []
    for row in rows:
        if not isinstance(row, dict) or row.get("err") is not None or not row.get("signature"):
            continue
        signature = str(row["signature"])
        slot = int(row.get("slot") or 0)
        try:
            await nft_devnet._verify_devnet_transaction(
                signature=signature,
                asset_address=asset_address,
                wallet=wallet,
            )
        except Exception:
            continue
        candidates.append((signature, slot))
    return min(candidates, key=lambda item: item[1]) if candidates else None


def _ensure_duplicate_table_postgres(conn) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS ruinform_devnet_duplicate_assets (
                object_id TEXT NOT NULL,
                asset_address TEXT PRIMARY KEY,
                transaction_signature TEXT NOT NULL,
                detected_at_iso TEXT NOT NULL,
                reason TEXT NOT NULL
            )
            """
        )
    conn.commit()


def _ensure_duplicate_table_sqlite(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS ruinform_devnet_duplicate_assets (
            object_id TEXT NOT NULL,
            asset_address TEXT PRIMARY KEY,
            transaction_signature TEXT NOT NULL,
            detected_at_iso TEXT NOT NULL,
            reason TEXT NOT NULL
        )
        """
    )


def _finalize_recovered(
    *,
    object_id: str,
    wallet: str,
    intent_id: str,
    asset_address: str,
    transaction_signature: str,
    duplicates: list[tuple[str, str, str]],
) -> nft_devnet.DevnetNftStatusResponse:
    row = nft_devnet._load_intent(intent_id, object_id)
    stored_asset, intent_wallet, _status, snapshot_hash, _snapshot_json, metadata_url, _expires = row
    if str(stored_asset) != asset_address or str(intent_wallet) != wallet:
        raise HTTPException(status_code=409, detail="Recovered Devnet mint does not match its RUINFORM intent")

    economics = read_object_economics(object_id)
    now = _now_iso()
    database_url = _database_url()
    if database_url:
        import psycopg

        with psycopg.connect(database_url) as conn:
            nft_devnet._ensure_postgres_schema(conn)
            _ensure_duplicate_table_postgres(conn)
            with conn.cursor() as cur:
                cur.execute("SELECT status FROM ruinform_nft_passports WHERE object_id=%s FOR UPDATE", (object_id,))
                existing = cur.fetchone()
                if existing and str(existing[0]) == "MINTED":
                    return nft_devnet._mint_status(object_id)
                if existing:
                    cur.execute(
                        "UPDATE ruinform_nft_passports SET chain='solana',network=%s,status='MINTED',mint_address=%s,royalty_bps=%s,terms_hash=%s,minted_at_iso=%s,transaction_signature=%s,snapshot_hash=%s,owner_wallet=%s,metadata_uri=%s WHERE object_id=%s AND status<>'MINTED'",
                        (nft_devnet.NETWORK, asset_address, economics.royalty_bps, economics.terms_hash, now, transaction_signature, snapshot_hash, wallet, metadata_url, object_id),
                    )
                else:
                    cur.execute(
                        "INSERT INTO ruinform_nft_passports(object_id,chain,network,status,mint_address,royalty_bps,terms_hash,minted_at_iso,transaction_signature,snapshot_hash,owner_wallet,metadata_uri) VALUES (%s,'solana',%s,'MINTED',%s,%s,%s,%s,%s,%s,%s,%s)",
                        (object_id, nft_devnet.NETWORK, asset_address, economics.royalty_bps, economics.terms_hash, now, transaction_signature, snapshot_hash, wallet, metadata_url),
                    )
                cur.execute(
                    "UPDATE ruinform_devnet_mint_intents SET status='MINTED',transaction_signature=%s,confirmed_at_iso=%s WHERE intent_id=%s",
                    (transaction_signature, now, intent_id),
                )
                for duplicate_intent, duplicate_asset, duplicate_signature in duplicates:
                    cur.execute(
                        "UPDATE ruinform_devnet_mint_intents SET status='DUPLICATE',transaction_signature=%s,confirmed_at_iso=%s WHERE intent_id=%s AND status='PENDING'",
                        (duplicate_signature, now, duplicate_intent),
                    )
                    cur.execute(
                        "INSERT INTO ruinform_devnet_duplicate_assets(object_id,asset_address,transaction_signature,detected_at_iso,reason) VALUES (%s,%s,%s,%s,%s) ON CONFLICT(asset_address) DO NOTHING",
                        (object_id, duplicate_asset, duplicate_signature, now, "Confirmed after canonical asset had already been created"),
                    )
                cur.execute(
                    "UPDATE ruinform_object_identity SET owner_wallet=COALESCE(owner_wallet,%s),ownership_claimed_at_iso=COALESCE(ownership_claimed_at_iso,%s) WHERE object_id=%s",
                    (wallet, now, object_id),
                )
            conn.commit()
    else:
        with sqlite3.connect(_sqlite_path()) as conn:
            nft_devnet._ensure_sqlite_schema(conn)
            _ensure_duplicate_table_sqlite(conn)
            existing = conn.execute("SELECT status FROM ruinform_nft_passports WHERE object_id=?", (object_id,)).fetchone()
            if existing and str(existing[0]) == "MINTED":
                return nft_devnet._mint_status(object_id)
            if existing:
                conn.execute(
                    "UPDATE ruinform_nft_passports SET chain='solana',network=?,status='MINTED',mint_address=?,royalty_bps=?,terms_hash=?,minted_at_iso=?,transaction_signature=?,snapshot_hash=?,owner_wallet=?,metadata_uri=? WHERE object_id=? AND status<>'MINTED'",
                    (nft_devnet.NETWORK, asset_address, economics.royalty_bps, economics.terms_hash, now, transaction_signature, snapshot_hash, wallet, metadata_url, object_id),
                )
            else:
                conn.execute(
                    "INSERT INTO ruinform_nft_passports(object_id,chain,network,status,mint_address,royalty_bps,terms_hash,minted_at_iso,transaction_signature,snapshot_hash,owner_wallet,metadata_uri) VALUES (?,'solana',?,'MINTED',?,?,?,?,?,?,?,?,?)",
                    (object_id, nft_devnet.NETWORK, asset_address, economics.royalty_bps, economics.terms_hash, now, transaction_signature, snapshot_hash, wallet, metadata_url),
                )
            conn.execute("UPDATE ruinform_devnet_mint_intents SET status='MINTED',transaction_signature=?,confirmed_at_iso=? WHERE intent_id=?", (transaction_signature, now, intent_id))
            for duplicate_intent, duplicate_asset, duplicate_signature in duplicates:
                conn.execute("UPDATE ruinform_devnet_mint_intents SET status='DUPLICATE',transaction_signature=?,confirmed_at_iso=? WHERE intent_id=? AND status='PENDING'", (duplicate_signature, now, duplicate_intent))
                conn.execute("INSERT OR IGNORE INTO ruinform_devnet_duplicate_assets(object_id,asset_address,transaction_signature,detected_at_iso,reason) VALUES (?,?,?,?,?)", (object_id, duplicate_asset, duplicate_signature, now, "Confirmed after canonical asset had already been created"))
            conn.execute("UPDATE ruinform_object_identity SET owner_wallet=COALESCE(owner_wallet,?),ownership_claimed_at_iso=COALESCE(ownership_claimed_at_iso,?) WHERE object_id=?", (wallet, now, object_id))

    return nft_devnet._mint_status(object_id)


@router.post("/{object_id}/devnet/reconcile", response_model=nft_devnet.DevnetNftStatusResponse)
async def reconcile_devnet_mint(
    object_id: str,
    x_ruinform_wallet_session: str | None = Header(default=None, alias="x-ruinform-wallet-session"),
) -> nft_devnet.DevnetNftStatusResponse:
    backend_id = nft_devnet._backend_object_id(object_id)
    wallet = resolve_wallet_session(x_ruinform_wallet_session).wallet_address
    identity = _identity_row(backend_id)
    if not identity.creator_wallet or identity.creator_wallet != wallet:
        raise HTTPException(status_code=403, detail="Only the registered creator can reconcile this Devnet mint")

    current = nft_devnet._mint_status(backend_id)
    if current.status == "MINTED":
        return current

    found: list[tuple[int, str, str, str]] = []
    for intent_id, asset_address, _created_at in _pending_intents(backend_id, wallet):
        confirmed = await _confirmed_signature(asset_address, wallet)
        if confirmed:
            signature, slot = confirmed
            found.append((slot, intent_id, asset_address, signature))

    if not found:
        return current

    found.sort(key=lambda item: item[0])
    _slot, canonical_intent, canonical_asset, canonical_signature = found[0]
    duplicates = [(intent_id, asset, signature) for _slot, intent_id, asset, signature in found[1:]]
    return _finalize_recovered(
        object_id=backend_id,
        wallet=wallet,
        intent_id=canonical_intent,
        asset_address=canonical_asset,
        transaction_signature=canonical_signature,
        duplicates=duplicates,
    )

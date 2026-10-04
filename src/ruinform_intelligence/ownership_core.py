from __future__ import annotations

import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal
from uuid import uuid4

import httpx
from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, Field

from .nft_devnet import DEVNET_RPC
from .object_transfers import (
    _backend_object_id,
    _canonical_nft,
    _public_object_id,
    _verify_transfer_transaction,
)
from .wallet_identity import _identity_row, _validated_wallet, resolve_wallet_session


router = APIRouter(prefix="/v1/ownership", tags=["ownership"])
NETWORK = "devnet"


class OwnershipEventResponse(BaseModel):
    event_id: str
    object_id: str
    network: Literal["devnet"] = "devnet"
    asset_address: str
    event_type: Literal["MINT", "RUINFORM_TRANSFER", "EXTERNAL_TRANSFER"]
    from_wallet: str | None = None
    to_wallet: str
    transaction_signature: str | None = None
    detected_at_iso: str


class OwnershipStateResponse(BaseModel):
    object_id: str
    network: Literal["devnet"] = "devnet"
    asset_address: str
    current_owner: str
    history: list[OwnershipEventResponse]


class DirectTransferRequest(BaseModel):
    recipient_wallet: str = Field(min_length=32, max_length=64)
    transaction_signature: str = Field(min_length=64, max_length=120)


class ReconcileOwnerRequest(BaseModel):
    observed_owner: str = Field(min_length=32, max_length=64)


def _database_url() -> str | None:
    return os.getenv("DATABASE_URL") or os.getenv("RUINFORM_DATABASE_URL")


def _sqlite_path() -> Path:
    path = Path(os.getenv("RUINFORM_DB_PATH", ".ruinform/ruinform.db"))
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _ensure_postgres_schema(conn) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS ruinform_ownership_events (
                event_id TEXT PRIMARY KEY,
                object_id TEXT NOT NULL,
                network TEXT NOT NULL,
                asset_address TEXT NOT NULL,
                event_type TEXT NOT NULL,
                from_wallet TEXT,
                to_wallet TEXT NOT NULL,
                transaction_signature TEXT,
                detected_at_iso TEXT NOT NULL
            )
            """
        )
        cur.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_ruinform_ownership_tx ON ruinform_ownership_events(transaction_signature) WHERE transaction_signature IS NOT NULL")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_ruinform_ownership_object ON ruinform_ownership_events(object_id,network,detected_at_iso ASC)")
    conn.commit()


def _ensure_sqlite_schema(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS ruinform_ownership_events (
            event_id TEXT PRIMARY KEY,
            object_id TEXT NOT NULL,
            network TEXT NOT NULL,
            asset_address TEXT NOT NULL,
            event_type TEXT NOT NULL,
            from_wallet TEXT,
            to_wallet TEXT NOT NULL,
            transaction_signature TEXT,
            detected_at_iso TEXT NOT NULL
        )
        """
    )
    conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_ruinform_ownership_tx ON ruinform_ownership_events(transaction_signature) WHERE transaction_signature IS NOT NULL")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_ruinform_ownership_object ON ruinform_ownership_events(object_id,network,detected_at_iso ASC)")


def _insert_event(
    *,
    object_id: str,
    asset_address: str,
    event_type: str,
    from_wallet: str | None,
    to_wallet: str,
    transaction_signature: str | None,
    detected_at_iso: str | None = None,
    event_id: str | None = None,
) -> None:
    event_id = event_id or uuid4().hex
    detected_at_iso = detected_at_iso or _now_iso()
    database_url = _database_url()
    if database_url:
        import psycopg
        with psycopg.connect(database_url) as conn:
            _ensure_postgres_schema(conn)
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO ruinform_ownership_events(
                        event_id,object_id,network,asset_address,event_type,from_wallet,to_wallet,transaction_signature,detected_at_iso
                    ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
                    ON CONFLICT DO NOTHING
                    """,
                    (event_id, object_id, NETWORK, asset_address, event_type, from_wallet, to_wallet, transaction_signature, detected_at_iso),
                )
            conn.commit()
        return
    with sqlite3.connect(_sqlite_path()) as conn:
        _ensure_sqlite_schema(conn)
        conn.execute(
            """
            INSERT OR IGNORE INTO ruinform_ownership_events(
                event_id,object_id,network,asset_address,event_type,from_wallet,to_wallet,transaction_signature,detected_at_iso
            ) VALUES (?,?,?,?,?,?,?,?,?)
            """,
            (event_id, object_id, NETWORK, asset_address, event_type, from_wallet, to_wallet, transaction_signature, detected_at_iso),
        )


def _seed_mint_event(object_id: str, asset_address: str) -> None:
    database_url = _database_url()
    creator_wallet = _identity_row(object_id).creator_wallet
    row = None
    if database_url:
        import psycopg
        with psycopg.connect(database_url) as conn:
            _ensure_postgres_schema(conn)
            with conn.cursor() as cur:
                cur.execute("SELECT 1 FROM ruinform_ownership_events WHERE object_id=%s AND event_type='MINT' LIMIT 1", (object_id,))
                if cur.fetchone():
                    return
                cur.execute(
                    "SELECT transaction_signature,minted_at_iso,owner_wallet FROM ruinform_nft_passports WHERE object_id=%s AND status='MINTED' AND COALESCE(network,'devnet')='devnet'",
                    (object_id,),
                )
                row = cur.fetchone()
    else:
        with sqlite3.connect(_sqlite_path()) as conn:
            _ensure_sqlite_schema(conn)
            if conn.execute("SELECT 1 FROM ruinform_ownership_events WHERE object_id=? AND event_type='MINT' LIMIT 1", (object_id,)).fetchone():
                return
            try:
                row = conn.execute(
                    "SELECT transaction_signature,minted_at_iso,owner_wallet FROM ruinform_nft_passports WHERE object_id=? AND status='MINTED'",
                    (object_id,),
                ).fetchone()
            except sqlite3.OperationalError:
                row = None
    if not row:
        return
    signature, minted_at, stored_owner = row
    initial_owner = creator_wallet or (str(stored_owner) if stored_owner else None)
    if not initial_owner:
        return
    _insert_event(
        object_id=object_id,
        asset_address=asset_address,
        event_type="MINT",
        from_wallet=None,
        to_wallet=initial_owner,
        transaction_signature=str(signature) if signature else None,
        detected_at_iso=str(minted_at) if minted_at else _now_iso(),
        event_id=f"mint:{object_id}",
    )


def _rows(object_id: str) -> list[tuple]:
    database_url = _database_url()
    if database_url:
        import psycopg
        with psycopg.connect(database_url) as conn:
            _ensure_postgres_schema(conn)
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT event_id,object_id,network,asset_address,event_type,from_wallet,to_wallet,transaction_signature,detected_at_iso FROM ruinform_ownership_events WHERE object_id=%s AND network='devnet' ORDER BY detected_at_iso ASC,event_id ASC",
                    (object_id,),
                )
                return list(cur.fetchall())
    with sqlite3.connect(_sqlite_path()) as conn:
        _ensure_sqlite_schema(conn)
        return list(conn.execute(
            "SELECT event_id,object_id,network,asset_address,event_type,from_wallet,to_wallet,transaction_signature,detected_at_iso FROM ruinform_ownership_events WHERE object_id=? AND network='devnet' ORDER BY detected_at_iso ASC,event_id ASC",
            (object_id,),
        ).fetchall())


def _event(row: tuple) -> OwnershipEventResponse:
    return OwnershipEventResponse(
        event_id=str(row[0]),
        object_id=_public_object_id(str(row[1])),
        network="devnet",
        asset_address=str(row[3]),
        event_type=str(row[4]),
        from_wallet=str(row[5]) if row[5] else None,
        to_wallet=str(row[6]),
        transaction_signature=str(row[7]) if row[7] else None,
        detected_at_iso=str(row[8]),
    )


def _state(object_id: str) -> OwnershipStateResponse:
    asset_address, current_owner = _canonical_nft(object_id)
    _seed_mint_event(object_id, asset_address)
    return OwnershipStateResponse(
        object_id=_public_object_id(object_id),
        asset_address=asset_address,
        current_owner=current_owner,
        history=[_event(row) for row in _rows(object_id)],
    )


def _apply_owner_change(
    *,
    object_id: str,
    asset_address: str,
    from_wallet: str,
    to_wallet: str,
    event_type: str,
    transaction_signature: str,
) -> None:
    now = _now_iso()
    database_url = _database_url()
    if database_url:
        import psycopg
        with psycopg.connect(database_url) as conn:
            _ensure_postgres_schema(conn)
            with conn.cursor() as cur:
                cur.execute("SELECT owner_wallet FROM ruinform_object_identity WHERE object_id=%s FOR UPDATE", (object_id,))
                owner_row = cur.fetchone()
                if not owner_row or str(owner_row[0]) != from_wallet:
                    raise HTTPException(status_code=409, detail="RUINFORM owner changed before reconciliation; refresh")
                cur.execute("UPDATE ruinform_object_identity SET owner_wallet=%s,ownership_claimed_at_iso=%s WHERE object_id=%s", (to_wallet, now, object_id))
                cur.execute("UPDATE ruinform_nft_passports SET owner_wallet=%s WHERE object_id=%s AND status='MINTED' AND COALESCE(network,'devnet')='devnet'", (to_wallet, object_id))
                cur.execute("UPDATE ruinform_network_nft_passports SET owner_wallet=%s WHERE object_id=%s AND network='devnet' AND status='MINTED'", (to_wallet, object_id))
                cur.execute(
                    """
                    INSERT INTO ruinform_ownership_events(
                        event_id,object_id,network,asset_address,event_type,from_wallet,to_wallet,transaction_signature,detected_at_iso
                    ) VALUES (%s,%s,'devnet',%s,%s,%s,%s,%s,%s)
                    ON CONFLICT DO NOTHING
                    """,
                    (uuid4().hex, object_id, asset_address, event_type, from_wallet, to_wallet, transaction_signature, now),
                )
            conn.commit()
        return
    with sqlite3.connect(_sqlite_path()) as conn:
        _ensure_sqlite_schema(conn)
        owner_row = conn.execute("SELECT owner_wallet FROM ruinform_object_identity WHERE object_id=?", (object_id,)).fetchone()
        if not owner_row or str(owner_row[0]) != from_wallet:
            raise HTTPException(status_code=409, detail="RUINFORM owner changed before reconciliation; refresh")
        conn.execute("UPDATE ruinform_object_identity SET owner_wallet=?,ownership_claimed_at_iso=? WHERE object_id=?", (to_wallet, now, object_id))
        try:
            conn.execute("UPDATE ruinform_nft_passports SET owner_wallet=? WHERE object_id=? AND status='MINTED'", (to_wallet, object_id))
            conn.execute("UPDATE ruinform_network_nft_passports SET owner_wallet=? WHERE object_id=? AND network='devnet' AND status='MINTED'", (to_wallet, object_id))
        except sqlite3.OperationalError:
            pass
        conn.execute(
            "INSERT OR IGNORE INTO ruinform_ownership_events(event_id,object_id,network,asset_address,event_type,from_wallet,to_wallet,transaction_signature,detected_at_iso) VALUES (?,?,?,?,?,?,?,?,?)",
            (uuid4().hex, object_id, NETWORK, asset_address, event_type, from_wallet, to_wallet, transaction_signature, now),
        )


async def _find_matching_transfer(asset_address: str, from_wallet: str, to_wallet: str) -> str | None:
    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "getSignaturesForAddress",
        "params": [asset_address, {"limit": 16}],
    }
    async with httpx.AsyncClient(timeout=14.0) as client:
        response = await client.post(DEVNET_RPC, json=payload)
    response.raise_for_status()
    for item in response.json().get("result") or []:
        if not isinstance(item, dict) or item.get("err") is not None or not item.get("signature"):
            continue
        signature = str(item["signature"])
        try:
            await _verify_transfer_transaction(
                signature=signature,
                asset_address=asset_address,
                from_wallet=from_wallet,
                to_wallet=to_wallet,
            )
            return signature
        except HTTPException:
            continue
    return None


@router.get("/object/{object_id}/devnet", response_model=OwnershipStateResponse)
async def get_ownership_state(object_id: str) -> OwnershipStateResponse:
    return _state(_backend_object_id(object_id))


@router.post("/object/{object_id}/devnet/direct", response_model=OwnershipStateResponse)
async def record_direct_transfer(
    object_id: str,
    payload: DirectTransferRequest,
    x_ruinform_wallet_session: str | None = Header(default=None, alias="x-ruinform-wallet-session"),
) -> OwnershipStateResponse:
    backend_id = _backend_object_id(object_id)
    session = resolve_wallet_session(x_ruinform_wallet_session)
    asset_address, current_owner = _canonical_nft(backend_id)
    if session.wallet_address != current_owner:
        raise HTTPException(status_code=403, detail="Only the current on-chain owner can transfer this Artifact Passport")
    recipient, _ = _validated_wallet(payload.recipient_wallet)
    if recipient == current_owner:
        raise HTTPException(status_code=400, detail="Recipient wallet must differ from the current owner")
    await _verify_transfer_transaction(
        signature=payload.transaction_signature,
        asset_address=asset_address,
        from_wallet=current_owner,
        to_wallet=recipient,
    )
    _apply_owner_change(
        object_id=backend_id,
        asset_address=asset_address,
        from_wallet=current_owner,
        to_wallet=recipient,
        event_type="RUINFORM_TRANSFER",
        transaction_signature=payload.transaction_signature,
    )
    return _state(backend_id)


@router.post("/object/{object_id}/devnet/reconcile", response_model=OwnershipStateResponse)
async def reconcile_external_owner(object_id: str, payload: ReconcileOwnerRequest) -> OwnershipStateResponse:
    backend_id = _backend_object_id(object_id)
    asset_address, current_owner = _canonical_nft(backend_id)
    observed_owner, _ = _validated_wallet(payload.observed_owner)
    if observed_owner == current_owner:
        return _state(backend_id)
    signature = await _find_matching_transfer(asset_address, current_owner, observed_owner)
    if not signature:
        raise HTTPException(
            status_code=409,
            detail="On-chain owner differs, but RUINFORM could not yet prove the matching transfer transaction. History was not changed.",
        )
    _apply_owner_change(
        object_id=backend_id,
        asset_address=asset_address,
        from_wallet=current_owner,
        to_wallet=observed_owner,
        event_type="EXTERNAL_TRANSFER",
        transaction_signature=signature,
    )
    return _state(backend_id)

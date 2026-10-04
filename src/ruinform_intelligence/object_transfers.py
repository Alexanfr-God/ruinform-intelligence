from __future__ import annotations

import base64
import os
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Literal
from uuid import uuid4

import httpx
from fastapi import APIRouter, Header, HTTPException
from nacl.exceptions import BadSignatureError
from nacl.signing import VerifyKey
from pydantic import BaseModel, Field

from .nft_devnet import CORE_PROGRAM_ID, DEVNET_RPC
from .release_channels import _ensure_network_registry
from .wallet_identity import _identity_row, _validated_wallet, resolve_wallet_session


router = APIRouter(prefix="/v1/object-transfers", tags=["object-transfers"])
NETWORK = "devnet"
_TRANSFER_TTL_DAYS = 14
_ACTIVE_STATUSES = ("AWAITING_RECIPIENT", "RECIPIENT_CONFIRMED")


class TransferStartRequest(BaseModel):
    recipient_wallet: str = Field(min_length=32, max_length=64)


class TransferAcceptRequest(BaseModel):
    signature_base64: str = Field(min_length=20, max_length=512)


class TransferCompleteRequest(BaseModel):
    transaction_signature: str = Field(min_length=64, max_length=120)


class TransferResponse(BaseModel):
    transfer_id: str
    object_id: str
    network: Literal["devnet"] = "devnet"
    asset_address: str
    from_wallet: str
    to_wallet: str
    status: Literal["AWAITING_RECIPIENT", "RECIPIENT_CONFIRMED", "COMPLETED", "CANCELLED", "EXPIRED"]
    recipient_message: str
    created_at_iso: str
    expires_at_iso: str
    recipient_confirmed_at_iso: str | None = None
    transaction_signature: str | None = None
    completed_at_iso: str | None = None


class TransferListResponse(BaseModel):
    object_id: str
    network: Literal["devnet"] = "devnet"
    current_owner: str | None = None
    active: TransferResponse | None = None
    history: list[TransferResponse] = []


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


def _ensure_postgres_schema(conn) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS ruinform_object_transfers (
                transfer_id TEXT PRIMARY KEY,
                object_id TEXT NOT NULL,
                network TEXT NOT NULL,
                asset_address TEXT NOT NULL,
                from_wallet TEXT NOT NULL,
                to_wallet TEXT NOT NULL,
                status TEXT NOT NULL,
                recipient_message TEXT NOT NULL,
                recipient_signature_base64 TEXT,
                created_at_iso TEXT NOT NULL,
                expires_at_iso TEXT NOT NULL,
                recipient_confirmed_at_iso TEXT,
                transaction_signature TEXT,
                completed_at_iso TEXT,
                cancelled_at_iso TEXT
            )
            """
        )
        cur.execute("CREATE INDEX IF NOT EXISTS idx_ruinform_transfers_object ON ruinform_object_transfers(object_id,network,created_at_iso DESC)")
    conn.commit()


def _ensure_sqlite_schema(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS ruinform_object_transfers (
            transfer_id TEXT PRIMARY KEY,
            object_id TEXT NOT NULL,
            network TEXT NOT NULL,
            asset_address TEXT NOT NULL,
            from_wallet TEXT NOT NULL,
            to_wallet TEXT NOT NULL,
            status TEXT NOT NULL,
            recipient_message TEXT NOT NULL,
            recipient_signature_base64 TEXT,
            created_at_iso TEXT NOT NULL,
            expires_at_iso TEXT NOT NULL,
            recipient_confirmed_at_iso TEXT,
            transaction_signature TEXT,
            completed_at_iso TEXT,
            cancelled_at_iso TEXT
        )
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_ruinform_transfers_object ON ruinform_object_transfers(object_id,network,created_at_iso DESC)")


def _canonical_nft(object_id: str) -> tuple[str, str]:
    """Return (asset_address, owner_wallet) for the canonical Devnet certificate."""
    database_url = _database_url()
    row = None
    if database_url:
        import psycopg
        with psycopg.connect(database_url) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT mint_address,owner_wallet FROM ruinform_nft_passports WHERE object_id=%s AND status='MINTED' AND COALESCE(network,'devnet')='devnet'",
                    (object_id,),
                )
                row = cur.fetchone()
    else:
        with sqlite3.connect(_sqlite_path()) as conn:
            try:
                row = conn.execute(
                    "SELECT mint_address,owner_wallet FROM ruinform_nft_passports WHERE object_id=? AND status='MINTED' AND COALESCE(network,'devnet')='devnet'",
                    (object_id,),
                ).fetchone()
            except sqlite3.OperationalError:
                row = conn.execute(
                    "SELECT mint_address,NULL FROM ruinform_nft_passports WHERE object_id=? AND status='MINTED'",
                    (object_id,),
                ).fetchone()
    if not row or not row[0]:
        raise HTTPException(status_code=409, detail="Canonical Devnet NFT Passport must be minted before transfer")
    identity_owner = _identity_row(object_id).owner_wallet
    owner = str(row[1]) if row[1] else identity_owner
    if not owner:
        raise HTTPException(status_code=409, detail="Current owner is not recorded for this Object Passport")
    return str(row[0]), owner


def _recipient_message(*, transfer_id: str, object_id: str, asset: str, from_wallet: str, to_wallet: str, expires_at: str) -> str:
    return "\n".join(
        [
            "RUINFORM PHYSICAL TRANSFER RECEIPT",
            "",
            f"Transfer: {transfer_id}",
            f"Object: {_public_object_id(object_id)}",
            "Network: Solana Devnet",
            f"Canonical NFT: {asset}",
            f"From: {from_wallet}",
            f"To: {to_wallet}",
            f"Expires: {expires_at}",
            "",
            "I confirm that I have received, or am physically accepting, the referenced physical object together with its RUINFORM Object Passport and canonical NFT Passport.",
            "I understand that creator provenance does not change and that this signature records the physical handoff step before the on-chain owner transfer.",
            "This signature is not a blockchain transaction and does not cost SOL.",
        ]
    )


def _row_to_response(row: tuple) -> TransferResponse:
    return TransferResponse(
        transfer_id=str(row[0]),
        object_id=_public_object_id(str(row[1])),
        asset_address=str(row[3]),
        from_wallet=str(row[4]),
        to_wallet=str(row[5]),
        status=str(row[6]),
        recipient_message=str(row[7]),
        created_at_iso=str(row[9]),
        expires_at_iso=str(row[10]),
        recipient_confirmed_at_iso=str(row[11]) if row[11] else None,
        transaction_signature=str(row[12]) if row[12] else None,
        completed_at_iso=str(row[13]) if row[13] else None,
    )


def _read_transfer(transfer_id: str) -> tuple:
    database_url = _database_url()
    row = None
    if database_url:
        import psycopg
        with psycopg.connect(database_url) as conn:
            _ensure_postgres_schema(conn)
            with conn.cursor() as cur:
                cur.execute("SELECT * FROM ruinform_object_transfers WHERE transfer_id=%s", (transfer_id,))
                row = cur.fetchone()
    else:
        with sqlite3.connect(_sqlite_path()) as conn:
            _ensure_sqlite_schema(conn)
            row = conn.execute("SELECT * FROM ruinform_object_transfers WHERE transfer_id=?", (transfer_id,)).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="RUINFORM transfer not found")
    return row


def _expire_if_needed(row: tuple) -> tuple:
    status = str(row[6])
    if status not in _ACTIVE_STATUSES or _parse_iso(str(row[10])) > _utc_now():
        return row
    transfer_id = str(row[0])
    database_url = _database_url()
    if database_url:
        import psycopg
        with psycopg.connect(database_url) as conn:
            _ensure_postgres_schema(conn)
            with conn.cursor() as cur:
                cur.execute("UPDATE ruinform_object_transfers SET status='EXPIRED' WHERE transfer_id=%s AND status IN ('AWAITING_RECIPIENT','RECIPIENT_CONFIRMED')", (transfer_id,))
            conn.commit()
    else:
        with sqlite3.connect(_sqlite_path()) as conn:
            _ensure_sqlite_schema(conn)
            conn.execute("UPDATE ruinform_object_transfers SET status='EXPIRED' WHERE transfer_id=? AND status IN ('AWAITING_RECIPIENT','RECIPIENT_CONFIRMED')", (transfer_id,))
    return _read_transfer(transfer_id)


def _object_transfers(object_id: str) -> list[tuple]:
    database_url = _database_url()
    if database_url:
        import psycopg
        with psycopg.connect(database_url) as conn:
            _ensure_postgres_schema(conn)
            with conn.cursor() as cur:
                cur.execute("SELECT * FROM ruinform_object_transfers WHERE object_id=%s AND network='devnet' ORDER BY created_at_iso DESC", (object_id,))
                return list(cur.fetchall())
    with sqlite3.connect(_sqlite_path()) as conn:
        _ensure_sqlite_schema(conn)
        return list(conn.execute("SELECT * FROM ruinform_object_transfers WHERE object_id=? AND network='devnet' ORDER BY created_at_iso DESC", (object_id,)).fetchall())


def _verify_recipient_signature(wallet: str, message: str, signature_base64: str) -> None:
    _, public_key = _validated_wallet(wallet)
    try:
        signature = base64.b64decode(signature_base64, validate=True)
    except Exception as exc:
        raise HTTPException(status_code=400, detail="Recipient signature is not valid base64") from exc
    try:
        VerifyKey(public_key).verify(message.encode("utf-8"), signature)
    except BadSignatureError as exc:
        raise HTTPException(status_code=401, detail="Recipient physical-receipt signature is invalid") from exc


async def _verify_transfer_transaction(*, signature: str, asset_address: str, from_wallet: str, to_wallet: str) -> None:
    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "getTransaction",
        "params": [signature, {"encoding": "jsonParsed", "commitment": "confirmed", "maxSupportedTransactionVersion": 0}],
    }
    async with httpx.AsyncClient(timeout=14.0) as client:
        response = await client.post(DEVNET_RPC, json=payload)
    response.raise_for_status()
    result = response.json().get("result")
    if not result or (result.get("meta") or {}).get("err") is not None:
        raise HTTPException(status_code=409, detail="Devnet transfer transaction is not confirmed successfully")
    message = ((result.get("transaction") or {}).get("message") or {})
    keys_raw = message.get("accountKeys") or []
    signer_map: dict[str, bool] = {}
    for entry in keys_raw:
        if isinstance(entry, str):
            signer_map[entry] = False
        elif isinstance(entry, dict) and entry.get("pubkey"):
            signer_map[str(entry["pubkey"])] = bool(entry.get("signer"))
    for required in (asset_address, from_wallet, to_wallet, CORE_PROGRAM_ID):
        if required not in signer_map:
            raise HTTPException(status_code=409, detail="Confirmed transaction does not match this RUINFORM transfer")
    if not signer_map.get(from_wallet):
        raise HTTPException(status_code=409, detail="Current owner did not sign the Devnet transfer")

    matching_instruction = False
    for instruction in message.get("instructions") or []:
        if not isinstance(instruction, dict) or str(instruction.get("programId")) != CORE_PROGRAM_ID:
            continue
        accounts = [str(value) for value in (instruction.get("accounts") or [])]
        if asset_address in accounts and from_wallet in accounts and to_wallet in accounts:
            matching_instruction = True
            break
    if not matching_instruction:
        raise HTTPException(status_code=409, detail="No matching MPL Core transfer instruction was found")


@router.get("/{transfer_id}", response_model=TransferResponse)
async def get_transfer(transfer_id: str) -> TransferResponse:
    row = _expire_if_needed(_read_transfer(transfer_id))
    return _row_to_response(row)


@router.get("/object/{object_id}/devnet", response_model=TransferListResponse)
async def list_object_transfers(object_id: str) -> TransferListResponse:
    backend_id = _backend_object_id(object_id)
    rows = [_expire_if_needed(row) for row in _object_transfers(backend_id)]
    active = next((row for row in rows if str(row[6]) in _ACTIVE_STATUSES), None)
    history = [row for row in rows if str(row[6]) not in _ACTIVE_STATUSES][:20]
    return TransferListResponse(
        object_id=_public_object_id(backend_id),
        current_owner=_identity_row(backend_id).owner_wallet,
        active=_row_to_response(active) if active else None,
        history=[_row_to_response(row) for row in history],
    )


@router.post("/object/{object_id}/devnet/start", response_model=TransferResponse)
async def start_transfer(
    object_id: str,
    payload: TransferStartRequest,
    x_ruinform_wallet_session: str | None = Header(default=None, alias="x-ruinform-wallet-session"),
) -> TransferResponse:
    backend_id = _backend_object_id(object_id)
    session = resolve_wallet_session(x_ruinform_wallet_session)
    asset_address, current_owner = _canonical_nft(backend_id)
    if session.wallet_address != current_owner:
        raise HTTPException(status_code=403, detail="Only the current owner can start this physical transfer")
    recipient, _ = _validated_wallet(payload.recipient_wallet)
    if recipient == current_owner:
        raise HTTPException(status_code=400, detail="Recipient wallet must differ from the current owner")

    for row in _object_transfers(backend_id):
        row = _expire_if_needed(row)
        if str(row[6]) in _ACTIVE_STATUSES:
            raise HTTPException(status_code=409, detail="This object already has an active RUINFORM transfer")

    transfer_id = uuid4().hex
    now = _utc_now()
    expires = now + timedelta(days=_TRANSFER_TTL_DAYS)
    expires_iso = _iso(expires)
    message = _recipient_message(
        transfer_id=transfer_id,
        object_id=backend_id,
        asset=asset_address,
        from_wallet=current_owner,
        to_wallet=recipient,
        expires_at=expires_iso,
    )
    values = (transfer_id, backend_id, NETWORK, asset_address, current_owner, recipient, "AWAITING_RECIPIENT", message, _iso(now), expires_iso)
    database_url = _database_url()
    if database_url:
        import psycopg
        with psycopg.connect(database_url) as conn:
            _ensure_postgres_schema(conn)
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO ruinform_object_transfers(transfer_id,object_id,network,asset_address,from_wallet,to_wallet,status,recipient_message,created_at_iso,expires_at_iso) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                    values,
                )
            conn.commit()
    else:
        with sqlite3.connect(_sqlite_path()) as conn:
            _ensure_sqlite_schema(conn)
            conn.execute(
                "INSERT INTO ruinform_object_transfers(transfer_id,object_id,network,asset_address,from_wallet,to_wallet,status,recipient_message,created_at_iso,expires_at_iso) VALUES (?,?,?,?,?,?,?,?,?,?)",
                values,
            )
    return _row_to_response(_read_transfer(transfer_id))


@router.post("/{transfer_id}/accept", response_model=TransferResponse)
async def accept_transfer(
    transfer_id: str,
    payload: TransferAcceptRequest,
    x_ruinform_wallet_session: str | None = Header(default=None, alias="x-ruinform-wallet-session"),
) -> TransferResponse:
    row = _expire_if_needed(_read_transfer(transfer_id))
    if str(row[6]) != "AWAITING_RECIPIENT":
        raise HTTPException(status_code=409, detail="This transfer is not awaiting recipient confirmation")
    session = resolve_wallet_session(x_ruinform_wallet_session)
    recipient = str(row[5])
    if session.wallet_address != recipient:
        raise HTTPException(status_code=403, detail="Only the named recipient wallet can accept this physical transfer")
    message = str(row[7])
    _verify_recipient_signature(recipient, message, payload.signature_base64)
    now = _iso(_utc_now())
    database_url = _database_url()
    if database_url:
        import psycopg
        with psycopg.connect(database_url) as conn:
            _ensure_postgres_schema(conn)
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE ruinform_object_transfers SET status='RECIPIENT_CONFIRMED',recipient_signature_base64=%s,recipient_confirmed_at_iso=%s WHERE transfer_id=%s AND status='AWAITING_RECIPIENT'",
                    (payload.signature_base64, now, transfer_id),
                )
                if cur.rowcount != 1:
                    raise HTTPException(status_code=409, detail="Transfer acceptance state changed; refresh")
            conn.commit()
    else:
        with sqlite3.connect(_sqlite_path()) as conn:
            _ensure_sqlite_schema(conn)
            cursor = conn.execute(
                "UPDATE ruinform_object_transfers SET status='RECIPIENT_CONFIRMED',recipient_signature_base64=?,recipient_confirmed_at_iso=? WHERE transfer_id=? AND status='AWAITING_RECIPIENT'",
                (payload.signature_base64, now, transfer_id),
            )
            if cursor.rowcount != 1:
                raise HTTPException(status_code=409, detail="Transfer acceptance state changed; refresh")
    return _row_to_response(_read_transfer(transfer_id))


@router.post("/{transfer_id}/complete", response_model=TransferResponse)
async def complete_transfer(
    transfer_id: str,
    payload: TransferCompleteRequest,
    x_ruinform_wallet_session: str | None = Header(default=None, alias="x-ruinform-wallet-session"),
) -> TransferResponse:
    row = _expire_if_needed(_read_transfer(transfer_id))
    if str(row[6]) != "RECIPIENT_CONFIRMED":
        raise HTTPException(status_code=409, detail="Recipient physical receipt must be confirmed before NFT transfer")
    session = resolve_wallet_session(x_ruinform_wallet_session)
    object_id, asset_address, from_wallet, to_wallet = str(row[1]), str(row[3]), str(row[4]), str(row[5])
    if session.wallet_address != from_wallet:
        raise HTTPException(status_code=403, detail="Only the current owner can complete the on-chain transfer")
    current_asset, current_owner = _canonical_nft(object_id)
    if current_asset != asset_address or current_owner != from_wallet:
        raise HTTPException(status_code=409, detail="Canonical owner state changed; transfer cannot complete")

    await _verify_transfer_transaction(
        signature=payload.transaction_signature,
        asset_address=asset_address,
        from_wallet=from_wallet,
        to_wallet=to_wallet,
    )
    now = _iso(_utc_now())
    _ensure_network_registry()
    database_url = _database_url()
    if database_url:
        import psycopg
        with psycopg.connect(database_url) as conn:
            _ensure_postgres_schema(conn)
            with conn.cursor() as cur:
                cur.execute("SELECT owner_wallet FROM ruinform_object_identity WHERE object_id=%s FOR UPDATE", (object_id,))
                owner_row = cur.fetchone()
                if not owner_row or str(owner_row[0]) != from_wallet:
                    raise HTTPException(status_code=409, detail="Current owner changed before transfer completion")
                cur.execute("UPDATE ruinform_object_identity SET owner_wallet=%s,ownership_claimed_at_iso=%s WHERE object_id=%s", (to_wallet, now, object_id))
                cur.execute("UPDATE ruinform_nft_passports SET owner_wallet=%s WHERE object_id=%s AND status='MINTED' AND COALESCE(network,'devnet')='devnet'", (to_wallet, object_id))
                cur.execute("UPDATE ruinform_network_nft_passports SET owner_wallet=%s WHERE object_id=%s AND network='devnet' AND status='MINTED'", (to_wallet, object_id))
                cur.execute(
                    "UPDATE ruinform_object_transfers SET status='COMPLETED',transaction_signature=%s,completed_at_iso=%s WHERE transfer_id=%s AND status='RECIPIENT_CONFIRMED'",
                    (payload.transaction_signature, now, transfer_id),
                )
                if cur.rowcount != 1:
                    raise HTTPException(status_code=409, detail="Transfer completion state changed; refresh")
            conn.commit()
    else:
        with sqlite3.connect(_sqlite_path()) as conn:
            _ensure_sqlite_schema(conn)
            owner_row = conn.execute("SELECT owner_wallet FROM ruinform_object_identity WHERE object_id=?", (object_id,)).fetchone()
            if not owner_row or str(owner_row[0]) != from_wallet:
                raise HTTPException(status_code=409, detail="Current owner changed before transfer completion")
            conn.execute("UPDATE ruinform_object_identity SET owner_wallet=?,ownership_claimed_at_iso=? WHERE object_id=?", (to_wallet, now, object_id))
            try:
                conn.execute("UPDATE ruinform_nft_passports SET owner_wallet=? WHERE object_id=? AND status='MINTED'", (to_wallet, object_id))
                conn.execute("UPDATE ruinform_network_nft_passports SET owner_wallet=? WHERE object_id=? AND network='devnet' AND status='MINTED'", (to_wallet, object_id))
            except sqlite3.OperationalError:
                pass
            cursor = conn.execute(
                "UPDATE ruinform_object_transfers SET status='COMPLETED',transaction_signature=?,completed_at_iso=? WHERE transfer_id=? AND status='RECIPIENT_CONFIRMED'",
                (payload.transaction_signature, now, transfer_id),
            )
            if cursor.rowcount != 1:
                raise HTTPException(status_code=409, detail="Transfer completion state changed; refresh")
    return _row_to_response(_read_transfer(transfer_id))


@router.post("/{transfer_id}/cancel", response_model=TransferResponse)
async def cancel_transfer(
    transfer_id: str,
    x_ruinform_wallet_session: str | None = Header(default=None, alias="x-ruinform-wallet-session"),
) -> TransferResponse:
    row = _expire_if_needed(_read_transfer(transfer_id))
    if str(row[6]) not in _ACTIVE_STATUSES:
        raise HTTPException(status_code=409, detail="Only an active transfer can be cancelled")
    session = resolve_wallet_session(x_ruinform_wallet_session)
    if session.wallet_address != str(row[4]):
        raise HTTPException(status_code=403, detail="Only the current owner can cancel this transfer")
    now = _iso(_utc_now())
    database_url = _database_url()
    if database_url:
        import psycopg
        with psycopg.connect(database_url) as conn:
            _ensure_postgres_schema(conn)
            with conn.cursor() as cur:
                cur.execute("UPDATE ruinform_object_transfers SET status='CANCELLED',cancelled_at_iso=%s WHERE transfer_id=%s AND status IN ('AWAITING_RECIPIENT','RECIPIENT_CONFIRMED')", (now, transfer_id))
            conn.commit()
    else:
        with sqlite3.connect(_sqlite_path()) as conn:
            _ensure_sqlite_schema(conn)
            conn.execute("UPDATE ruinform_object_transfers SET status='CANCELLED',cancelled_at_iso=? WHERE transfer_id=? AND status IN ('AWAITING_RECIPIENT','RECIPIENT_CONFIRMED')", (now, transfer_id))
    return _row_to_response(_read_transfer(transfer_id))

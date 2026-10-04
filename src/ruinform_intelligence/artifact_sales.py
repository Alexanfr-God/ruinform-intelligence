from __future__ import annotations

import base64
import hashlib
import sqlite3
from datetime import datetime, timezone
from typing import Literal
from uuid import uuid4

import httpx
from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, Field

from .artifact_standard_v1 import DEVNET_FEE_VAULT, RESALE_ROYALTY_BPS
from .nft_devnet import CORE_PROGRAM_ID, DEVNET_RPC
from .object_transfers import _backend_object_id, _canonical_nft, _public_object_id
from .wallet_identity import (
    _database_url,
    _ensure_postgres_schema as _ensure_identity_postgres,
    _ensure_sqlite_schema as _ensure_identity_sqlite,
    _identity_row,
    _sqlite_path,
    resolve_wallet_session,
)
from . import release_channels


router = APIRouter(prefix="/v1/artifact-sales", tags=["artifact-sales"])
NETWORK = "devnet"
SALE_PROGRAM_ID = "7MMPTzN2JvY1doYG3ezNRVq6Xf21KaL9yrkzh2Mguf1W"
SALE_TTL_DAYS = 14
LAMPORTS_PER_SOL = 1_000_000_000
_ACTIVE = ("LISTED", "FUNDED", "SHIPPED", "RECEIPT_CONFIRMED")
_CHAIN_STATUS = {1: "LISTED", 2: "FUNDED", 3: "RECEIPT_CONFIRMED", 4: "SETTLED", 5: "CANCELLED"}
_BASE58 = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"

# Sale V0 exists in the laboratory only. Mainnet is deliberately untouched.
release_channels.DEVNET_RELEASE = "RF-DEV-0.6"
if "sale-v0" not in release_channels.DEVNET_CAPABILITIES:
    release_channels.DEVNET_CAPABILITIES.append("sale-v0")


class SaleConfigResponse(BaseModel):
    network: Literal["devnet"] = "devnet"
    release: str
    program_id: str
    treasury_wallet: str
    resale_fee_bps: int
    resale_fee_percent: float
    ttl_days: int
    currency: Literal["SOL"] = "SOL"


class SaleListRequest(BaseModel):
    price_lamports: int = Field(ge=1_000_000, le=100_000 * LAMPORTS_PER_SOL)
    nonce: int = Field(ge=0, le=9_007_199_254_740_991)
    escrow_pda: str = Field(min_length=32, max_length=64)
    transaction_signature: str = Field(min_length=64, max_length=120)


class SaleTxRequest(BaseModel):
    transaction_signature: str = Field(min_length=64, max_length=120)


class SaleResponse(BaseModel):
    sale_id: str
    object_id: str
    network: Literal["devnet"] = "devnet"
    program_id: str
    escrow_pda: str
    asset_address: str
    seller_wallet: str
    buyer_wallet: str | None = None
    price_lamports: int
    price_sol: float
    ruinform_fee_bps: int
    seller_amount_lamports: int
    ruinform_amount_lamports: int
    status: Literal["LISTED", "FUNDED", "SHIPPED", "RECEIPT_CONFIRMED", "SETTLED", "CANCELLED"]
    nonce: int
    listing_tx: str | None = None
    fund_tx: str | None = None
    receipt_tx: str | None = None
    settlement_tx: str | None = None
    cancel_tx: str | None = None
    created_at_iso: str
    expires_at_iso: str
    shipped_at_iso: str | None = None
    settled_at_iso: str | None = None
    cancelled_at_iso: str | None = None


class SaleListResponse(BaseModel):
    object_id: str
    network: Literal["devnet"] = "devnet"
    active: SaleResponse | None = None
    history: list[SaleResponse] = []


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _b58encode(raw: bytes) -> str:
    if not raw:
        return ""
    number = int.from_bytes(raw, "big")
    chars: list[str] = []
    while number:
        number, rem = divmod(number, 58)
        chars.append(_BASE58[rem])
    zeros = len(raw) - len(raw.lstrip(b"\x00"))
    return "1" * zeros + ("".join(reversed(chars)) if chars else "")


def _ensure_postgres_schema(conn) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS ruinform_artifact_sales (
                sale_id TEXT PRIMARY KEY,
                object_id TEXT NOT NULL,
                network TEXT NOT NULL,
                program_id TEXT NOT NULL,
                escrow_pda TEXT UNIQUE NOT NULL,
                asset_address TEXT NOT NULL,
                seller_wallet TEXT NOT NULL,
                buyer_wallet TEXT,
                price_lamports BIGINT NOT NULL,
                ruinform_fee_bps INTEGER NOT NULL,
                status TEXT NOT NULL,
                nonce BIGINT NOT NULL,
                listing_tx TEXT,
                fund_tx TEXT,
                receipt_tx TEXT,
                settlement_tx TEXT,
                cancel_tx TEXT,
                created_at_iso TEXT NOT NULL,
                expires_at_iso TEXT NOT NULL,
                shipped_at_iso TEXT,
                settled_at_iso TEXT,
                cancelled_at_iso TEXT
            )
            """
        )
        cur.execute("CREATE INDEX IF NOT EXISTS idx_ruinform_sales_object ON ruinform_artifact_sales(object_id,network,created_at_iso DESC)")
    conn.commit()


def _ensure_sqlite_schema(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS ruinform_artifact_sales (
            sale_id TEXT PRIMARY KEY,
            object_id TEXT NOT NULL,
            network TEXT NOT NULL,
            program_id TEXT NOT NULL,
            escrow_pda TEXT UNIQUE NOT NULL,
            asset_address TEXT NOT NULL,
            seller_wallet TEXT NOT NULL,
            buyer_wallet TEXT,
            price_lamports INTEGER NOT NULL,
            ruinform_fee_bps INTEGER NOT NULL,
            status TEXT NOT NULL,
            nonce INTEGER NOT NULL,
            listing_tx TEXT,
            fund_tx TEXT,
            receipt_tx TEXT,
            settlement_tx TEXT,
            cancel_tx TEXT,
            created_at_iso TEXT NOT NULL,
            expires_at_iso TEXT NOT NULL,
            shipped_at_iso TEXT,
            settled_at_iso TEXT,
            cancelled_at_iso TEXT
        )
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_ruinform_sales_object ON ruinform_artifact_sales(object_id,network,created_at_iso DESC)")


_COLS = "sale_id,object_id,network,program_id,escrow_pda,asset_address,seller_wallet,buyer_wallet,price_lamports,ruinform_fee_bps,status,nonce,listing_tx,fund_tx,receipt_tx,settlement_tx,cancel_tx,created_at_iso,expires_at_iso,shipped_at_iso,settled_at_iso,cancelled_at_iso"


def _row_response(row: tuple) -> SaleResponse:
    price = int(row[8])
    fee = price * int(row[9]) // 10_000
    return SaleResponse(
        sale_id=str(row[0]), object_id=_public_object_id(str(row[1])), network="devnet",
        program_id=str(row[3]), escrow_pda=str(row[4]), asset_address=str(row[5]),
        seller_wallet=str(row[6]), buyer_wallet=str(row[7]) if row[7] else None,
        price_lamports=price, price_sol=price / LAMPORTS_PER_SOL,
        ruinform_fee_bps=int(row[9]), seller_amount_lamports=price-fee, ruinform_amount_lamports=fee,
        status=str(row[10]), nonce=int(row[11]), listing_tx=str(row[12]) if row[12] else None,
        fund_tx=str(row[13]) if row[13] else None, receipt_tx=str(row[14]) if row[14] else None,
        settlement_tx=str(row[15]) if row[15] else None, cancel_tx=str(row[16]) if row[16] else None,
        created_at_iso=str(row[17]), expires_at_iso=str(row[18]),
        shipped_at_iso=str(row[19]) if row[19] else None, settled_at_iso=str(row[20]) if row[20] else None,
        cancelled_at_iso=str(row[21]) if row[21] else None,
    )


def _read_sale(sale_id: str) -> tuple:
    db = _database_url()
    if db:
        import psycopg
        with psycopg.connect(db) as conn:
            _ensure_postgres_schema(conn)
            with conn.cursor() as cur:
                cur.execute(f"SELECT {_COLS} FROM ruinform_artifact_sales WHERE sale_id=%s", (sale_id,))
                row = cur.fetchone()
    else:
        with sqlite3.connect(_sqlite_path()) as conn:
            _ensure_sqlite_schema(conn)
            row = conn.execute(f"SELECT {_COLS} FROM ruinform_artifact_sales WHERE sale_id=?", (sale_id,)).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="RUINFORM Artifact sale not found")
    return row


def _object_rows(object_id: str) -> list[tuple]:
    db = _database_url()
    if db:
        import psycopg
        with psycopg.connect(db) as conn:
            _ensure_postgres_schema(conn)
            with conn.cursor() as cur:
                cur.execute(f"SELECT {_COLS} FROM ruinform_artifact_sales WHERE object_id=%s AND network='devnet' ORDER BY created_at_iso DESC", (object_id,))
                return list(cur.fetchall())
    with sqlite3.connect(_sqlite_path()) as conn:
        _ensure_sqlite_schema(conn)
        return list(conn.execute(f"SELECT {_COLS} FROM ruinform_artifact_sales WHERE object_id=? AND network='devnet' ORDER BY created_at_iso DESC", (object_id,)).fetchall())


def _write_status(sale_id: str, status: str, *, buyer: str | None = None, tx_field: str | None = None, tx: str | None = None, time_field: str | None = None) -> SaleResponse:
    allowed_tx = {"fund_tx", "receipt_tx", "settlement_tx", "cancel_tx"}
    allowed_time = {"shipped_at_iso", "settled_at_iso", "cancelled_at_iso"}
    sets = ["status"]
    values: list[object] = [status]
    if buyer is not None: sets.append("buyer_wallet"); values.append(buyer)
    if tx_field:
        if tx_field not in allowed_tx: raise RuntimeError("invalid tx field")
        sets.append(tx_field); values.append(tx)
    if time_field:
        if time_field not in allowed_time: raise RuntimeError("invalid time field")
        sets.append(time_field); values.append(_now_iso())
    db = _database_url()
    if db:
        import psycopg
        with psycopg.connect(db) as conn:
            _ensure_postgres_schema(conn)
            with conn.cursor() as cur:
                cur.execute(f"UPDATE ruinform_artifact_sales SET {','.join(v+'=%s' for v in sets)} WHERE sale_id=%s", (*values, sale_id))
            conn.commit()
    else:
        with sqlite3.connect(_sqlite_path()) as conn:
            _ensure_sqlite_schema(conn)
            conn.execute(f"UPDATE ruinform_artifact_sales SET {','.join(v+'=?' for v in sets)} WHERE sale_id=?", (*values, sale_id))
    return _row_response(_read_sale(sale_id))


async def _rpc(method: str, params: list) -> dict:
    async with httpx.AsyncClient(timeout=16.0) as client:
        response = await client.post(DEVNET_RPC, json={"jsonrpc":"2.0","id":73,"method":method,"params":params})
    response.raise_for_status()
    body = response.json()
    if body.get("error"):
        raise HTTPException(status_code=502, detail="Solana Devnet RPC rejected the sale verification")
    return body


async def _successful_transaction(signature: str) -> dict:
    body = await _rpc("getTransaction", [signature, {"encoding":"jsonParsed","commitment":"confirmed","maxSupportedTransactionVersion":0}])
    result = body.get("result")
    if not result or (result.get("meta") or {}).get("err") is not None:
        raise HTTPException(status_code=409, detail="Devnet sale transaction is not confirmed successfully")
    return result


async def _escrow_state(pda: str) -> dict:
    body = await _rpc("getAccountInfo", [pda, {"encoding":"base64","commitment":"confirmed"}])
    value = (body.get("result") or {}).get("value")
    if not value or str(value.get("owner")) != SALE_PROGRAM_ID:
        raise HTTPException(status_code=409, detail="RUINFORM sale escrow PDA is not active on Devnet")
    encoded = (value.get("data") or [None])[0]
    try:
        raw = base64.b64decode(encoded)
    except Exception as exc:
        raise HTTPException(status_code=409, detail="Sale escrow state could not be decoded") from exc
    if len(raw) < 200 or raw[:8] != b"RUFSALE1" or raw[8] != 1:
        raise HTTPException(status_code=409, detail="Sale escrow state has an unknown format")
    buyer_raw = raw[72:104]
    return {
        "status": _CHAIN_STATUS.get(int(raw[10]), "UNKNOWN"),
        "nonce": int.from_bytes(raw[16:24], "little"),
        "price_lamports": int.from_bytes(raw[24:32], "little"),
        "expires_at_unix": int.from_bytes(raw[32:40], "little", signed=True),
        "seller": _b58encode(raw[40:72]),
        "buyer": None if buyer_raw == bytes(32) else _b58encode(buyer_raw),
        "asset": _b58encode(raw[104:136]),
        "treasury": _b58encode(raw[136:168]),
        "object_hash": raw[168:200].hex(),
        "lamports": int(value.get("lamports") or 0),
    }


def _expected_object_hash(object_id: str) -> str:
    return hashlib.sha256(_public_object_id(object_id).encode("utf-8")).hexdigest()


def _check_state(state: dict, *, object_id: str, asset: str, seller: str, price: int, nonce: int) -> None:
    expected = {
        "asset": asset,
        "seller": seller,
        "treasury": DEVNET_FEE_VAULT,
        "price_lamports": price,
        "nonce": nonce,
        "object_hash": _expected_object_hash(object_id),
    }
    for key, value in expected.items():
        if state.get(key) != value:
            raise HTTPException(status_code=409, detail=f"On-chain sale escrow does not match RUINFORM {key}")


async def _verify_atomic_settlement(signature: str, *, asset: str, seller: str, buyer: str, escrow_pda: str) -> None:
    result = await _successful_transaction(signature)
    message = ((result.get("transaction") or {}).get("message") or {})
    keys_raw = message.get("accountKeys") or []
    signers: dict[str, bool] = {}
    for entry in keys_raw:
        if isinstance(entry, str): signers[entry] = False
        elif isinstance(entry, dict) and entry.get("pubkey"): signers[str(entry["pubkey"])] = bool(entry.get("signer"))
    for required in (asset, seller, buyer, escrow_pda, DEVNET_FEE_VAULT, CORE_PROGRAM_ID, SALE_PROGRAM_ID):
        if required not in signers:
            raise HTTPException(status_code=409, detail="Settlement transaction does not contain the complete RUINFORM sale")
    if not signers.get(seller):
        raise HTTPException(status_code=409, detail="Seller did not sign the Artifact sale settlement")
    core_ok = sale_ok = False
    for ix in message.get("instructions") or []:
        if not isinstance(ix, dict): continue
        program = str(ix.get("programId") or "")
        accounts = [str(v) for v in (ix.get("accounts") or [])]
        if program == CORE_PROGRAM_ID and asset in accounts and seller in accounts and buyer in accounts: core_ok = True
        if program == SALE_PROGRAM_ID and escrow_pda in accounts and seller in accounts and DEVNET_FEE_VAULT in accounts: sale_ok = True
    if not core_ok or not sale_ok:
        raise HTTPException(status_code=409, detail="Payment release and Artifact Passport transfer were not atomic")


def _update_owner(object_id: str, buyer: str) -> None:
    now = _now_iso(); db = _database_url()
    if db:
        import psycopg
        with psycopg.connect(db) as conn:
            _ensure_identity_postgres(conn)
            with conn.cursor() as cur:
                cur.execute("UPDATE ruinform_object_identity SET owner_wallet=%s,ownership_claimed_at_iso=%s WHERE object_id=%s", (buyer, now, object_id))
                cur.execute("UPDATE ruinform_nft_passports SET owner_wallet=%s WHERE object_id=%s AND status='MINTED' AND COALESCE(network,'devnet')='devnet'", (buyer, object_id))
                cur.execute("UPDATE ruinform_network_nft_passports SET owner_wallet=%s WHERE object_id=%s AND network='devnet'", (buyer, object_id))
            conn.commit()
        return
    with sqlite3.connect(_sqlite_path()) as conn:
        _ensure_identity_sqlite(conn)
        conn.execute("UPDATE ruinform_object_identity SET owner_wallet=?,ownership_claimed_at_iso=? WHERE object_id=?", (buyer, now, object_id))
        try: conn.execute("UPDATE ruinform_nft_passports SET owner_wallet=? WHERE object_id=? AND status='MINTED'", (buyer, object_id))
        except sqlite3.OperationalError: pass
        try: conn.execute("UPDATE ruinform_network_nft_passports SET owner_wallet=? WHERE object_id=? AND network='devnet'", (buyer, object_id))
        except sqlite3.OperationalError: pass


@router.get("/config/devnet", response_model=SaleConfigResponse)
async def sale_config() -> SaleConfigResponse:
    return SaleConfigResponse(release="RF-DEV-0.6", program_id=SALE_PROGRAM_ID, treasury_wallet=DEVNET_FEE_VAULT, resale_fee_bps=RESALE_ROYALTY_BPS, resale_fee_percent=RESALE_ROYALTY_BPS/100, ttl_days=SALE_TTL_DAYS)


@router.get("/{sale_id}", response_model=SaleResponse)
async def get_sale(sale_id: str) -> SaleResponse:
    return _row_response(_read_sale(sale_id))


@router.get("/object/{object_id}/devnet", response_model=SaleListResponse)
async def object_sales(object_id: str) -> SaleListResponse:
    backend_id = _backend_object_id(object_id); rows = _object_rows(backend_id)
    active = next((r for r in rows if str(r[10]) in _ACTIVE), None)
    history = [r for r in rows if str(r[10]) not in _ACTIVE][:20]
    return SaleListResponse(object_id=_public_object_id(backend_id), active=_row_response(active) if active else None, history=[_row_response(r) for r in history])


@router.post("/object/{object_id}/devnet/list", response_model=SaleResponse)
async def list_for_sale(object_id: str, payload: SaleListRequest, x_ruinform_wallet_session: str | None = Header(default=None, alias="x-ruinform-wallet-session")) -> SaleResponse:
    backend_id = _backend_object_id(object_id); seller = resolve_wallet_session(x_ruinform_wallet_session).wallet_address
    asset, owner = _canonical_nft(backend_id)
    if seller != owner or _identity_row(backend_id).owner_wallet != seller:
        raise HTTPException(status_code=403, detail="Only the current Artifact owner can list it for sale")
    if any(str(r[10]) in _ACTIVE for r in _object_rows(backend_id)):
        raise HTTPException(status_code=409, detail="This Artifact already has an active RUINFORM sale")
    await _successful_transaction(payload.transaction_signature)
    state = await _escrow_state(payload.escrow_pda)
    _check_state(state, object_id=backend_id, asset=asset, seller=seller, price=payload.price_lamports, nonce=payload.nonce)
    if state["status"] != "LISTED": raise HTTPException(status_code=409, detail="Sale escrow is not in LISTED state")
    created = _now_iso(); expires = datetime.fromtimestamp(state["expires_at_unix"], tz=timezone.utc).isoformat().replace("+00:00", "Z"); sale_id = uuid4().hex
    values = (sale_id,backend_id,NETWORK,SALE_PROGRAM_ID,payload.escrow_pda,asset,seller,None,payload.price_lamports,RESALE_ROYALTY_BPS,"LISTED",payload.nonce,payload.transaction_signature,None,None,None,None,created,expires,None,None,None)
    db = _database_url()
    if db:
        import psycopg
        with psycopg.connect(db) as conn:
            _ensure_postgres_schema(conn)
            with conn.cursor() as cur:
                cur.execute("INSERT INTO ruinform_artifact_sales VALUES (" + ",".join(["%s"]*22) + ")", values)
            conn.commit()
    else:
        with sqlite3.connect(_sqlite_path()) as conn:
            _ensure_sqlite_schema(conn); conn.execute("INSERT INTO ruinform_artifact_sales VALUES (" + ",".join(["?"]*22) + ")", values)
    return _row_response(_read_sale(sale_id))


@router.post("/{sale_id}/fund", response_model=SaleResponse)
async def fund_sale(sale_id: str, payload: SaleTxRequest, x_ruinform_wallet_session: str | None = Header(default=None, alias="x-ruinform-wallet-session")) -> SaleResponse:
    row = _read_sale(sale_id); sale = _row_response(row); buyer = resolve_wallet_session(x_ruinform_wallet_session).wallet_address
    if sale.status != "LISTED" or buyer == sale.seller_wallet: raise HTTPException(status_code=409, detail="This sale cannot be funded by this wallet")
    await _successful_transaction(payload.transaction_signature); state = await _escrow_state(sale.escrow_pda)
    _check_state(state, object_id=_backend_object_id(sale.object_id), asset=sale.asset_address, seller=sale.seller_wallet, price=sale.price_lamports, nonce=sale.nonce)
    if state["status"] != "FUNDED" or state["buyer"] != buyer or state["lamports"] < sale.price_lamports:
        raise HTTPException(status_code=409, detail="Buyer payment is not locked in the Devnet escrow")
    return _write_status(sale_id, "FUNDED", buyer=buyer, tx_field="fund_tx", tx=payload.transaction_signature)


@router.post("/{sale_id}/shipped", response_model=SaleResponse)
async def mark_shipped(sale_id: str, x_ruinform_wallet_session: str | None = Header(default=None, alias="x-ruinform-wallet-session")) -> SaleResponse:
    sale = _row_response(_read_sale(sale_id)); wallet = resolve_wallet_session(x_ruinform_wallet_session).wallet_address
    if wallet != sale.seller_wallet or sale.status != "FUNDED": raise HTTPException(status_code=403, detail="Only the seller can mark a funded Artifact as shipped")
    state = await _escrow_state(sale.escrow_pda)
    if state["status"] != "FUNDED": raise HTTPException(status_code=409, detail="Escrow payment is no longer locked")
    return _write_status(sale_id, "SHIPPED", time_field="shipped_at_iso")


@router.post("/{sale_id}/receipt", response_model=SaleResponse)
async def confirm_sale_receipt(sale_id: str, payload: SaleTxRequest, x_ruinform_wallet_session: str | None = Header(default=None, alias="x-ruinform-wallet-session")) -> SaleResponse:
    sale = _row_response(_read_sale(sale_id)); wallet = resolve_wallet_session(x_ruinform_wallet_session).wallet_address
    if wallet != sale.buyer_wallet or sale.status != "SHIPPED": raise HTTPException(status_code=403, detail="Only the funded buyer can confirm physical receipt after shipping")
    await _successful_transaction(payload.transaction_signature); state = await _escrow_state(sale.escrow_pda)
    if state["status"] != "RECEIPT_CONFIRMED" or state["buyer"] != wallet:
        raise HTTPException(status_code=409, detail="Buyer receipt authorization is not recorded in escrow")
    return _write_status(sale_id, "RECEIPT_CONFIRMED", tx_field="receipt_tx", tx=payload.transaction_signature)


@router.post("/{sale_id}/settle", response_model=SaleResponse)
async def settle_sale(sale_id: str, payload: SaleTxRequest, x_ruinform_wallet_session: str | None = Header(default=None, alias="x-ruinform-wallet-session")) -> SaleResponse:
    sale = _row_response(_read_sale(sale_id)); wallet = resolve_wallet_session(x_ruinform_wallet_session).wallet_address
    if wallet != sale.seller_wallet or sale.status != "RECEIPT_CONFIRMED" or not sale.buyer_wallet:
        raise HTTPException(status_code=403, detail="Only the seller can settle after buyer physical receipt")
    await _verify_atomic_settlement(payload.transaction_signature, asset=sale.asset_address, seller=sale.seller_wallet, buyer=sale.buyer_wallet, escrow_pda=sale.escrow_pda)
    state = await _escrow_state(sale.escrow_pda)
    if state["status"] != "SETTLED": raise HTTPException(status_code=409, detail="Escrow did not release the sale payment")
    _update_owner(_backend_object_id(sale.object_id), sale.buyer_wallet)
    return _write_status(sale_id, "SETTLED", tx_field="settlement_tx", tx=payload.transaction_signature, time_field="settled_at_iso")


@router.post("/{sale_id}/cancel", response_model=SaleResponse)
async def cancel_sale(sale_id: str, payload: SaleTxRequest, x_ruinform_wallet_session: str | None = Header(default=None, alias="x-ruinform-wallet-session")) -> SaleResponse:
    sale = _row_response(_read_sale(sale_id)); wallet = resolve_wallet_session(x_ruinform_wallet_session).wallet_address
    if wallet != sale.seller_wallet or sale.status not in ("LISTED", "FUNDED"):
        raise HTTPException(status_code=403, detail="Only the seller can cancel before physical receipt")
    await _successful_transaction(payload.transaction_signature); state = await _escrow_state(sale.escrow_pda)
    if state["status"] != "CANCELLED": raise HTTPException(status_code=409, detail="Escrow cancellation/refund is not confirmed")
    return _write_status(sale_id, "CANCELLED", tx_field="cancel_tx", tx=payload.transaction_signature, time_field="cancelled_at_iso")


@router.post("/{sale_id}/timeout-refund", response_model=SaleResponse)
async def timeout_refund(sale_id: str, payload: SaleTxRequest, x_ruinform_wallet_session: str | None = Header(default=None, alias="x-ruinform-wallet-session")) -> SaleResponse:
    sale = _row_response(_read_sale(sale_id)); wallet = resolve_wallet_session(x_ruinform_wallet_session).wallet_address
    if wallet != sale.buyer_wallet or sale.status not in ("FUNDED", "SHIPPED"):
        raise HTTPException(status_code=403, detail="Only the funded buyer can request an expired escrow refund")
    await _successful_transaction(payload.transaction_signature); state = await _escrow_state(sale.escrow_pda)
    if state["status"] != "CANCELLED": raise HTTPException(status_code=409, detail="Expired escrow refund is not confirmed")
    return _write_status(sale_id, "CANCELLED", tx_field="cancel_tx", tx=payload.transaction_signature, time_field="cancelled_at_iso")

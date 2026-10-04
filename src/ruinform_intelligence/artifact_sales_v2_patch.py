from __future__ import annotations

import base64
import sqlite3
from datetime import datetime, timezone

from fastapi import Header, HTTPException

from . import artifact_sales as sales

DEPLOYED_SALE_PROGRAM_ID = "RtcEaWSqDLej5FBWTkwGNraSEeb3zPGHmXg9FfVqNce"

# The immutable program deployed on Solana Devnet is Sale Escrow state v2.
sales.SALE_PROGRAM_ID = DEPLOYED_SALE_PROGRAM_ID
sales._CHAIN_STATUS = {
    1: "LISTED",
    2: "FUNDED",
    3: "SHIPPED",
    4: "RECEIPT_CONFIRMED",
    5: "SETTLED",
    6: "CANCELLED",
}


async def _escrow_state_v2(pda: str) -> dict:
    body = await sales._rpc("getAccountInfo", [pda, {"encoding": "base64", "commitment": "confirmed"}])
    value = (body.get("result") or {}).get("value")
    if not value or str(value.get("owner")) != DEPLOYED_SALE_PROGRAM_ID:
        raise HTTPException(status_code=409, detail="RUINFORM Sale V0 escrow PDA is not active on Devnet")
    encoded = (value.get("data") or [None])[0]
    try:
        raw = base64.b64decode(encoded)
    except Exception as exc:
        raise HTTPException(status_code=409, detail="Sale escrow state could not be decoded") from exc
    if len(raw) < 200 or raw[:8] != b"RUFSALE1" or raw[8] != 2:
        raise HTTPException(status_code=409, detail="Sale escrow state has an unknown version")
    buyer_raw = raw[72:104]
    chain_status = int(raw[10])
    return {
        "status": sales._CHAIN_STATUS.get(chain_status, "UNKNOWN"),
        "chain_status": chain_status,
        "nonce": int.from_bytes(raw[16:24], "little"),
        "price_lamports": int.from_bytes(raw[24:32], "little"),
        "expires_at_unix": int.from_bytes(raw[32:40], "little", signed=True),
        "seller": sales._b58encode(raw[40:72]),
        "buyer": None if buyer_raw == bytes(32) else sales._b58encode(buyer_raw),
        "asset": sales._b58encode(raw[104:136]),
        "treasury": sales._b58encode(raw[136:168]),
        "object_hash": raw[168:200].hex(),
        "lamports": int(value.get("lamports") or 0),
    }


sales._escrow_state = _escrow_state_v2


def _chain_expiry_iso(state: dict) -> str:
    return datetime.fromtimestamp(int(state["expires_at_unix"]), tz=timezone.utc).isoformat().replace("+00:00", "Z")


def _set_expiry(sale_id: str, expires_at_iso: str) -> None:
    db = sales._database_url()
    if db:
        import psycopg
        with psycopg.connect(db) as conn:
            sales._ensure_postgres_schema(conn)
            with conn.cursor() as cur:
                cur.execute("UPDATE ruinform_artifact_sales SET expires_at_iso=%s WHERE sale_id=%s", (expires_at_iso, sale_id))
            conn.commit()
        return
    with sqlite3.connect(sales._sqlite_path()) as conn:
        sales._ensure_sqlite_schema(conn)
        conn.execute("UPDATE ruinform_artifact_sales SET expires_at_iso=? WHERE sale_id=?", (expires_at_iso, sale_id))


async def _reconcile_row(row: tuple) -> sales.SaleResponse:
    sale = sales._row_response(row)
    if sale.program_id != DEPLOYED_SALE_PROGRAM_ID:
        return sale
    state = await _escrow_state_v2(sale.escrow_pda)
    sales._check_state(
        state,
        object_id=sales._backend_object_id(sale.object_id),
        asset=sale.asset_address,
        seller=sale.seller_wallet,
        price=sale.price_lamports,
        nonce=sale.nonce,
    )
    chain_status = state["status"]
    if chain_status == "UNKNOWN":
        return sale
    _set_expiry(sale.sale_id, _chain_expiry_iso(state))
    if chain_status == sale.status:
        if state.get("buyer") and not sale.buyer_wallet:
            return sales._write_status(sale.sale_id, sale.status, buyer=state["buyer"])
        return sales._row_response(sales._read_sale(sale.sale_id))
    # Solana is the source of truth for monotonic escrow progress.
    rank = {"LISTED": 1, "FUNDED": 2, "SHIPPED": 3, "RECEIPT_CONFIRMED": 4, "SETTLED": 5, "CANCELLED": 6}
    if rank.get(chain_status, 0) < rank.get(sale.status, 0) and chain_status != "CANCELLED":
        return sales._row_response(sales._read_sale(sale.sale_id))
    kwargs = {}
    if state.get("buyer"):
        kwargs["buyer"] = state["buyer"]
    if chain_status == "SHIPPED" and sale.status != "SHIPPED":
        kwargs["time_field"] = "shipped_at_iso"
    if chain_status == "SETTLED" and sale.status != "SETTLED":
        kwargs["time_field"] = "settled_at_iso"
    if chain_status == "CANCELLED" and sale.status != "CANCELLED":
        kwargs["time_field"] = "cancelled_at_iso"
    return sales._write_status(sale.sale_id, chain_status, **kwargs)


@sales.router.get("/v2/object/{object_id}/devnet", response_model=sales.SaleListResponse)
async def object_sales_v2(object_id: str) -> sales.SaleListResponse:
    backend_id = sales._backend_object_id(object_id)
    rows = sales._object_rows(backend_id)
    active = next((r for r in rows if str(r[10]) in sales._ACTIVE), None)
    if active:
        try:
            await _reconcile_row(active)
        except HTTPException:
            # Read pages must remain available even if a public RPC is briefly unhealthy.
            pass
    rows = sales._object_rows(backend_id)
    active = next((r for r in rows if str(r[10]) in sales._ACTIVE), None)
    history = [r for r in rows if str(r[10]) not in sales._ACTIVE][:20]
    return sales.SaleListResponse(
        object_id=sales._public_object_id(backend_id),
        active=sales._row_response(active) if active else None,
        history=[sales._row_response(r) for r in history],
    )


@sales.router.post("/v2/{sale_id}/shipped", response_model=sales.SaleResponse)
async def mark_shipped_v2(
    sale_id: str,
    payload: sales.SaleTxRequest,
    x_ruinform_wallet_session: str | None = Header(default=None, alias="x-ruinform-wallet-session"),
) -> sales.SaleResponse:
    sale = sales._row_response(sales._read_sale(sale_id))
    wallet = sales.resolve_wallet_session(x_ruinform_wallet_session).wallet_address
    if wallet != sale.seller_wallet or sale.status != "FUNDED":
        raise HTTPException(status_code=403, detail="Only the seller can mark a funded Artifact as shipped")
    await sales._successful_transaction(payload.transaction_signature)
    state = await _escrow_state_v2(sale.escrow_pda)
    sales._check_state(
        state,
        object_id=sales._backend_object_id(sale.object_id),
        asset=sale.asset_address,
        seller=sale.seller_wallet,
        price=sale.price_lamports,
        nonce=sale.nonce,
    )
    if state["status"] != "SHIPPED" or state.get("buyer") != sale.buyer_wallet:
        raise HTTPException(status_code=409, detail="Devnet escrow is not in SHIPPED state")
    _set_expiry(sale.sale_id, _chain_expiry_iso(state))
    return sales._write_status(sale_id, "SHIPPED", time_field="shipped_at_iso")

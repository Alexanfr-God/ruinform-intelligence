from __future__ import annotations

import base64
from datetime import datetime, timezone
from uuid import uuid4

from fastapi import Header, HTTPException

from . import artifact_sales as sales
from . import artifact_sales_fee_v2_patch as fees
from . import artifact_sales_v2_patch as sale_v2
from . import object_transfers as transfers


def _parse_program_account(pubkey: str, account: dict) -> dict | None:
    if str(account.get("owner") or "") != sale_v2.DEPLOYED_SALE_PROGRAM_ID:
        return None
    encoded = (account.get("data") or [None])[0]
    try:
        raw = base64.b64decode(encoded)
    except Exception:
        return None
    if len(raw) < 200 or raw[:8] != b"RUFSALE1" or raw[8] != 2:
        return None
    buyer_raw = raw[72:104]
    chain_status = int(raw[10])
    return {
        "escrow_pda": pubkey,
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
        "lamports": int(account.get("lamports") or 0),
    }


def _active_transfer(object_id: str):
    for row in transfers._object_transfers(object_id):
        row = transfers._expire_if_needed(row)
        if str(row[6]) in transfers._ACTIVE_STATUSES:
            return transfers._row_to_response(row)
    return None


async def _listing_signature(escrow_pda: str, seller: str) -> tuple[str, int, int | None] | None:
    body = await sales._rpc(
        "getSignaturesForAddress",
        [escrow_pda, {"limit": 20, "commitment": "confirmed"}],
    )
    signatures = list((body.get("result") or []))
    for entry in reversed(signatures):
        signature = str(entry.get("signature") or "")
        if not signature or entry.get("err") is not None:
            continue
        try:
            transaction = await sales._successful_transaction(signature)
        except HTTPException:
            continue
        message = ((transaction.get("transaction") or {}).get("message") or {})
        keys_raw = message.get("accountKeys") or []
        signers: dict[str, bool] = {}
        for item in keys_raw:
            if isinstance(item, str):
                signers[item] = False
            elif isinstance(item, dict) and item.get("pubkey"):
                signers[str(item["pubkey"])] = bool(item.get("signer"))
        if not signers.get(seller):
            continue
        matching_program = False
        matching_escrow = False
        for instruction in message.get("instructions") or []:
            if not isinstance(instruction, dict):
                continue
            if str(instruction.get("programId") or "") != sale_v2.DEPLOYED_SALE_PROGRAM_ID:
                continue
            matching_program = True
            if escrow_pda in [str(value) for value in (instruction.get("accounts") or [])]:
                matching_escrow = True
        if not matching_program or not matching_escrow:
            continue
        try:
            observed = fees._require_sale_step_fee(transaction, "Artifact sale listing recovery")
        except HTTPException:
            continue
        return signature, observed, int(entry["blockTime"]) if entry.get("blockTime") else None
    return None


async def _discover_orphan_listing(object_id: str) -> dict | None:
    backend_id = sales._backend_object_id(object_id)
    asset, owner = sales._canonical_nft(backend_id)

    # If RUINFORM already has the sale, reconciliation belongs to the normal v2 reader.
    rows = sales._object_rows(backend_id)
    active = next((row for row in rows if str(row[10]) in sales._ACTIVE), None)
    if active:
        return {
            "state": "REGISTERED",
            "sale": sales._row_response(active),
        }

    body = await sales._rpc(
        "getProgramAccounts",
        [sale_v2.DEPLOYED_SALE_PROGRAM_ID, {"encoding": "base64", "commitment": "confirmed"}],
    )
    expected_hash = sales._expected_object_hash(backend_id)
    candidates: list[dict] = []
    for item in body.get("result") or []:
        state = _parse_program_account(str(item.get("pubkey") or ""), item.get("account") or {})
        if not state:
            continue
        if state["status"] != "LISTED":
            continue
        if state["asset"] != asset or state["seller"] != owner:
            continue
        if state["treasury"] != sales.DEVNET_FEE_VAULT or state["object_hash"] != expected_hash:
            continue
        candidates.append(state)
    if not candidates:
        return None

    state = max(candidates, key=lambda item: int(item["expires_at_unix"]))
    listing = await _listing_signature(state["escrow_pda"], state["seller"])
    if not listing:
        raise HTTPException(status_code=409, detail="On-chain RUINFORM listing exists but its listing transaction could not be verified")
    signature, observed_treasury, block_time = listing
    return {
        "state": "ORPHAN_LISTED",
        "object_id": backend_id,
        "asset_address": asset,
        "seller_wallet": owner,
        "escrow_pda": state["escrow_pda"],
        "price_lamports": int(state["price_lamports"]),
        "nonce": int(state["nonce"]),
        "expires_at_unix": int(state["expires_at_unix"]),
        "transaction_signature": signature,
        "observed_treasury_lamports": observed_treasury,
        "block_time": block_time,
    }


def _insert_recovered_sale(found: dict) -> sales.SaleResponse:
    object_id = str(found["object_id"])
    for row in sales._object_rows(object_id):
        if str(row[4]) == str(found["escrow_pda"]):
            return sales._row_response(row)
        if str(row[10]) in sales._ACTIVE:
            raise HTTPException(status_code=409, detail="This Artifact already has an active RUINFORM sale")

    sale_id = uuid4().hex
    created = (
        datetime.fromtimestamp(int(found["block_time"]), tz=timezone.utc).isoformat().replace("+00:00", "Z")
        if found.get("block_time")
        else sales._now_iso()
    )
    expires = datetime.fromtimestamp(int(found["expires_at_unix"]), tz=timezone.utc).isoformat().replace("+00:00", "Z")
    values = (
        sale_id,
        object_id,
        sales.NETWORK,
        sale_v2.DEPLOYED_SALE_PROGRAM_ID,
        str(found["escrow_pda"]),
        str(found["asset_address"]),
        str(found["seller_wallet"]),
        None,
        int(found["price_lamports"]),
        sales.RESALE_ROYALTY_BPS,
        "LISTED",
        int(found["nonce"]),
        str(found["transaction_signature"]),
        None,
        None,
        None,
        None,
        created,
        expires,
        None,
        None,
        None,
    )
    db = sales._database_url()
    if db:
        import psycopg

        with psycopg.connect(db) as conn:
            sales._ensure_postgres_schema(conn)
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO ruinform_artifact_sales VALUES (" + ",".join(["%s"] * 22) + ")",
                    values,
                )
            conn.commit()
    else:
        import sqlite3

        with sqlite3.connect(sales._sqlite_path()) as conn:
            sales._ensure_sqlite_schema(conn)
            conn.execute(
                "INSERT INTO ruinform_artifact_sales VALUES (" + ",".join(["?"] * 22) + ")",
                values,
            )

    fees._record_sale_fee(
        sale_id=sale_id,
        object_id=sales._public_object_id(object_id),
        operation="LIST",
        transaction_signature=str(found["transaction_signature"]),
        royalty_lamports=0,
        observed_treasury_lamports=int(found["observed_treasury_lamports"]),
    )
    return sales._row_response(sales._read_sale(sale_id))


@sales.router.get("/v3/object/{object_id}/recovery")
async def sale_recovery_state(object_id: str) -> dict:
    found = await _discover_orphan_listing(object_id)
    if not found:
        return {"state": "NONE", "object_id": sales._public_object_id(sales._backend_object_id(object_id))}
    if found["state"] == "REGISTERED":
        sale = found["sale"]
        return {"state": "REGISTERED", "object_id": sale.object_id, "sale_id": sale.sale_id, "status": sale.status}
    transfer = _active_transfer(str(found["object_id"]))
    return {
        "state": "BLOCKED_TRANSFER" if transfer else "RECOVERABLE",
        "object_id": sales._public_object_id(str(found["object_id"])),
        "escrow_pda": found["escrow_pda"],
        "transaction_signature": found["transaction_signature"],
        "price_lamports": found["price_lamports"],
        "price_sol": int(found["price_lamports"]) / sales.LAMPORTS_PER_SOL,
        "transfer_id": transfer.transfer_id if transfer else None,
        "transfer_status": transfer.status if transfer else None,
    }


@sales.router.post("/v3/object/{object_id}/recover-listing", response_model=sales.SaleResponse)
async def recover_sale_listing(
    object_id: str,
    x_ruinform_wallet_session: str | None = Header(default=None, alias="x-ruinform-wallet-session"),
) -> sales.SaleResponse:
    found = await _discover_orphan_listing(object_id)
    if not found:
        raise HTTPException(status_code=404, detail="No unregistered on-chain RUINFORM listing was found")
    if found["state"] == "REGISTERED":
        return found["sale"]
    session = sales.resolve_wallet_session(x_ruinform_wallet_session)
    if session.wallet_address != str(found["seller_wallet"]):
        raise HTTPException(status_code=403, detail="Only the listing seller can recover this RUINFORM sale")
    transfer = _active_transfer(str(found["object_id"]))
    if transfer:
        raise HTTPException(
            status_code=409,
            detail="On-chain listing found. Cancel the active direct transfer before recovering this sale.",
        )
    return _insert_recovered_sale(found)

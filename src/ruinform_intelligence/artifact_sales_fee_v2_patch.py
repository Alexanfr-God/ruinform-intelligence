from __future__ import annotations

import sqlite3

from fastapi import Header, HTTPException

from . import artifact_sales as sales
from . import artifact_sales_v2_patch as sale_v2
from . import release_channels
from .artifact_standard_v1 import TRANSFER_SERVICE_FEE_LAMPORTS


SALE_FEE_SCHEDULE_VERSION = "RF-FEES-v2"
SALE_TRANSACTION_SERVICE_FEE_LAMPORTS = TRANSFER_SERVICE_FEE_LAMPORTS
SALE_TRANSACTION_SERVICE_FEE_SOL = SALE_TRANSACTION_SERVICE_FEE_LAMPORTS / sales.LAMPORTS_PER_SOL
NORMAL_SALE_FIXED_FEE_STEPS = 5
NORMAL_SALE_FIXED_FEE_LAMPORTS = SALE_TRANSACTION_SERVICE_FEE_LAMPORTS * NORMAL_SALE_FIXED_FEE_STEPS

# This remains a DEVNET LAB capability only. Mainnet is not promoted automatically.
release_channels.DEVNET_RELEASE = "RF-DEV-0.8"
for capability in ("fees-v2", "sale-fee-ledger-v1"):
    if capability not in release_channels.DEVNET_CAPABILITIES:
        release_channels.DEVNET_CAPABILITIES.append(capability)


_LEDGER_COLS = (
    "sale_id,object_id,operation,transaction_signature,fee_schedule_version,"
    "service_fee_lamports,royalty_lamports,minimum_treasury_lamports,"
    "observed_treasury_lamports,created_at_iso"
)


def _ensure_fee_ledger_postgres(conn) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS ruinform_sale_fee_events (
                sale_id TEXT NOT NULL,
                object_id TEXT NOT NULL,
                operation TEXT NOT NULL,
                transaction_signature TEXT UNIQUE NOT NULL,
                fee_schedule_version TEXT NOT NULL,
                service_fee_lamports BIGINT NOT NULL,
                royalty_lamports BIGINT NOT NULL,
                minimum_treasury_lamports BIGINT NOT NULL,
                observed_treasury_lamports BIGINT NOT NULL,
                created_at_iso TEXT NOT NULL,
                PRIMARY KEY (sale_id, operation)
            )
            """
        )
        cur.execute(
            "CREATE INDEX IF NOT EXISTS idx_ruinform_sale_fee_events_created "
            "ON ruinform_sale_fee_events(created_at_iso DESC)"
        )
    conn.commit()


def _ensure_fee_ledger_sqlite(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS ruinform_sale_fee_events (
            sale_id TEXT NOT NULL,
            object_id TEXT NOT NULL,
            operation TEXT NOT NULL,
            transaction_signature TEXT UNIQUE NOT NULL,
            fee_schedule_version TEXT NOT NULL,
            service_fee_lamports INTEGER NOT NULL,
            royalty_lamports INTEGER NOT NULL,
            minimum_treasury_lamports INTEGER NOT NULL,
            observed_treasury_lamports INTEGER NOT NULL,
            created_at_iso TEXT NOT NULL,
            PRIMARY KEY (sale_id, operation)
        )
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_ruinform_sale_fee_events_created "
        "ON ruinform_sale_fee_events(created_at_iso DESC)"
    )


def _ledger_row(row: tuple) -> dict:
    return {
        "sale_id": str(row[0]),
        "object_id": str(row[1]),
        "operation": str(row[2]),
        "transaction_signature": str(row[3]),
        "fee_schedule_version": str(row[4]),
        "service_fee_lamports": int(row[5]),
        "service_fee_sol": int(row[5]) / sales.LAMPORTS_PER_SOL,
        "royalty_lamports": int(row[6]),
        "royalty_sol": int(row[6]) / sales.LAMPORTS_PER_SOL,
        "minimum_treasury_lamports": int(row[7]),
        "minimum_treasury_sol": int(row[7]) / sales.LAMPORTS_PER_SOL,
        "observed_treasury_lamports": int(row[8]),
        "observed_treasury_sol": int(row[8]) / sales.LAMPORTS_PER_SOL,
        "created_at_iso": str(row[9]),
    }


def _record_sale_fee(
    *,
    sale_id: str,
    object_id: str,
    operation: str,
    transaction_signature: str,
    royalty_lamports: int,
    observed_treasury_lamports: int,
) -> None:
    royalty = max(0, int(royalty_lamports))
    service = SALE_TRANSACTION_SERVICE_FEE_LAMPORTS
    minimum = service + royalty
    values = (
        sale_id,
        object_id,
        operation,
        transaction_signature,
        SALE_FEE_SCHEDULE_VERSION,
        service,
        royalty,
        minimum,
        int(observed_treasury_lamports),
        sales._now_iso(),
    )
    db = sales._database_url()
    if db:
        import psycopg

        with psycopg.connect(db) as conn:
            _ensure_fee_ledger_postgres(conn)
            with conn.cursor() as cur:
                cur.execute(
                    f"INSERT INTO ruinform_sale_fee_events({_LEDGER_COLS}) "
                    "VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) "
                    "ON CONFLICT (sale_id,operation) DO NOTHING",
                    values,
                )
            conn.commit()
        return

    with sqlite3.connect(sales._sqlite_path()) as conn:
        _ensure_fee_ledger_sqlite(conn)
        conn.execute(
            f"INSERT INTO ruinform_sale_fee_events({_LEDGER_COLS}) "
            "VALUES(?,?,?,?,?,?,?,?,?,?) "
            "ON CONFLICT(sale_id,operation) DO NOTHING",
            values,
        )


def _fee_rows(sale_id: str | None = None) -> list[tuple]:
    db = sales._database_url()
    if db:
        import psycopg

        with psycopg.connect(db) as conn:
            _ensure_fee_ledger_postgres(conn)
            with conn.cursor() as cur:
                if sale_id is None:
                    cur.execute(f"SELECT {_LEDGER_COLS} FROM ruinform_sale_fee_events ORDER BY created_at_iso ASC")
                else:
                    cur.execute(
                        f"SELECT {_LEDGER_COLS} FROM ruinform_sale_fee_events "
                        "WHERE sale_id=%s ORDER BY created_at_iso ASC",
                        (sale_id,),
                    )
                return list(cur.fetchall())

    with sqlite3.connect(sales._sqlite_path()) as conn:
        _ensure_fee_ledger_sqlite(conn)
        if sale_id is None:
            return list(conn.execute(f"SELECT {_LEDGER_COLS} FROM ruinform_sale_fee_events ORDER BY created_at_iso ASC").fetchall())
        return list(
            conn.execute(
                f"SELECT {_LEDGER_COLS} FROM ruinform_sale_fee_events "
                "WHERE sale_id=? ORDER BY created_at_iso ASC",
                (sale_id,),
            ).fetchall()
        )


def _summarize_fee_rows(rows: list[tuple]) -> dict:
    events = [_ledger_row(row) for row in rows]
    service = sum(item["service_fee_lamports"] for item in events)
    royalty = sum(item["royalty_lamports"] for item in events)
    minimum = sum(item["minimum_treasury_lamports"] for item in events)
    observed = sum(item["observed_treasury_lamports"] for item in events)
    return {
        "events": len(events),
        "service_fee_lamports": service,
        "service_fee_sol": service / sales.LAMPORTS_PER_SOL,
        "royalty_lamports": royalty,
        "royalty_sol": royalty / sales.LAMPORTS_PER_SOL,
        "verified_minimum_revenue_lamports": minimum,
        "verified_minimum_revenue_sol": minimum / sales.LAMPORTS_PER_SOL,
        "observed_treasury_lamports": observed,
        "observed_treasury_sol": observed / sales.LAMPORTS_PER_SOL,
    }


def _treasury_received_lamports(transaction: dict, *, operation: str) -> int:
    message = ((transaction.get("transaction") or {}).get("message") or {})
    keys_raw = message.get("accountKeys") or []
    keys: list[str] = []
    for entry in keys_raw:
        if isinstance(entry, str):
            keys.append(entry)
        elif isinstance(entry, dict) and entry.get("pubkey"):
            keys.append(str(entry["pubkey"]))
    try:
        index = keys.index(sales.DEVNET_FEE_VAULT)
    except ValueError as exc:
        raise HTTPException(
            status_code=409,
            detail=f"RUINFORM {SALE_FEE_SCHEDULE_VERSION} service fee is missing from the {operation} transaction",
        ) from exc

    meta = transaction.get("meta") or {}
    pre = meta.get("preBalances") or []
    post = meta.get("postBalances") or []
    if index >= len(pre) or index >= len(post):
        raise HTTPException(status_code=409, detail="RUINFORM sale service-fee balance proof is unavailable")
    return int(post[index]) - int(pre[index])


def _require_sale_step_fee(
    transaction: dict,
    operation: str,
    *,
    extra_treasury_lamports: int = 0,
) -> int:
    minimum = SALE_TRANSACTION_SERVICE_FEE_LAMPORTS + max(0, int(extra_treasury_lamports))
    received = _treasury_received_lamports(transaction, operation=operation)
    if received < minimum:
        expected = minimum / sales.LAMPORTS_PER_SOL
        got = received / sales.LAMPORTS_PER_SOL
        raise HTTPException(
            status_code=409,
            detail=f"RUINFORM sale fee is short: expected {expected:.3f} SOL, received {got:.9f} SOL",
        )
    return received


@sales.router.get("/v3/config/devnet")
async def sale_config_v3() -> dict:
    return {
        "network": "devnet",
        "release": "RF-DEV-0.8",
        "program_id": sales.SALE_PROGRAM_ID,
        "treasury_wallet": sales.DEVNET_FEE_VAULT,
        "resale_fee_bps": sales.RESALE_ROYALTY_BPS,
        "resale_fee_percent": sales.RESALE_ROYALTY_BPS / 100,
        "ttl_days": sales.SALE_TTL_DAYS,
        "currency": "SOL",
        "fee_schedule_version": SALE_FEE_SCHEDULE_VERSION,
        "transaction_service_fee_lamports": SALE_TRANSACTION_SERVICE_FEE_LAMPORTS,
        "transaction_service_fee_sol": SALE_TRANSACTION_SERVICE_FEE_SOL,
        "normal_sale_fixed_fee_steps": NORMAL_SALE_FIXED_FEE_STEPS,
        "normal_sale_fixed_fee_lamports": NORMAL_SALE_FIXED_FEE_LAMPORTS,
        "normal_sale_fixed_fee_sol": NORMAL_SALE_FIXED_FEE_LAMPORTS / sales.LAMPORTS_PER_SOL,
        "fee_ledger": "enabled",
        "service_fee_policy": "charged on LIST, BUY/LOCK, SHIPPED, RECEIPT and SETTLEMENT; not charged on CANCEL/REFUND/DISPUTE",
    }


@sales.router.get("/v3/{sale_id}/fee-ledger")
async def sale_fee_ledger_v3(sale_id: str) -> dict:
    sale = sales._row_response(sales._read_sale(sale_id))
    rows = _fee_rows(sale_id)
    return {
        "sale_id": sale.sale_id,
        "object_id": sale.object_id,
        "network": "devnet",
        "release": "RF-DEV-0.8",
        "fee_schedule_version": SALE_FEE_SCHEDULE_VERSION,
        "events": [_ledger_row(row) for row in rows],
        "totals": _summarize_fee_rows(rows),
    }


@sales.router.get("/v3/treasury/summary")
async def sale_treasury_summary_v3() -> dict:
    rows = _fee_rows()
    summary = _summarize_fee_rows(rows)
    return {
        "network": "devnet",
        "release": "RF-DEV-0.8",
        "treasury_wallet": sales.DEVNET_FEE_VAULT,
        "fee_schedule_version": SALE_FEE_SCHEDULE_VERSION,
        **summary,
    }


@sales.router.post("/v3/object/{object_id}/devnet/list", response_model=sales.SaleResponse)
async def list_for_sale_v3(
    object_id: str,
    payload: sales.SaleListRequest,
    x_ruinform_wallet_session: str | None = Header(default=None, alias="x-ruinform-wallet-session"),
) -> sales.SaleResponse:
    transaction = await sales._successful_transaction(payload.transaction_signature)
    received = _require_sale_step_fee(transaction, "Artifact sale listing")
    sale = await sales.list_for_sale(object_id, payload, x_ruinform_wallet_session)
    _record_sale_fee(
        sale_id=sale.sale_id,
        object_id=sale.object_id,
        operation="LIST",
        transaction_signature=payload.transaction_signature,
        royalty_lamports=0,
        observed_treasury_lamports=received,
    )
    return sale


@sales.router.post("/v3/{sale_id}/fund", response_model=sales.SaleResponse)
async def fund_sale_v3(
    sale_id: str,
    payload: sales.SaleTxRequest,
    x_ruinform_wallet_session: str | None = Header(default=None, alias="x-ruinform-wallet-session"),
) -> sales.SaleResponse:
    transaction = await sales._successful_transaction(payload.transaction_signature)
    received = _require_sale_step_fee(transaction, "Artifact sale payment lock")
    sale = await sales.fund_sale(sale_id, payload, x_ruinform_wallet_session)
    _record_sale_fee(
        sale_id=sale.sale_id,
        object_id=sale.object_id,
        operation="BUY_LOCK",
        transaction_signature=payload.transaction_signature,
        royalty_lamports=0,
        observed_treasury_lamports=received,
    )
    return sale


@sales.router.post("/v3/{sale_id}/shipped", response_model=sales.SaleResponse)
async def mark_shipped_v3(
    sale_id: str,
    payload: sales.SaleTxRequest,
    x_ruinform_wallet_session: str | None = Header(default=None, alias="x-ruinform-wallet-session"),
) -> sales.SaleResponse:
    transaction = await sales._successful_transaction(payload.transaction_signature)
    received = _require_sale_step_fee(transaction, "Artifact sale shipped checkpoint")
    sale = await sale_v2.mark_shipped_v2(sale_id, payload, x_ruinform_wallet_session)
    _record_sale_fee(
        sale_id=sale.sale_id,
        object_id=sale.object_id,
        operation="MARK_SHIPPED",
        transaction_signature=payload.transaction_signature,
        royalty_lamports=0,
        observed_treasury_lamports=received,
    )
    return sale


@sales.router.post("/v3/{sale_id}/receipt", response_model=sales.SaleResponse)
async def confirm_sale_receipt_v3(
    sale_id: str,
    payload: sales.SaleTxRequest,
    x_ruinform_wallet_session: str | None = Header(default=None, alias="x-ruinform-wallet-session"),
) -> sales.SaleResponse:
    transaction = await sales._successful_transaction(payload.transaction_signature)
    received = _require_sale_step_fee(transaction, "Artifact sale physical receipt")
    sale = await sales.confirm_sale_receipt(sale_id, payload, x_ruinform_wallet_session)
    _record_sale_fee(
        sale_id=sale.sale_id,
        object_id=sale.object_id,
        operation="CONFIRM_RECEIPT",
        transaction_signature=payload.transaction_signature,
        royalty_lamports=0,
        observed_treasury_lamports=received,
    )
    return sale


@sales.router.post("/v3/{sale_id}/settle", response_model=sales.SaleResponse)
async def settle_sale_v3(
    sale_id: str,
    payload: sales.SaleTxRequest,
    x_ruinform_wallet_session: str | None = Header(default=None, alias="x-ruinform-wallet-session"),
) -> sales.SaleResponse:
    before = sales._row_response(sales._read_sale(sale_id))
    # Settlement sends the 5% resale share and the independent 0.01 SOL service
    # fee to the same treasury in the same Phantom transaction.
    transaction = await sales._successful_transaction(payload.transaction_signature)
    received = _require_sale_step_fee(
        transaction,
        "Artifact sale settlement",
        extra_treasury_lamports=before.ruinform_amount_lamports,
    )
    sale = await sales.settle_sale(sale_id, payload, x_ruinform_wallet_session)
    _record_sale_fee(
        sale_id=sale.sale_id,
        object_id=sale.object_id,
        operation="FINAL_SETTLEMENT",
        transaction_signature=payload.transaction_signature,
        royalty_lamports=before.ruinform_amount_lamports,
        observed_treasury_lamports=received,
    )
    return sale

from __future__ import annotations

from fastapi import Header

from . import artifact_sales as sales
from . import artifact_sales_v2_patch as sale_v2
from . import release_channels
from .artifact_standard_v1 import TRANSFER_SERVICE_FEE_LAMPORTS, _require_service_fee


SALE_FEE_SCHEDULE_VERSION = "RF-FEES-v2"
SALE_TRANSACTION_SERVICE_FEE_LAMPORTS = TRANSFER_SERVICE_FEE_LAMPORTS
SALE_TRANSACTION_SERVICE_FEE_SOL = SALE_TRANSACTION_SERVICE_FEE_LAMPORTS / sales.LAMPORTS_PER_SOL

# This remains a DEVNET LAB capability only. Mainnet is not promoted automatically.
release_channels.DEVNET_RELEASE = "RF-DEV-0.7"
if "fees-v2" not in release_channels.DEVNET_CAPABILITIES:
    release_channels.DEVNET_CAPABILITIES.append("fees-v2")


async def _require_sale_step_fee(signature: str, operation: str, *, extra_treasury_lamports: int = 0) -> None:
    await _require_service_fee(
        signature=signature,
        minimum_lamports=SALE_TRANSACTION_SERVICE_FEE_LAMPORTS + max(0, int(extra_treasury_lamports)),
        operation=operation,
    )


@sales.router.get("/v3/config/devnet")
async def sale_config_v3() -> dict:
    return {
        "network": "devnet",
        "release": "RF-DEV-0.7",
        "program_id": sales.SALE_PROGRAM_ID,
        "treasury_wallet": sales.DEVNET_FEE_VAULT,
        "resale_fee_bps": sales.RESALE_ROYALTY_BPS,
        "resale_fee_percent": sales.RESALE_ROYALTY_BPS / 100,
        "ttl_days": sales.SALE_TTL_DAYS,
        "currency": "SOL",
        "fee_schedule_version": SALE_FEE_SCHEDULE_VERSION,
        "transaction_service_fee_lamports": SALE_TRANSACTION_SERVICE_FEE_LAMPORTS,
        "transaction_service_fee_sol": SALE_TRANSACTION_SERVICE_FEE_SOL,
        "service_fee_policy": "charged on LIST, BUY/LOCK, SHIPPED, RECEIPT and SETTLEMENT; not charged on CANCEL/REFUND/DISPUTE",
    }


@sales.router.post("/v3/object/{object_id}/devnet/list", response_model=sales.SaleResponse)
async def list_for_sale_v3(
    object_id: str,
    payload: sales.SaleListRequest,
    x_ruinform_wallet_session: str | None = Header(default=None, alias="x-ruinform-wallet-session"),
) -> sales.SaleResponse:
    # Verify the fee before the legacy handler can persist an active sale.
    await sales._successful_transaction(payload.transaction_signature)
    await _require_sale_step_fee(payload.transaction_signature, "Artifact sale listing")
    return await sales.list_for_sale(object_id, payload, x_ruinform_wallet_session)


@sales.router.post("/v3/{sale_id}/fund", response_model=sales.SaleResponse)
async def fund_sale_v3(
    sale_id: str,
    payload: sales.SaleTxRequest,
    x_ruinform_wallet_session: str | None = Header(default=None, alias="x-ruinform-wallet-session"),
) -> sales.SaleResponse:
    await sales._successful_transaction(payload.transaction_signature)
    await _require_sale_step_fee(payload.transaction_signature, "Artifact sale payment lock")
    return await sales.fund_sale(sale_id, payload, x_ruinform_wallet_session)


@sales.router.post("/v3/{sale_id}/shipped", response_model=sales.SaleResponse)
async def mark_shipped_v3(
    sale_id: str,
    payload: sales.SaleTxRequest,
    x_ruinform_wallet_session: str | None = Header(default=None, alias="x-ruinform-wallet-session"),
) -> sales.SaleResponse:
    await sales._successful_transaction(payload.transaction_signature)
    await _require_sale_step_fee(payload.transaction_signature, "Artifact sale shipped checkpoint")
    return await sale_v2.mark_shipped_v2(sale_id, payload, x_ruinform_wallet_session)


@sales.router.post("/v3/{sale_id}/receipt", response_model=sales.SaleResponse)
async def confirm_sale_receipt_v3(
    sale_id: str,
    payload: sales.SaleTxRequest,
    x_ruinform_wallet_session: str | None = Header(default=None, alias="x-ruinform-wallet-session"),
) -> sales.SaleResponse:
    await sales._successful_transaction(payload.transaction_signature)
    await _require_sale_step_fee(payload.transaction_signature, "Artifact sale physical receipt")
    return await sales.confirm_sale_receipt(sale_id, payload, x_ruinform_wallet_session)


@sales.router.post("/v3/{sale_id}/settle", response_model=sales.SaleResponse)
async def settle_sale_v3(
    sale_id: str,
    payload: sales.SaleTxRequest,
    x_ruinform_wallet_session: str | None = Header(default=None, alias="x-ruinform-wallet-session"),
) -> sales.SaleResponse:
    sale = sales._row_response(sales._read_sale(sale_id))
    # Settlement also sends the 5% resale share to the same treasury. Require
    # the expected royalty PLUS the independent 0.01 SOL service fee.
    await sales._successful_transaction(payload.transaction_signature)
    await _require_sale_step_fee(
        payload.transaction_signature,
        "Artifact sale settlement",
        extra_treasury_lamports=sale.ruinform_amount_lamports,
    )
    return await sales.settle_sale(sale_id, payload, x_ruinform_wallet_session)

from __future__ import annotations

import pytest
from fastapi import HTTPException

from ruinform_intelligence import artifact_sales_fee_v2_patch as fees


def _transaction(received_lamports: int) -> dict:
    vault = fees.sales.DEVNET_FEE_VAULT
    return {
        "transaction": {
            "message": {
                "accountKeys": [
                    {"pubkey": "11111111111111111111111111111111", "signer": True},
                    {"pubkey": vault, "signer": False},
                ]
            }
        },
        "meta": {
            "preBalances": [2_000_000_000, 100_000_000],
            "postBalances": [1_900_000_000, 100_000_000 + received_lamports],
        },
    }


def test_sale_step_fee_accepts_fixed_fee() -> None:
    received = fees._require_sale_step_fee(
        _transaction(fees.SALE_TRANSACTION_SERVICE_FEE_LAMPORTS),
        "Artifact sale listing",
    )
    assert received == fees.SALE_TRANSACTION_SERVICE_FEE_LAMPORTS


def test_sale_step_fee_requires_fixed_fee_plus_royalty() -> None:
    royalty = 25_000_000
    expected = fees.SALE_TRANSACTION_SERVICE_FEE_LAMPORTS + royalty
    received = fees._require_sale_step_fee(
        _transaction(expected),
        "Artifact sale settlement",
        extra_treasury_lamports=royalty,
    )
    assert received == expected


def test_sale_step_fee_rejects_short_payment() -> None:
    with pytest.raises(HTTPException) as exc:
        fees._require_sale_step_fee(
            _transaction(fees.SALE_TRANSACTION_SERVICE_FEE_LAMPORTS - 1),
            "Artifact sale listing",
        )
    assert exc.value.status_code == 409
    assert "sale fee is short" in str(exc.value.detail)


def test_fee_ledger_is_idempotent_and_summarizes(tmp_path, monkeypatch) -> None:
    database = tmp_path / "ruinform-fees.db"
    monkeypatch.setattr(fees.sales, "_database_url", lambda: None)
    monkeypatch.setattr(fees.sales, "_sqlite_path", lambda: database)

    fees._record_sale_fee(
        sale_id="sale-1",
        object_id="RuF-OBJECT-1",
        operation="LIST",
        transaction_signature="sig-list",
        royalty_lamports=0,
        observed_treasury_lamports=10_000_000,
    )
    # Retrying the same successful API call must not double-count revenue.
    fees._record_sale_fee(
        sale_id="sale-1",
        object_id="RuF-OBJECT-1",
        operation="LIST",
        transaction_signature="sig-list",
        royalty_lamports=0,
        observed_treasury_lamports=10_000_000,
    )
    fees._record_sale_fee(
        sale_id="sale-1",
        object_id="RuF-OBJECT-1",
        operation="FINAL_SETTLEMENT",
        transaction_signature="sig-settle",
        royalty_lamports=50_000_000,
        observed_treasury_lamports=60_000_000,
    )

    rows = fees._fee_rows("sale-1")
    assert len(rows) == 2

    summary = fees._summarize_fee_rows(rows)
    assert summary["events"] == 2
    assert summary["service_fee_lamports"] == 20_000_000
    assert summary["royalty_lamports"] == 50_000_000
    assert summary["verified_minimum_revenue_lamports"] == 70_000_000
    assert summary["observed_treasury_lamports"] == 70_000_000


def test_devnet_release_and_normal_cycle_fixed_fee() -> None:
    assert fees.release_channels.DEVNET_RELEASE == "RF-DEV-0.8"
    assert "sale-fee-ledger-v1" in fees.release_channels.DEVNET_CAPABILITIES
    assert fees.NORMAL_SALE_FIXED_FEE_LAMPORTS == 50_000_000

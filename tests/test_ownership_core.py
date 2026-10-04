from __future__ import annotations

import sqlite3
from types import SimpleNamespace

from ruinform_intelligence import ownership_core as ownership


def _prepare_passport_db(path, *, object_id: str = "RF-0006", owner: str = "owner-a") -> None:
    with sqlite3.connect(path) as conn:
        conn.execute(
            """
            CREATE TABLE ruinform_nft_passports (
                object_id TEXT PRIMARY KEY,
                status TEXT,
                network TEXT,
                transaction_signature TEXT,
                minted_at_iso TEXT,
                owner_wallet TEXT
            )
            """
        )
        conn.execute(
            "INSERT INTO ruinform_nft_passports VALUES (?,?,?,?,?,?)",
            (object_id, "MINTED", "devnet", "mint-signature", "2026-10-04T00:00:00Z", owner),
        )


def test_ownership_state_seeds_one_mint_event(monkeypatch, tmp_path) -> None:
    path = tmp_path / "ownership.db"
    _prepare_passport_db(path)
    monkeypatch.setattr(ownership, "_database_url", lambda: None)
    monkeypatch.setattr(ownership, "_sqlite_path", lambda: path)
    monkeypatch.setattr(ownership, "_canonical_nft", lambda object_id: ("asset-006", "owner-a"))
    monkeypatch.setattr(ownership, "_identity_row", lambda object_id: SimpleNamespace(creator_wallet="owner-a"))

    first = ownership._state("RF-0006")
    second = ownership._state("RF-0006")

    assert first.current_owner == "owner-a"
    assert len(first.history) == 1
    assert len(second.history) == 1
    assert first.history[0].event_type == "MINT"
    assert first.history[0].to_wallet == "owner-a"
    assert first.history[0].transaction_signature == "mint-signature"


def test_apply_owner_change_appends_transfer_event(monkeypatch, tmp_path) -> None:
    path = tmp_path / "ownership.db"
    _prepare_passport_db(path)
    monkeypatch.setattr(ownership, "_database_url", lambda: None)
    monkeypatch.setattr(ownership, "_sqlite_path", lambda: path)

    with sqlite3.connect(path) as conn:
        conn.execute(
            "CREATE TABLE ruinform_object_identity (object_id TEXT PRIMARY KEY, owner_wallet TEXT, ownership_claimed_at_iso TEXT)"
        )
        conn.execute("INSERT INTO ruinform_object_identity VALUES ('RF-0006','owner-a',NULL)")
        conn.execute(
            "CREATE TABLE ruinform_network_nft_passports (object_id TEXT, network TEXT, status TEXT, owner_wallet TEXT)"
        )
        conn.execute("INSERT INTO ruinform_network_nft_passports VALUES ('RF-0006','devnet','MINTED','owner-a')")

    ownership._apply_owner_change(
        object_id="RF-0006",
        asset_address="asset-006",
        from_wallet="owner-a",
        to_wallet="owner-b",
        event_type="RUINFORM_TRANSFER",
        transaction_signature="transfer-signature",
    )

    with sqlite3.connect(path) as conn:
        owner = conn.execute("SELECT owner_wallet FROM ruinform_object_identity WHERE object_id='RF-0006'").fetchone()[0]
        passport_owner = conn.execute("SELECT owner_wallet FROM ruinform_nft_passports WHERE object_id='RF-0006'").fetchone()[0]
        row = conn.execute(
            "SELECT event_type,from_wallet,to_wallet,transaction_signature FROM ruinform_ownership_events WHERE transaction_signature='transfer-signature'"
        ).fetchone()

    assert owner == "owner-b"
    assert passport_owner == "owner-b"
    assert row == ("RUINFORM_TRANSFER", "owner-a", "owner-b", "transfer-signature")

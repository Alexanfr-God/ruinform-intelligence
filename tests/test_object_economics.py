from __future__ import annotations

import base64
import hashlib
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from nacl.signing import SigningKey

import ruinform_intelligence.object_economics as economics
import ruinform_intelligence.object_economics_v3 as economics_v3
from ruinform_intelligence.object_economics import AgreementVerifyRequest


ALPHABET = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"


def _base58_encode(raw: bytes) -> str:
    number = int.from_bytes(raw, "big")
    encoded = ""
    while number:
        number, remainder = divmod(number, 58)
        encoded = ALPHABET[remainder] + encoded
    padding = len(raw) - len(raw.lstrip(b"\x00"))
    return "1" * padding + (encoded or "1")


def _setup(monkeypatch, tmp_path):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("RUINFORM_DATABASE_URL", raising=False)
    monkeypatch.setenv("RUINFORM_DB_PATH", str(tmp_path / "economics.db"))
    signing_key = SigningKey.generate()
    address = _base58_encode(bytes(signing_key.verify_key))
    passport = SimpleNamespace(verification_status="UNVERIFIED")
    monkeypatch.setattr(economics, "object_store", lambda: SimpleNamespace(get=lambda _object_id: passport))
    monkeypatch.setattr(economics_v3, "object_store", lambda: SimpleNamespace(get=lambda _object_id: passport))
    monkeypatch.setattr(economics, "resolve_wallet_session", lambda _token: SimpleNamespace(wallet_address=address))
    monkeypatch.setattr(economics_v3, "resolve_wallet_session", lambda _token: SimpleNamespace(wallet_address=address))
    monkeypatch.setattr(
        economics,
        "_identity_row",
        lambda _object_id: SimpleNamespace(creator_wallet=address, owner_wallet=None),
    )
    return signing_key, address


def test_terms_hash_is_exact_and_royalty_is_five_percent() -> None:
    assert economics.ROYALTY_BPS == 500
    assert economics.TERMS_HASH == hashlib.sha256(economics.TERMS_TEXT.encode("utf-8")).hexdigest()
    assert "5.00% (500 basis points)" in economics.TERMS_TEXT
    assert "ONE CANONICAL NFT PASSPORT" in economics.TERMS_TEXT


def test_creator_signs_object_specific_agreement_and_nft_stays_locked(monkeypatch, tmp_path) -> None:
    signing_key, address = _setup(monkeypatch, tmp_path)
    challenge = economics.issue_creator_agreement_challenge("RuF-0004", "session")
    assert challenge.wallet_address == address
    assert "Object: RuF-0004" in challenge.message
    assert economics.TERMS_HASH in challenge.message

    signature = signing_key.sign(challenge.message.encode("utf-8")).signature
    result = economics.verify_creator_agreement(
        "RuF-0004",
        AgreementVerifyRequest(
            challenge_id=challenge.challenge_id,
            signature_base64=base64.b64encode(signature).decode("ascii"),
        ),
        "session",
    )

    assert result.agreement_status == "SIGNED"
    assert result.nft_status == "NOT_MINTED"
    assert result.royalty_bps == 500
    assert result.eligible_to_mint is False
    assert "LIVE_PHYSICAL_PROOF_REQUIRED" in result.blockers

    with pytest.raises(HTTPException) as exc:
        economics.verify_creator_agreement(
            "RuF-0004",
            AgreementVerifyRequest(
                challenge_id=challenge.challenge_id,
                signature_base64=base64.b64encode(signature).decode("ascii"),
            ),
            "session",
        )
    assert exc.value.status_code == 409

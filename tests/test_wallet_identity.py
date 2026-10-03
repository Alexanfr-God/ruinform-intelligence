from __future__ import annotations

import base64

import pytest
from fastapi import HTTPException
from nacl.signing import SigningKey

from ruinform_intelligence.wallet_identity import (
    WalletVerifyRequest,
    issue_wallet_challenge,
    resolve_wallet_session,
    verify_wallet_signature,
)


ALPHABET = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"


def _base58_encode(raw: bytes) -> str:
    number = int.from_bytes(raw, "big")
    encoded = ""
    while number:
        number, remainder = divmod(number, 58)
        encoded = ALPHABET[remainder] + encoded
    padding = len(raw) - len(raw.lstrip(b"\x00"))
    return "1" * padding + (encoded or "1")


def _sqlite(monkeypatch, tmp_path) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("RUINFORM_DATABASE_URL", raising=False)
    monkeypatch.setenv("RUINFORM_DB_PATH", str(tmp_path / "identity.db"))


def test_signed_wallet_challenge_creates_verified_session(monkeypatch, tmp_path) -> None:
    _sqlite(monkeypatch, tmp_path)
    signing_key = SigningKey.generate()
    address = _base58_encode(bytes(signing_key.verify_key))
    challenge = issue_wallet_challenge(address)
    signature = signing_key.sign(challenge.message.encode("utf-8")).signature

    verified = verify_wallet_signature(
        WalletVerifyRequest(
            challenge_id=challenge.challenge_id,
            wallet_address=address,
            signature_base64=base64.b64encode(signature).decode("ascii"),
        )
    )

    session = resolve_wallet_session(verified.session_token)
    assert session.authenticated is True
    assert session.wallet_address == address


def test_wallet_challenge_is_one_time(monkeypatch, tmp_path) -> None:
    _sqlite(monkeypatch, tmp_path)
    signing_key = SigningKey.generate()
    address = _base58_encode(bytes(signing_key.verify_key))
    challenge = issue_wallet_challenge(address)
    signature = base64.b64encode(signing_key.sign(challenge.message.encode("utf-8")).signature).decode("ascii")
    payload = WalletVerifyRequest(
        challenge_id=challenge.challenge_id,
        wallet_address=address,
        signature_base64=signature,
    )

    verify_wallet_signature(payload)
    with pytest.raises(HTTPException) as exc:
        verify_wallet_signature(payload)
    assert exc.value.status_code == 409


def test_signature_from_another_wallet_is_rejected(monkeypatch, tmp_path) -> None:
    _sqlite(monkeypatch, tmp_path)
    owner_key = SigningKey.generate()
    attacker_key = SigningKey.generate()
    address = _base58_encode(bytes(owner_key.verify_key))
    challenge = issue_wallet_challenge(address)
    wrong_signature = attacker_key.sign(challenge.message.encode("utf-8")).signature

    with pytest.raises(HTTPException) as exc:
        verify_wallet_signature(
            WalletVerifyRequest(
                challenge_id=challenge.challenge_id,
                wallet_address=address,
                signature_base64=base64.b64encode(wrong_signature).decode("ascii"),
            )
        )
    assert exc.value.status_code == 401

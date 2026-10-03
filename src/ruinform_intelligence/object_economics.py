from __future__ import annotations

import base64
import hashlib
import os
import secrets
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Literal
from uuid import uuid4

from fastapi import APIRouter, Header, HTTPException
from nacl.exceptions import BadSignatureError
from nacl.signing import VerifyKey
from pydantic import BaseModel, Field

from .object_passport import ObjectPassportNotFound, object_store
from .wallet_identity import _identity_row, _validated_wallet, resolve_wallet_session


router = APIRouter(tags=["object-economics"])

TERMS_VERSION = "RF-CREATOR-v1"
ROYALTY_BPS = 500
CHAIN = "solana"
_AGREEMENT_TTL_MINUTES = 10

# Canonical v1 text. The SHA-256 digest of these exact UTF-8 bytes is what the creator signs.
# This is an evidentiary/product contract record, not a substitute for jurisdiction-specific
# legal review before RUINFORM handles high-value commercial transactions.
TERMS_TEXT = """RUINFORM CREATOR AGREEMENT — RF-CREATOR-v1

1. CREATOR REGISTRATION
The signing wallet confirms that it controls the wallet used to register this RUINFORM Object Passport and is authorized to register the referenced object and creative work in RUINFORM.

2. CANONICAL OBJECT IDENTITY
The referenced RuF Object ID is the canonical RUINFORM identity for this registered object. Creator attribution is permanent provenance and does not transfer when ownership changes.

3. ONE CANONICAL NFT PASSPORT
RUINFORM will recognize no more than one canonical RUINFORM NFT Passport mint for the referenced RuF Object ID. A transfer, resale, burn, duplicate image, copy, fork, or derivative does not authorize a second canonical mint for the same RuF Object ID.

4. PHYSICAL VERIFICATION BEFORE MINT
A canonical NFT Passport is not eligible to mint until RUINFORM records the physical object as VERIFIED and the initial owner claim is completed.

5. RUINFORM RESALE ROYALTY
Qualifying resales completed through RUINFORM or a RUINFORM-recognized marketplace/transfer protocol are subject to a RUINFORM platform resale royalty of 5.00% (500 basis points), subject to applicable law and the mechanics of the marketplace or transfer protocol. This royalty is a platform resale royalty and does not state that RUINFORM owns 5% of the physical object.

6. PHYSICAL AND DIGITAL TRANSFER
For a registered physical object, the parties should transfer the RUINFORM Object Passport/NFT Passport together with the physical object through the supported RUINFORM transfer flow so provenance and current-owner history remain continuous.

7. ON-CHAIN RECORD
When the canonical NFT Passport is minted, RUINFORM may anchor the RuF Object ID, this agreement version, the exact agreement hash, and the royalty configuration on Solana or in the canonical NFT metadata/plugins.

8. GOOD-STANDING PROGRAM
RUINFORM may offer badges, reduced fees, visibility, rewards, or other benefits for verified and dispute-free transfers. Such benefits are optional program features and are not guaranteed consideration under this agreement.

9. IMMUTABLE ACCEPTANCE RECORD
Acceptance is object-specific. RUINFORM records the signing wallet, RuF Object ID, agreement version, exact agreement SHA-256 hash, signature, and timestamp. A later agreement version does not silently replace the version accepted for this object.
"""
TERMS_HASH = hashlib.sha256(TERMS_TEXT.encode("utf-8")).hexdigest()


class AgreementChallengeResponse(BaseModel):
    challenge_id: str
    object_id: str
    wallet_address: str
    message: str
    expires_at_iso: str
    terms_version: str
    terms_hash: str
    terms_text: str
    royalty_bps: int


class AgreementVerifyRequest(BaseModel):
    challenge_id: str = Field(min_length=8, max_length=80)
    signature_base64: str = Field(min_length=20, max_length=512)


class ObjectEconomicsResponse(BaseModel):
    object_id: str
    creator_wallet: str | None = None
    agreement_status: Literal["NOT_SIGNED", "SIGNED"]
    terms_version: str
    terms_hash: str
    terms_text: str
    royalty_bps: int
    royalty_percent: float
    signed_at_iso: str | None = None
    nft_status: Literal["NOT_MINTED", "MINTED"]
    chain: Literal["solana"] = "solana"
    mint_address: str | None = None
    minted_at_iso: str | None = None
    eligible_to_mint: bool
    blockers: list[str]


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


def _ensure_sqlite_schema(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS ruinform_creator_agreement_challenges (
            challenge_id TEXT PRIMARY KEY,
            object_id TEXT NOT NULL,
            wallet_address TEXT NOT NULL,
            message TEXT NOT NULL,
            terms_version TEXT NOT NULL,
            terms_hash TEXT NOT NULL,
            expires_at_iso TEXT NOT NULL,
            used_at_iso TEXT
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS ruinform_creator_agreements (
            object_id TEXT PRIMARY KEY,
            wallet_address TEXT NOT NULL,
            terms_version TEXT NOT NULL,
            terms_hash TEXT NOT NULL,
            royalty_bps INTEGER NOT NULL,
            signed_message TEXT NOT NULL,
            signature_base64 TEXT NOT NULL,
            signed_at_iso TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS ruinform_nft_passports (
            object_id TEXT PRIMARY KEY,
            chain TEXT NOT NULL,
            status TEXT NOT NULL,
            mint_address TEXT UNIQUE,
            royalty_bps INTEGER NOT NULL,
            terms_hash TEXT NOT NULL,
            minted_at_iso TEXT
        )
        """
    )


def _ensure_postgres_schema(conn) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS ruinform_creator_agreement_challenges (
                challenge_id TEXT PRIMARY KEY,
                object_id TEXT NOT NULL,
                wallet_address TEXT NOT NULL,
                message TEXT NOT NULL,
                terms_version TEXT NOT NULL,
                terms_hash TEXT NOT NULL,
                expires_at_iso TEXT NOT NULL,
                used_at_iso TEXT
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS ruinform_creator_agreements (
                object_id TEXT PRIMARY KEY,
                wallet_address TEXT NOT NULL,
                terms_version TEXT NOT NULL,
                terms_hash TEXT NOT NULL,
                royalty_bps INTEGER NOT NULL,
                signed_message TEXT NOT NULL,
                signature_base64 TEXT NOT NULL,
                signed_at_iso TEXT NOT NULL
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS ruinform_nft_passports (
                object_id TEXT PRIMARY KEY,
                chain TEXT NOT NULL,
                status TEXT NOT NULL,
                mint_address TEXT UNIQUE,
                royalty_bps INTEGER NOT NULL,
                terms_hash TEXT NOT NULL,
                minted_at_iso TEXT
            )
            """
        )
    conn.commit()


def _creator_for(object_id: str) -> str:
    creator = _identity_row(object_id).creator_wallet
    if not creator:
        raise HTTPException(status_code=409, detail="Creator identity must be registered before signing the Creator Agreement")
    return creator


def _agreement_message(*, object_id: str, wallet: str, nonce: str, issued: datetime, expires: datetime) -> str:
    return "\n".join(
        [
            "RUINFORM CREATOR AGREEMENT",
            "",
            f"Object: {_public_object_id(object_id)}",
            f"Creator wallet: {wallet}",
            f"Terms version: {TERMS_VERSION}",
            f"Terms SHA-256: {TERMS_HASH}",
            f"RUINFORM resale royalty: {ROYALTY_BPS} bps (5.00%)",
            "Canonical NFT Passport: ONE MINT ONLY",
            f"Nonce: {nonce}",
            f"Issued: {_iso(issued)}",
            f"Expires: {_iso(expires)}",
            "",
            "By signing, I accept the displayed Creator Agreement identified by the exact terms hash above for this RuF Object ID.",
            "This signature is not a blockchain transaction and does not cost SOL.",
        ]
    )


def _read_agreement(object_id: str) -> tuple | None:
    database_url = _database_url()
    if database_url:
        import psycopg
        with psycopg.connect(database_url) as conn:
            _ensure_postgres_schema(conn)
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT wallet_address,terms_version,terms_hash,royalty_bps,signed_at_iso FROM ruinform_creator_agreements WHERE object_id=%s",
                    (object_id,),
                )
                return cur.fetchone()
    with sqlite3.connect(_sqlite_path()) as conn:
        _ensure_sqlite_schema(conn)
        return conn.execute(
            "SELECT wallet_address,terms_version,terms_hash,royalty_bps,signed_at_iso FROM ruinform_creator_agreements WHERE object_id=?",
            (object_id,),
        ).fetchone()


def _read_nft(object_id: str) -> tuple | None:
    database_url = _database_url()
    if database_url:
        import psycopg
        with psycopg.connect(database_url) as conn:
            _ensure_postgres_schema(conn)
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT chain,status,mint_address,royalty_bps,terms_hash,minted_at_iso FROM ruinform_nft_passports WHERE object_id=%s",
                    (object_id,),
                )
                return cur.fetchone()
    with sqlite3.connect(_sqlite_path()) as conn:
        _ensure_sqlite_schema(conn)
        return conn.execute(
            "SELECT chain,status,mint_address,royalty_bps,terms_hash,minted_at_iso FROM ruinform_nft_passports WHERE object_id=?",
            (object_id,),
        ).fetchone()


def read_object_economics(object_id: str) -> ObjectEconomicsResponse:
    backend_id = _backend_object_id(object_id)
    try:
        passport = object_store().get(backend_id)
    except ObjectPassportNotFound as exc:
        raise HTTPException(status_code=404, detail="Object Passport not found") from exc

    identity = _identity_row(backend_id)
    agreement = _read_agreement(backend_id)
    nft = _read_nft(backend_id)
    agreement_signed = agreement is not None
    nft_status = str(nft[1]) if nft else "NOT_MINTED"
    blockers: list[str] = []
    if not identity.creator_wallet:
        blockers.append("CREATOR_NOT_REGISTERED")
    if not agreement_signed:
        blockers.append("CREATOR_AGREEMENT_NOT_SIGNED")
    if passport.verification_status != "VERIFIED":
        blockers.append("PHYSICAL_NOT_VERIFIED")
    if not identity.owner_wallet:
        blockers.append("OWNER_NOT_CLAIMED")
    if nft_status == "MINTED":
        blockers.append("CANONICAL_NFT_ALREADY_MINTED")

    return ObjectEconomicsResponse(
        object_id=_public_object_id(backend_id),
        creator_wallet=identity.creator_wallet,
        agreement_status="SIGNED" if agreement_signed else "NOT_SIGNED",
        terms_version=str(agreement[1]) if agreement else TERMS_VERSION,
        terms_hash=str(agreement[2]) if agreement else TERMS_HASH,
        terms_text=TERMS_TEXT,
        royalty_bps=int(agreement[3]) if agreement else ROYALTY_BPS,
        royalty_percent=(int(agreement[3]) if agreement else ROYALTY_BPS) / 100,
        signed_at_iso=str(agreement[4]) if agreement else None,
        nft_status="MINTED" if nft_status == "MINTED" else "NOT_MINTED",
        chain="solana",
        mint_address=str(nft[2]) if nft and nft[2] else None,
        minted_at_iso=str(nft[5]) if nft and nft[5] else None,
        eligible_to_mint=not blockers,
        blockers=blockers,
    )


def issue_creator_agreement_challenge(object_id: str, wallet_session: str | None) -> AgreementChallengeResponse:
    backend_id = _backend_object_id(object_id)
    try:
        object_store().get(backend_id)
    except ObjectPassportNotFound as exc:
        raise HTTPException(status_code=404, detail="Object Passport not found") from exc

    session = resolve_wallet_session(wallet_session)
    creator = _creator_for(backend_id)
    if creator != session.wallet_address:
        raise HTTPException(status_code=403, detail="Only the registered creator can sign this Creator Agreement")
    if _read_agreement(backend_id) is not None:
        raise HTTPException(status_code=409, detail="Creator Agreement is already signed for this Object Passport")

    issued = _utc_now()
    expires = issued + timedelta(minutes=_AGREEMENT_TTL_MINUTES)
    challenge_id = uuid4().hex
    nonce = secrets.token_hex(16).upper()
    message = _agreement_message(object_id=backend_id, wallet=creator, nonce=nonce, issued=issued, expires=expires)

    database_url = _database_url()
    if database_url:
        import psycopg
        with psycopg.connect(database_url) as conn:
            _ensure_postgres_schema(conn)
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO ruinform_creator_agreement_challenges(challenge_id,object_id,wallet_address,message,terms_version,terms_hash,expires_at_iso,used_at_iso) VALUES (%s,%s,%s,%s,%s,%s,%s,NULL)",
                    (challenge_id, backend_id, creator, message, TERMS_VERSION, TERMS_HASH, _iso(expires)),
                )
            conn.commit()
    else:
        with sqlite3.connect(_sqlite_path()) as conn:
            _ensure_sqlite_schema(conn)
            conn.execute(
                "INSERT INTO ruinform_creator_agreement_challenges(challenge_id,object_id,wallet_address,message,terms_version,terms_hash,expires_at_iso,used_at_iso) VALUES (?,?,?,?,?,?,?,NULL)",
                (challenge_id, backend_id, creator, message, TERMS_VERSION, TERMS_HASH, _iso(expires)),
            )

    return AgreementChallengeResponse(
        challenge_id=challenge_id,
        object_id=_public_object_id(backend_id),
        wallet_address=creator,
        message=message,
        expires_at_iso=_iso(expires),
        terms_version=TERMS_VERSION,
        terms_hash=TERMS_HASH,
        terms_text=TERMS_TEXT,
        royalty_bps=ROYALTY_BPS,
    )


def _load_challenge(challenge_id: str, object_id: str) -> tuple:
    database_url = _database_url()
    if database_url:
        import psycopg
        with psycopg.connect(database_url) as conn:
            _ensure_postgres_schema(conn)
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT wallet_address,message,terms_version,terms_hash,expires_at_iso,used_at_iso FROM ruinform_creator_agreement_challenges WHERE challenge_id=%s AND object_id=%s",
                    (challenge_id, object_id),
                )
                row = cur.fetchone()
    else:
        with sqlite3.connect(_sqlite_path()) as conn:
            _ensure_sqlite_schema(conn)
            row = conn.execute(
                "SELECT wallet_address,message,terms_version,terms_hash,expires_at_iso,used_at_iso FROM ruinform_creator_agreement_challenges WHERE challenge_id=? AND object_id=?",
                (challenge_id, object_id),
            ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Creator Agreement challenge not found")
    return row


def verify_creator_agreement(
    object_id: str,
    payload: AgreementVerifyRequest,
    wallet_session: str | None,
) -> ObjectEconomicsResponse:
    backend_id = _backend_object_id(object_id)
    session = resolve_wallet_session(wallet_session)
    row = _load_challenge(payload.challenge_id, backend_id)
    wallet, message, version, terms_hash, expires_at_iso, used_at_iso = [str(value) if value is not None else None for value in row]
    if wallet != session.wallet_address:
        raise HTTPException(status_code=403, detail="Wallet session does not match this Creator Agreement challenge")
    if used_at_iso:
        raise HTTPException(status_code=409, detail="Creator Agreement challenge was already used")
    if version != TERMS_VERSION or terms_hash != TERMS_HASH:
        raise HTTPException(status_code=409, detail="Creator Agreement terms changed; request a fresh agreement")
    if _parse_iso(str(expires_at_iso)) <= _utc_now():
        raise HTTPException(status_code=410, detail="Creator Agreement challenge expired")

    _wallet, public_key = _validated_wallet(str(wallet))
    try:
        signature = base64.b64decode(payload.signature_base64, validate=True)
    except Exception as exc:
        raise HTTPException(status_code=400, detail="Invalid Creator Agreement signature encoding") from exc
    if len(signature) != 64:
        raise HTTPException(status_code=400, detail="Invalid Solana signature length")
    try:
        VerifyKey(public_key).verify(str(message).encode("utf-8"), signature)
    except BadSignatureError as exc:
        raise HTTPException(status_code=401, detail="Creator Agreement signature is not valid for this wallet") from exc

    now = _iso(_utc_now())
    database_url = _database_url()
    if database_url:
        import psycopg
        with psycopg.connect(database_url) as conn:
            _ensure_postgres_schema(conn)
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE ruinform_creator_agreement_challenges SET used_at_iso=%s WHERE challenge_id=%s AND used_at_iso IS NULL",
                    (now, payload.challenge_id),
                )
                if cur.rowcount != 1:
                    raise HTTPException(status_code=409, detail="Creator Agreement challenge was already used")
                cur.execute(
                    "INSERT INTO ruinform_creator_agreements(object_id,wallet_address,terms_version,terms_hash,royalty_bps,signed_message,signature_base64,signed_at_iso) VALUES (%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT(object_id) DO NOTHING",
                    (backend_id, wallet, TERMS_VERSION, TERMS_HASH, ROYALTY_BPS, message, payload.signature_base64, now),
                )
                cur.execute(
                    "INSERT INTO ruinform_nft_passports(object_id,chain,status,mint_address,royalty_bps,terms_hash,minted_at_iso) VALUES (%s,%s,'NOT_MINTED',NULL,%s,%s,NULL) ON CONFLICT(object_id) DO NOTHING",
                    (backend_id, CHAIN, ROYALTY_BPS, TERMS_HASH),
                )
            conn.commit()
    else:
        with sqlite3.connect(_sqlite_path()) as conn:
            _ensure_sqlite_schema(conn)
            cursor = conn.execute(
                "UPDATE ruinform_creator_agreement_challenges SET used_at_iso=? WHERE challenge_id=? AND used_at_iso IS NULL",
                (now, payload.challenge_id),
            )
            if cursor.rowcount != 1:
                raise HTTPException(status_code=409, detail="Creator Agreement challenge was already used")
            conn.execute(
                "INSERT OR IGNORE INTO ruinform_creator_agreements(object_id,wallet_address,terms_version,terms_hash,royalty_bps,signed_message,signature_base64,signed_at_iso) VALUES (?,?,?,?,?,?,?,?)",
                (backend_id, wallet, TERMS_VERSION, TERMS_HASH, ROYALTY_BPS, message, payload.signature_base64, now),
            )
            conn.execute(
                "INSERT OR IGNORE INTO ruinform_nft_passports(object_id,chain,status,mint_address,royalty_bps,terms_hash,minted_at_iso) VALUES (?,?,'NOT_MINTED',NULL,?,?,NULL)",
                (backend_id, CHAIN, ROYALTY_BPS, TERMS_HASH),
            )

    return read_object_economics(backend_id)


@router.get("/v1/object-economics/{object_id}", response_model=ObjectEconomicsResponse)
async def get_object_economics(object_id: str) -> ObjectEconomicsResponse:
    return read_object_economics(object_id)


@router.post("/v1/object-economics/{object_id}/agreement-challenge", response_model=AgreementChallengeResponse)
async def create_creator_agreement_challenge(
    object_id: str,
    x_ruinform_wallet_session: str | None = Header(default=None, alias="x-ruinform-wallet-session"),
) -> AgreementChallengeResponse:
    return issue_creator_agreement_challenge(object_id, x_ruinform_wallet_session)


@router.post("/v1/object-economics/{object_id}/agreement-verify", response_model=ObjectEconomicsResponse)
async def complete_creator_agreement(
    object_id: str,
    payload: AgreementVerifyRequest,
    x_ruinform_wallet_session: str | None = Header(default=None, alias="x-ruinform-wallet-session"),
) -> ObjectEconomicsResponse:
    return verify_creator_agreement(object_id, payload, x_ruinform_wallet_session)

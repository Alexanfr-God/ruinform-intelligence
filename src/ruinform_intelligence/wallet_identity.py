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
from .run_store import utc_now_iso


router = APIRouter(tags=["wallet-identity"])

_CHALLENGE_TTL_MINUTES = 10
_SESSION_TTL_DAYS = 7
_BASE58_ALPHABET = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
_BASE58_INDEX = {char: index for index, char in enumerate(_BASE58_ALPHABET)}


class WalletChallengeRequest(BaseModel):
    wallet_address: str = Field(min_length=32, max_length=64)


class WalletChallengeResponse(BaseModel):
    challenge_id: str
    wallet_address: str
    message: str
    expires_at_iso: str


class WalletVerifyRequest(BaseModel):
    challenge_id: str = Field(min_length=8, max_length=80)
    wallet_address: str = Field(min_length=32, max_length=64)
    signature_base64: str = Field(min_length=20, max_length=512)


class WalletVerifyResponse(BaseModel):
    session_token: str
    wallet_address: str
    expires_at_iso: str


class WalletSessionResponse(BaseModel):
    authenticated: bool
    wallet_address: str
    expires_at_iso: str


class RegisterCreatorRequest(BaseModel):
    source_session_id: str = Field(min_length=1, max_length=160)
    candidate_id: str = Field(min_length=1, max_length=160)


class ObjectIdentityResponse(BaseModel):
    object_id: str
    registration_status: Literal["UNREGISTERED", "REGISTERED"]
    creator_wallet: str | None = None
    creator_registered_at_iso: str | None = None
    ownership_status: Literal["NO_OWNER", "OWNED"] = "NO_OWNER"
    owner_wallet: str | None = None
    ownership_claimed_at_iso: str | None = None


class WalletIdentityError(RuntimeError):
    pass


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _parse_iso(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _base58_decode(value: str) -> bytes:
    if not value:
        raise ValueError("Empty base58 value")
    number = 0
    for char in value:
        try:
            digit = _BASE58_INDEX[char]
        except KeyError as exc:
            raise ValueError("Invalid base58 value") from exc
        number = number * 58 + digit
    raw = b"" if number == 0 else number.to_bytes((number.bit_length() + 7) // 8, "big")
    padding = len(value) - len(value.lstrip("1"))
    return b"\x00" * padding + raw


def _validated_wallet(value: str) -> tuple[str, bytes]:
    wallet = value.strip()
    public_key = _base58_decode(wallet)
    if len(public_key) != 32:
        raise HTTPException(status_code=400, detail="A valid Solana wallet address is required")
    return wallet, public_key


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _database_url() -> str | None:
    return os.getenv("DATABASE_URL") or os.getenv("RUINFORM_DATABASE_URL")


def _sqlite_path() -> Path:
    path = Path(os.getenv("RUINFORM_DB_PATH", ".ruinform/ruinform.db"))
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _ensure_sqlite_schema(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS ruinform_wallet_challenges (
            challenge_id TEXT PRIMARY KEY,
            wallet_address TEXT NOT NULL,
            message TEXT NOT NULL,
            expires_at_iso TEXT NOT NULL,
            used_at_iso TEXT
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS ruinform_wallet_sessions (
            session_hash TEXT PRIMARY KEY,
            wallet_address TEXT NOT NULL,
            created_at_iso TEXT NOT NULL,
            expires_at_iso TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS ruinform_object_identity (
            object_id TEXT PRIMARY KEY,
            creator_wallet TEXT,
            creator_registered_at_iso TEXT,
            owner_wallet TEXT,
            ownership_claimed_at_iso TEXT
        )
        """
    )


def _ensure_postgres_schema(conn) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS ruinform_wallet_challenges (
                challenge_id TEXT PRIMARY KEY,
                wallet_address TEXT NOT NULL,
                message TEXT NOT NULL,
                expires_at_iso TEXT NOT NULL,
                used_at_iso TEXT
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS ruinform_wallet_sessions (
                session_hash TEXT PRIMARY KEY,
                wallet_address TEXT NOT NULL,
                created_at_iso TEXT NOT NULL,
                expires_at_iso TEXT NOT NULL
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS ruinform_object_identity (
                object_id TEXT PRIMARY KEY,
                creator_wallet TEXT,
                creator_registered_at_iso TEXT,
                owner_wallet TEXT,
                ownership_claimed_at_iso TEXT
            )
            """
        )
    conn.commit()


def _challenge_message(wallet: str, nonce: str, issued: datetime, expires: datetime) -> str:
    return "\n".join(
        [
            "RUINFORM LOGIN",
            "",
            f"Wallet: {wallet}",
            f"Nonce: {nonce}",
            f"Issued: {_iso(issued)}",
            f"Expires: {_iso(expires)}",
            "",
            "Purpose: Sign in to RUINFORM.",
            "This signature does not create a transaction or cost SOL.",
        ]
    )


def issue_wallet_challenge(wallet_address: str) -> WalletChallengeResponse:
    wallet, _ = _validated_wallet(wallet_address)
    issued = _utc_now()
    expires = issued + timedelta(minutes=_CHALLENGE_TTL_MINUTES)
    challenge_id = uuid4().hex
    nonce = secrets.token_hex(16).upper()
    message = _challenge_message(wallet, nonce, issued, expires)

    database_url = _database_url()
    if database_url:
        import psycopg

        with psycopg.connect(database_url) as conn:
            _ensure_postgres_schema(conn)
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO ruinform_wallet_challenges(challenge_id,wallet_address,message,expires_at_iso,used_at_iso) VALUES (%s,%s,%s,%s,NULL)",
                    (challenge_id, wallet, message, _iso(expires)),
                )
            conn.commit()
    else:
        with sqlite3.connect(_sqlite_path()) as conn:
            _ensure_sqlite_schema(conn)
            conn.execute(
                "INSERT INTO ruinform_wallet_challenges(challenge_id,wallet_address,message,expires_at_iso,used_at_iso) VALUES (?,?,?,?,NULL)",
                (challenge_id, wallet, message, _iso(expires)),
            )

    return WalletChallengeResponse(
        challenge_id=challenge_id,
        wallet_address=wallet,
        message=message,
        expires_at_iso=_iso(expires),
    )


def _load_challenge(challenge_id: str) -> tuple[str, str, str, str | None]:
    database_url = _database_url()
    if database_url:
        import psycopg

        with psycopg.connect(database_url) as conn:
            _ensure_postgres_schema(conn)
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT wallet_address,message,expires_at_iso,used_at_iso FROM ruinform_wallet_challenges WHERE challenge_id=%s",
                    (challenge_id,),
                )
                row = cur.fetchone()
    else:
        with sqlite3.connect(_sqlite_path()) as conn:
            _ensure_sqlite_schema(conn)
            row = conn.execute(
                "SELECT wallet_address,message,expires_at_iso,used_at_iso FROM ruinform_wallet_challenges WHERE challenge_id=?",
                (challenge_id,),
            ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Wallet sign-in challenge not found")
    return str(row[0]), str(row[1]), str(row[2]), str(row[3]) if row[3] else None


def _consume_challenge_and_create_session(challenge_id: str, wallet: str) -> WalletVerifyResponse:
    now = _utc_now()
    expires = now + timedelta(days=_SESSION_TTL_DAYS)
    raw_token = secrets.token_urlsafe(32)
    session_hash = _token_hash(raw_token)
    database_url = _database_url()

    if database_url:
        import psycopg

        with psycopg.connect(database_url) as conn:
            _ensure_postgres_schema(conn)
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE ruinform_wallet_challenges SET used_at_iso=%s WHERE challenge_id=%s AND used_at_iso IS NULL",
                    (_iso(now), challenge_id),
                )
                if cur.rowcount != 1:
                    raise HTTPException(status_code=409, detail="Wallet sign-in challenge was already used")
                cur.execute(
                    "INSERT INTO ruinform_wallet_sessions(session_hash,wallet_address,created_at_iso,expires_at_iso) VALUES (%s,%s,%s,%s)",
                    (session_hash, wallet, _iso(now), _iso(expires)),
                )
            conn.commit()
    else:
        with sqlite3.connect(_sqlite_path()) as conn:
            _ensure_sqlite_schema(conn)
            cursor = conn.execute(
                "UPDATE ruinform_wallet_challenges SET used_at_iso=? WHERE challenge_id=? AND used_at_iso IS NULL",
                (_iso(now), challenge_id),
            )
            if cursor.rowcount != 1:
                raise HTTPException(status_code=409, detail="Wallet sign-in challenge was already used")
            conn.execute(
                "INSERT INTO ruinform_wallet_sessions(session_hash,wallet_address,created_at_iso,expires_at_iso) VALUES (?,?,?,?)",
                (session_hash, wallet, _iso(now), _iso(expires)),
            )

    return WalletVerifyResponse(
        session_token=raw_token,
        wallet_address=wallet,
        expires_at_iso=_iso(expires),
    )


def verify_wallet_signature(payload: WalletVerifyRequest) -> WalletVerifyResponse:
    wallet, public_key = _validated_wallet(payload.wallet_address)
    stored_wallet, message, expires_at_iso, used_at_iso = _load_challenge(payload.challenge_id)
    if stored_wallet != wallet:
        raise HTTPException(status_code=409, detail="Wallet address does not match this sign-in challenge")
    if used_at_iso:
        raise HTTPException(status_code=409, detail="Wallet sign-in challenge was already used")
    if _parse_iso(expires_at_iso) <= _utc_now():
        raise HTTPException(status_code=410, detail="Wallet sign-in challenge expired")
    try:
        signature = base64.b64decode(payload.signature_base64, validate=True)
    except Exception as exc:
        raise HTTPException(status_code=400, detail="Invalid wallet signature encoding") from exc
    if len(signature) != 64:
        raise HTTPException(status_code=400, detail="Invalid Solana signature length")
    try:
        VerifyKey(public_key).verify(message.encode("utf-8"), signature)
    except BadSignatureError as exc:
        raise HTTPException(status_code=401, detail="Wallet signature is not valid for this address") from exc
    return _consume_challenge_and_create_session(payload.challenge_id, wallet)


def resolve_wallet_session(raw_token: str | None) -> WalletSessionResponse:
    token = (raw_token or "").strip()
    if not token:
        raise HTTPException(status_code=401, detail="Wallet session required")
    session_hash = _token_hash(token)
    database_url = _database_url()
    if database_url:
        import psycopg

        with psycopg.connect(database_url) as conn:
            _ensure_postgres_schema(conn)
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT wallet_address,expires_at_iso FROM ruinform_wallet_sessions WHERE session_hash=%s",
                    (session_hash,),
                )
                row = cur.fetchone()
    else:
        with sqlite3.connect(_sqlite_path()) as conn:
            _ensure_sqlite_schema(conn)
            row = conn.execute(
                "SELECT wallet_address,expires_at_iso FROM ruinform_wallet_sessions WHERE session_hash=?",
                (session_hash,),
            ).fetchone()
    if row is None:
        raise HTTPException(status_code=401, detail="Wallet session is invalid")
    expires_at_iso = str(row[1])
    if _parse_iso(expires_at_iso) <= _utc_now():
        raise HTTPException(status_code=401, detail="Wallet session expired")
    return WalletSessionResponse(authenticated=True, wallet_address=str(row[0]), expires_at_iso=expires_at_iso)


def _identity_row(object_id: str) -> ObjectIdentityResponse:
    database_url = _database_url()
    if database_url:
        import psycopg

        with psycopg.connect(database_url) as conn:
            _ensure_postgres_schema(conn)
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT creator_wallet,creator_registered_at_iso,owner_wallet,ownership_claimed_at_iso FROM ruinform_object_identity WHERE object_id=%s",
                    (object_id,),
                )
                row = cur.fetchone()
    else:
        with sqlite3.connect(_sqlite_path()) as conn:
            _ensure_sqlite_schema(conn)
            row = conn.execute(
                "SELECT creator_wallet,creator_registered_at_iso,owner_wallet,ownership_claimed_at_iso FROM ruinform_object_identity WHERE object_id=?",
                (object_id,),
            ).fetchone()
    if row is None:
        return ObjectIdentityResponse(object_id=object_id, registration_status="UNREGISTERED")
    creator = str(row[0]) if row[0] else None
    owner = str(row[2]) if row[2] else None
    return ObjectIdentityResponse(
        object_id=object_id,
        registration_status="REGISTERED" if creator else "UNREGISTERED",
        creator_wallet=creator,
        creator_registered_at_iso=str(row[1]) if row[1] else None,
        ownership_status="OWNED" if owner else "NO_OWNER",
        owner_wallet=owner,
        ownership_claimed_at_iso=str(row[3]) if row[3] else None,
    )


def register_creator(
    *,
    object_id: str,
    wallet_session: str | None,
    source_session_id: str,
    candidate_id: str,
) -> ObjectIdentityResponse:
    wallet = resolve_wallet_session(wallet_session).wallet_address
    backend_id = object_id.upper().replace("RUF-", "RF-")
    try:
        passport = object_store().get(backend_id)
    except ObjectPassportNotFound as exc:
        raise HTTPException(status_code=404, detail="Object Passport not found") from exc
    if passport.source_session_id != source_session_id or passport.candidate_id != candidate_id:
        raise HTTPException(status_code=403, detail="This private Workshop does not match the Object Passport provenance")

    now = utc_now_iso()
    database_url = _database_url()
    if database_url:
        import psycopg

        with psycopg.connect(database_url) as conn:
            _ensure_postgres_schema(conn)
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT creator_wallet FROM ruinform_object_identity WHERE object_id=%s FOR UPDATE",
                    (backend_id,),
                )
                row = cur.fetchone()
                if row and row[0] and str(row[0]) != wallet:
                    raise HTTPException(status_code=409, detail="This Object Passport already has a different creator")
                cur.execute(
                    """
                    INSERT INTO ruinform_object_identity(object_id,creator_wallet,creator_registered_at_iso)
                    VALUES (%s,%s,%s)
                    ON CONFLICT(object_id) DO UPDATE SET
                        creator_wallet=COALESCE(ruinform_object_identity.creator_wallet, EXCLUDED.creator_wallet),
                        creator_registered_at_iso=COALESCE(ruinform_object_identity.creator_registered_at_iso, EXCLUDED.creator_registered_at_iso)
                    """,
                    (backend_id, wallet, now),
                )
            conn.commit()
    else:
        with sqlite3.connect(_sqlite_path()) as conn:
            _ensure_sqlite_schema(conn)
            row = conn.execute(
                "SELECT creator_wallet FROM ruinform_object_identity WHERE object_id=?",
                (backend_id,),
            ).fetchone()
            if row and row[0] and str(row[0]) != wallet:
                raise HTTPException(status_code=409, detail="This Object Passport already has a different creator")
            conn.execute(
                "INSERT OR IGNORE INTO ruinform_object_identity(object_id,creator_wallet,creator_registered_at_iso) VALUES (?,?,?)",
                (backend_id, wallet, now),
            )
            conn.execute(
                "UPDATE ruinform_object_identity SET creator_wallet=COALESCE(creator_wallet,?), creator_registered_at_iso=COALESCE(creator_registered_at_iso,?) WHERE object_id=?",
                (wallet, now, backend_id),
            )
    return _identity_row(backend_id)


def claim_object(*, object_id: str, wallet_session: str | None) -> ObjectIdentityResponse:
    wallet = resolve_wallet_session(wallet_session).wallet_address
    backend_id = object_id.upper().replace("RUF-", "RF-")
    try:
        passport = object_store().get(backend_id)
    except ObjectPassportNotFound as exc:
        raise HTTPException(status_code=404, detail="Object Passport not found") from exc
    if passport.verification_status != "VERIFIED":
        raise HTTPException(status_code=409, detail="Physical verification is required before ownership can be claimed")

    identity = _identity_row(backend_id)
    if not identity.creator_wallet:
        raise HTTPException(status_code=409, detail="Creator identity must be registered before ownership can be claimed")
    if identity.creator_wallet != wallet:
        raise HTTPException(status_code=403, detail="Only the registered creator can make the initial ownership claim")
    if identity.owner_wallet and identity.owner_wallet != wallet:
        raise HTTPException(status_code=409, detail="This object already has an owner")
    if identity.owner_wallet == wallet:
        return identity

    now = utc_now_iso()
    database_url = _database_url()
    if database_url:
        import psycopg

        with psycopg.connect(database_url) as conn:
            _ensure_postgres_schema(conn)
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE ruinform_object_identity SET owner_wallet=%s,ownership_claimed_at_iso=%s WHERE object_id=%s AND owner_wallet IS NULL",
                    (wallet, now, backend_id),
                )
                if cur.rowcount != 1:
                    raise HTTPException(status_code=409, detail="Ownership claim could not be locked")
            conn.commit()
    else:
        with sqlite3.connect(_sqlite_path()) as conn:
            _ensure_sqlite_schema(conn)
            cursor = conn.execute(
                "UPDATE ruinform_object_identity SET owner_wallet=?,ownership_claimed_at_iso=? WHERE object_id=? AND owner_wallet IS NULL",
                (wallet, now, backend_id),
            )
            if cursor.rowcount != 1:
                raise HTTPException(status_code=409, detail="Ownership claim could not be locked")
    return _identity_row(backend_id)


@router.post("/v1/wallet/challenge", response_model=WalletChallengeResponse)
async def create_wallet_challenge(payload: WalletChallengeRequest) -> WalletChallengeResponse:
    return issue_wallet_challenge(payload.wallet_address)


@router.post("/v1/wallet/verify", response_model=WalletVerifyResponse)
async def complete_wallet_sign_in(payload: WalletVerifyRequest) -> WalletVerifyResponse:
    return verify_wallet_signature(payload)


@router.get("/v1/wallet/session", response_model=WalletSessionResponse)
async def read_wallet_session(
    x_ruinform_wallet_session: str | None = Header(default=None, alias="x-ruinform-wallet-session"),
) -> WalletSessionResponse:
    return resolve_wallet_session(x_ruinform_wallet_session)


@router.get("/v1/object-identity/{object_id}", response_model=ObjectIdentityResponse)
async def read_object_identity(object_id: str) -> ObjectIdentityResponse:
    backend_id = object_id.upper().replace("RUF-", "RF-")
    try:
        object_store().get(backend_id)
    except ObjectPassportNotFound as exc:
        raise HTTPException(status_code=404, detail="Object Passport not found") from exc
    return _identity_row(backend_id)


@router.post("/v1/object-identity/{object_id}/creator", response_model=ObjectIdentityResponse)
async def register_object_creator(
    object_id: str,
    payload: RegisterCreatorRequest,
    x_ruinform_wallet_session: str | None = Header(default=None, alias="x-ruinform-wallet-session"),
) -> ObjectIdentityResponse:
    return register_creator(
        object_id=object_id,
        wallet_session=x_ruinform_wallet_session,
        source_session_id=payload.source_session_id,
        candidate_id=payload.candidate_id,
    )


@router.post("/v1/object-identity/{object_id}/claim", response_model=ObjectIdentityResponse)
async def claim_object_ownership(
    object_id: str,
    x_ruinform_wallet_session: str | None = Header(default=None, alias="x-ruinform-wallet-session"),
) -> ObjectIdentityResponse:
    return claim_object(object_id=object_id, wallet_session=x_ruinform_wallet_session)

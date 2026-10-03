from __future__ import annotations

import base64
import sqlite3
from uuid import uuid4

from fastapi import HTTPException
from nacl.exceptions import BadSignatureError
from nacl.signing import VerifyKey

from . import nft_devnet
from . import object_economics as legacy
from . import object_economics_v2 as v2
from .object_passport import ObjectPassportNotFound, object_store
from .wallet_identity import _validated_wallet, resolve_wallet_session


TERMS_VERSION = v2.TERMS_VERSION
TERMS_TEXT = v2.TERMS_TEXT
TERMS_HASH = v2.TERMS_HASH
ROYALTY_BPS = legacy.ROYALTY_BPS
CHAIN = legacy.CHAIN


def _ensure_history_sqlite(conn: sqlite3.Connection) -> None:
    legacy._ensure_sqlite_schema(conn)
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS ruinform_creator_agreement_history (
            object_id TEXT NOT NULL,
            wallet_address TEXT NOT NULL,
            terms_version TEXT NOT NULL,
            terms_hash TEXT NOT NULL,
            royalty_bps INTEGER NOT NULL,
            signed_message TEXT NOT NULL,
            signature_base64 TEXT NOT NULL,
            signed_at_iso TEXT NOT NULL,
            PRIMARY KEY(object_id, terms_hash)
        )
        """
    )
    conn.execute(
        """
        INSERT OR IGNORE INTO ruinform_creator_agreement_history(
            object_id,wallet_address,terms_version,terms_hash,royalty_bps,signed_message,signature_base64,signed_at_iso
        )
        SELECT object_id,wallet_address,terms_version,terms_hash,royalty_bps,signed_message,signature_base64,signed_at_iso
        FROM ruinform_creator_agreements
        """
    )


def _ensure_history_postgres(conn) -> None:
    legacy._ensure_postgres_schema(conn)
    with conn.cursor() as cur:
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS ruinform_creator_agreement_history (
                object_id TEXT NOT NULL,
                wallet_address TEXT NOT NULL,
                terms_version TEXT NOT NULL,
                terms_hash TEXT NOT NULL,
                royalty_bps INTEGER NOT NULL,
                signed_message TEXT NOT NULL,
                signature_base64 TEXT NOT NULL,
                signed_at_iso TEXT NOT NULL,
                PRIMARY KEY(object_id, terms_hash)
            )
            """
        )
        cur.execute(
            """
            INSERT INTO ruinform_creator_agreement_history(
                object_id,wallet_address,terms_version,terms_hash,royalty_bps,signed_message,signature_base64,signed_at_iso
            )
            SELECT object_id,wallet_address,terms_version,terms_hash,royalty_bps,signed_message,signature_base64,signed_at_iso
            FROM ruinform_creator_agreements
            ON CONFLICT(object_id, terms_hash) DO NOTHING
            """
        )
    conn.commit()


def _read_current_agreement(object_id: str) -> tuple | None:
    database_url = legacy._database_url()
    if database_url:
        import psycopg
        with psycopg.connect(database_url) as conn:
            _ensure_history_postgres(conn)
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT wallet_address,terms_version,terms_hash,royalty_bps,signed_at_iso FROM ruinform_creator_agreement_history WHERE object_id=%s AND terms_hash=%s",
                    (object_id, TERMS_HASH),
                )
                return cur.fetchone()
    with sqlite3.connect(legacy._sqlite_path()) as conn:
        _ensure_history_sqlite(conn)
        return conn.execute(
            "SELECT wallet_address,terms_version,terms_hash,royalty_bps,signed_at_iso FROM ruinform_creator_agreement_history WHERE object_id=? AND terms_hash=?",
            (object_id, TERMS_HASH),
        ).fetchone()


def read_object_economics(object_id: str):
    backend_id = legacy._backend_object_id(object_id)
    # Base response still owns creator/NFT state. Agreement state and mint blockers
    # are recomputed below from the current immutable terms hash.
    result = v2._legacy_read_object_economics(backend_id)
    current = _read_current_agreement(backend_id)

    result.agreement_status = "SIGNED" if current is not None else "NOT_SIGNED"
    result.terms_version = str(current[1]) if current else TERMS_VERSION
    result.terms_hash = str(current[2]) if current else TERMS_HASH
    result.terms_text = TERMS_TEXT
    result.royalty_bps = int(current[3]) if current else ROYALTY_BPS
    result.royalty_percent = result.royalty_bps / 100
    result.signed_at_iso = str(current[4]) if current else None

    blockers: list[str] = []
    if not result.creator_wallet:
        blockers.append("CREATOR_NOT_REGISTERED")
    if current is None:
        blockers.append("CREATOR_AGREEMENT_NOT_SIGNED")
    if v2._live_proof_status(backend_id) != "valid":
        blockers.append("LIVE_PHYSICAL_PROOF_REQUIRED")
    if result.nft_status == "MINTED":
        blockers.append("CANONICAL_NFT_ALREADY_MINTED")
    result.blockers = blockers
    result.eligible_to_mint = not blockers
    return result


def issue_creator_agreement_challenge(object_id: str, wallet_session: str | None):
    backend_id = legacy._backend_object_id(object_id)
    try:
        object_store().get(backend_id)
    except ObjectPassportNotFound as exc:
        raise HTTPException(status_code=404, detail="Object Passport not found") from exc

    session = resolve_wallet_session(wallet_session)
    creator = legacy._creator_for(backend_id)
    if creator != session.wallet_address:
        raise HTTPException(status_code=403, detail="Only the registered creator can sign this Creator Agreement")
    if _read_current_agreement(backend_id) is not None:
        raise HTTPException(status_code=409, detail="This exact Creator Agreement version is already signed for the Object Passport")

    issued = legacy._utc_now()
    expires = issued + legacy.timedelta(minutes=legacy._AGREEMENT_TTL_MINUTES)
    challenge_id = uuid4().hex
    nonce = legacy.secrets.token_hex(16).upper()
    message = legacy._agreement_message(object_id=backend_id, wallet=creator, nonce=nonce, issued=issued, expires=expires)

    database_url = legacy._database_url()
    if database_url:
        import psycopg
        with psycopg.connect(database_url) as conn:
            legacy._ensure_postgres_schema(conn)
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO ruinform_creator_agreement_challenges(challenge_id,object_id,wallet_address,message,terms_version,terms_hash,expires_at_iso,used_at_iso) VALUES (%s,%s,%s,%s,%s,%s,%s,NULL)",
                    (challenge_id, backend_id, creator, message, TERMS_VERSION, TERMS_HASH, legacy._iso(expires)),
                )
            conn.commit()
    else:
        with sqlite3.connect(legacy._sqlite_path()) as conn:
            legacy._ensure_sqlite_schema(conn)
            conn.execute(
                "INSERT INTO ruinform_creator_agreement_challenges(challenge_id,object_id,wallet_address,message,terms_version,terms_hash,expires_at_iso,used_at_iso) VALUES (?,?,?,?,?,?,?,NULL)",
                (challenge_id, backend_id, creator, message, TERMS_VERSION, TERMS_HASH, legacy._iso(expires)),
            )

    return legacy.AgreementChallengeResponse(
        challenge_id=challenge_id,
        object_id=legacy._public_object_id(backend_id),
        wallet_address=creator,
        message=message,
        expires_at_iso=legacy._iso(expires),
        terms_version=TERMS_VERSION,
        terms_hash=TERMS_HASH,
        terms_text=TERMS_TEXT,
        royalty_bps=ROYALTY_BPS,
    )


def verify_creator_agreement(object_id: str, payload, wallet_session: str | None):
    backend_id = legacy._backend_object_id(object_id)
    session = resolve_wallet_session(wallet_session)
    row = legacy._load_challenge(payload.challenge_id, backend_id)
    wallet, message, version, terms_hash, expires_at_iso, used_at_iso = [str(value) if value is not None else None for value in row]
    if wallet != session.wallet_address:
        raise HTTPException(status_code=403, detail="Wallet session does not match this Creator Agreement challenge")
    if used_at_iso:
        raise HTTPException(status_code=409, detail="Creator Agreement challenge was already used")
    if version != TERMS_VERSION or terms_hash != TERMS_HASH:
        raise HTTPException(status_code=409, detail="Creator Agreement terms changed; request a fresh agreement")
    if legacy._parse_iso(str(expires_at_iso)) <= legacy._utc_now():
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

    now = legacy._iso(legacy._utc_now())
    database_url = legacy._database_url()
    if database_url:
        import psycopg
        with psycopg.connect(database_url) as conn:
            _ensure_history_postgres(conn)
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE ruinform_creator_agreement_challenges SET used_at_iso=%s WHERE challenge_id=%s AND used_at_iso IS NULL",
                    (now, payload.challenge_id),
                )
                if cur.rowcount != 1:
                    raise HTTPException(status_code=409, detail="Creator Agreement challenge was already used")
                cur.execute(
                    "INSERT INTO ruinform_creator_agreement_history(object_id,wallet_address,terms_version,terms_hash,royalty_bps,signed_message,signature_base64,signed_at_iso) VALUES (%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT(object_id,terms_hash) DO NOTHING",
                    (backend_id, wallet, TERMS_VERSION, TERMS_HASH, ROYALTY_BPS, message, payload.signature_base64, now),
                )
                # Keep the original one-row V0 table as legacy audit data; never overwrite it.
                cur.execute(
                    "INSERT INTO ruinform_creator_agreements(object_id,wallet_address,terms_version,terms_hash,royalty_bps,signed_message,signature_base64,signed_at_iso) VALUES (%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT(object_id) DO NOTHING",
                    (backend_id, wallet, TERMS_VERSION, TERMS_HASH, ROYALTY_BPS, message, payload.signature_base64, now),
                )
                cur.execute(
                    "INSERT INTO ruinform_nft_passports(object_id,chain,status,mint_address,royalty_bps,terms_hash,minted_at_iso) VALUES (%s,%s,'NOT_MINTED',NULL,%s,%s,NULL) ON CONFLICT(object_id) DO UPDATE SET royalty_bps=EXCLUDED.royalty_bps,terms_hash=EXCLUDED.terms_hash WHERE ruinform_nft_passports.status<>'MINTED'",
                    (backend_id, CHAIN, ROYALTY_BPS, TERMS_HASH),
                )
            conn.commit()
    else:
        with sqlite3.connect(legacy._sqlite_path()) as conn:
            _ensure_history_sqlite(conn)
            cursor = conn.execute(
                "UPDATE ruinform_creator_agreement_challenges SET used_at_iso=? WHERE challenge_id=? AND used_at_iso IS NULL",
                (now, payload.challenge_id),
            )
            if cursor.rowcount != 1:
                raise HTTPException(status_code=409, detail="Creator Agreement challenge was already used")
            conn.execute(
                "INSERT OR IGNORE INTO ruinform_creator_agreement_history(object_id,wallet_address,terms_version,terms_hash,royalty_bps,signed_message,signature_base64,signed_at_iso) VALUES (?,?,?,?,?,?,?,?)",
                (backend_id, wallet, TERMS_VERSION, TERMS_HASH, ROYALTY_BPS, message, payload.signature_base64, now),
            )
            conn.execute(
                "INSERT OR IGNORE INTO ruinform_creator_agreements(object_id,wallet_address,terms_version,terms_hash,royalty_bps,signed_message,signature_base64,signed_at_iso) VALUES (?,?,?,?,?,?,?,?)",
                (backend_id, wallet, TERMS_VERSION, TERMS_HASH, ROYALTY_BPS, message, payload.signature_base64, now),
            )
            conn.execute(
                "INSERT OR IGNORE INTO ruinform_nft_passports(object_id,chain,status,mint_address,royalty_bps,terms_hash,minted_at_iso) VALUES (?,?,'NOT_MINTED',NULL,?,?,NULL)",
                (backend_id, CHAIN, ROYALTY_BPS, TERMS_HASH),
            )
            conn.execute(
                "UPDATE ruinform_nft_passports SET royalty_bps=?,terms_hash=? WHERE object_id=? AND status<>'MINTED'",
                (ROYALTY_BPS, TERMS_HASH, backend_id),
            )

    return read_object_economics(backend_id)


# Route handlers were declared in object_economics.py and resolve these globals at
# request time, so patching them upgrades the existing public contract without a
# duplicate route surface.
legacy.TERMS_VERSION = TERMS_VERSION
legacy.TERMS_TEXT = TERMS_TEXT
legacy.TERMS_HASH = TERMS_HASH
legacy.read_object_economics = read_object_economics
legacy.issue_creator_agreement_challenge = issue_creator_agreement_challenge
legacy.verify_creator_agreement = verify_creator_agreement
v2.read_object_economics = read_object_economics
nft_devnet.read_object_economics = read_object_economics

router = legacy.router

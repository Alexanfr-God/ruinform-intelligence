from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal
from uuid import uuid4

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, Field

from .object_passport import ObjectPassportNotFound, object_store
from .wallet_identity import _identity_row, resolve_wallet_session


router = APIRouter(tags=["verification-disputes"])

DisputeStatus = Literal["NONE", "OPEN", "UPHELD", "OVERRIDDEN", "NEW_PROOF_REQUESTED", "RESOLVED"]


class VerificationDisputeCreateRequest(BaseModel):
    reason: str = Field(min_length=10, max_length=2400)


class VerificationDisputeResponse(BaseModel):
    object_id: str
    status: DisputeStatus
    dispute_id: str | None = None
    creator_wallet: str | None = None
    original_proof_status: str | None = None
    original_score: int | None = None
    original_verdict: str | None = None
    original_verification_status: str | None = None
    reason: str | None = None
    created_at_iso: str | None = None
    resolution_note: str | None = None
    resolved_at_iso: str | None = None
    override_score: int | None = None


def _database_url() -> str | None:
    return os.getenv("DATABASE_URL") or os.getenv("RUINFORM_DATABASE_URL")


def _sqlite_path() -> Path:
    path = Path(os.getenv("RUINFORM_DB_PATH", ".ruinform/ruinform.db"))
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


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
        CREATE TABLE IF NOT EXISTS ruinform_verification_disputes (
            dispute_id TEXT PRIMARY KEY,
            object_id TEXT NOT NULL,
            creator_wallet TEXT NOT NULL,
            original_proof_status TEXT,
            original_score INTEGER,
            original_verdict TEXT,
            original_verification_status TEXT,
            reason TEXT NOT NULL,
            status TEXT NOT NULL,
            created_at_iso TEXT NOT NULL,
            resolution_note TEXT,
            resolved_at_iso TEXT,
            override_score INTEGER
        )
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_ruinform_verification_disputes_object ON ruinform_verification_disputes(object_id, created_at_iso DESC)"
    )


def _ensure_postgres_schema(conn) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS ruinform_verification_disputes (
                dispute_id TEXT PRIMARY KEY,
                object_id TEXT NOT NULL,
                creator_wallet TEXT NOT NULL,
                original_proof_status TEXT,
                original_score INTEGER,
                original_verdict TEXT,
                original_verification_status TEXT,
                reason TEXT NOT NULL,
                status TEXT NOT NULL,
                created_at_iso TEXT NOT NULL,
                resolution_note TEXT,
                resolved_at_iso TEXT,
                override_score INTEGER
            )
            """
        )
        cur.execute(
            "CREATE INDEX IF NOT EXISTS idx_ruinform_verification_disputes_object ON ruinform_verification_disputes(object_id, created_at_iso DESC)"
        )
    conn.commit()


def _verification_snapshot(object_id: str) -> dict:
    database_url = _database_url()
    row = None
    if database_url:
        import psycopg

        with psycopg.connect(database_url) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT payload_json FROM ruinform_objects WHERE object_id=%s", (object_id,))
                row = cur.fetchone()
    else:
        path = _sqlite_path()
        if not path.exists():
            raise HTTPException(status_code=404, detail="Object Passport not found")
        with sqlite3.connect(path) as conn:
            row = conn.execute("SELECT payload_json FROM ruinform_objects WHERE object_id=?", (object_id,)).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Object Passport not found")
    try:
        payload = json.loads(row[0])
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=500, detail="Object Passport verification provenance is unreadable") from exc
    return payload


def _latest_row(object_id: str) -> tuple | None:
    database_url = _database_url()
    if database_url:
        import psycopg

        with psycopg.connect(database_url) as conn:
            _ensure_postgres_schema(conn)
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT dispute_id,creator_wallet,original_proof_status,original_score,original_verdict,original_verification_status,reason,status,created_at_iso,resolution_note,resolved_at_iso,override_score FROM ruinform_verification_disputes WHERE object_id=%s ORDER BY created_at_iso DESC LIMIT 1",
                    (object_id,),
                )
                return cur.fetchone()
    with sqlite3.connect(_sqlite_path()) as conn:
        _ensure_sqlite_schema(conn)
        return conn.execute(
            "SELECT dispute_id,creator_wallet,original_proof_status,original_score,original_verdict,original_verification_status,reason,status,created_at_iso,resolution_note,resolved_at_iso,override_score FROM ruinform_verification_disputes WHERE object_id=? ORDER BY created_at_iso DESC LIMIT 1",
            (object_id,),
        ).fetchone()


def _response(object_id: str, row: tuple | None) -> VerificationDisputeResponse:
    if row is None:
        return VerificationDisputeResponse(object_id=_public_object_id(object_id), status="NONE")
    return VerificationDisputeResponse(
        object_id=_public_object_id(object_id),
        dispute_id=str(row[0]),
        creator_wallet=str(row[1]),
        original_proof_status=str(row[2]) if row[2] is not None else None,
        original_score=int(row[3]) if row[3] is not None else None,
        original_verdict=str(row[4]) if row[4] is not None else None,
        original_verification_status=str(row[5]) if row[5] is not None else None,
        reason=str(row[6]),
        status=str(row[7]),
        created_at_iso=str(row[8]),
        resolution_note=str(row[9]) if row[9] is not None else None,
        resolved_at_iso=str(row[10]) if row[10] is not None else None,
        override_score=int(row[11]) if row[11] is not None else None,
    )


def read_verification_dispute(object_id: str) -> VerificationDisputeResponse:
    backend_id = _backend_object_id(object_id)
    try:
        object_store().get(backend_id)
    except ObjectPassportNotFound as exc:
        raise HTTPException(status_code=404, detail="Object Passport not found") from exc
    return _response(backend_id, _latest_row(backend_id))


def open_verification_dispute(
    object_id: str,
    payload: VerificationDisputeCreateRequest,
    wallet_session: str | None,
) -> VerificationDisputeResponse:
    backend_id = _backend_object_id(object_id)
    try:
        passport = object_store().get(backend_id)
    except ObjectPassportNotFound as exc:
        raise HTTPException(status_code=404, detail="Object Passport not found") from exc

    session = resolve_wallet_session(wallet_session)
    identity = _identity_row(backend_id)
    if not identity.creator_wallet or identity.creator_wallet != session.wallet_address:
        raise HTTPException(status_code=403, detail="Only the registered creator can dispute this verification result")

    snapshot = _verification_snapshot(backend_id)
    if snapshot.get("verification_verdict") is None and snapshot.get("verification_proof_status") is None:
        raise HTTPException(status_code=409, detail="No completed verification assessment exists to dispute")

    latest = _latest_row(backend_id)
    if latest is not None and str(latest[7]) == "OPEN":
        raise HTTPException(status_code=409, detail="A creator appeal is already open for this object")

    dispute_id = uuid4().hex
    created = _utc_now_iso()
    values = (
        dispute_id,
        backend_id,
        session.wallet_address,
        snapshot.get("verification_proof_status"),
        snapshot.get("verification_score"),
        snapshot.get("verification_verdict"),
        passport.verification_status,
        payload.reason.strip(),
        "OPEN",
        created,
    )

    database_url = _database_url()
    if database_url:
        import psycopg

        with psycopg.connect(database_url) as conn:
            _ensure_postgres_schema(conn)
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO ruinform_verification_disputes(dispute_id,object_id,creator_wallet,original_proof_status,original_score,original_verdict,original_verification_status,reason,status,created_at_iso,resolution_note,resolved_at_iso,override_score) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,NULL,NULL,NULL)",
                    values,
                )
            conn.commit()
    else:
        with sqlite3.connect(_sqlite_path()) as conn:
            _ensure_sqlite_schema(conn)
            conn.execute(
                "INSERT INTO ruinform_verification_disputes(dispute_id,object_id,creator_wallet,original_proof_status,original_score,original_verdict,original_verification_status,reason,status,created_at_iso,resolution_note,resolved_at_iso,override_score) VALUES (?,?,?,?,?,?,?,?,?,?,NULL,NULL,NULL)",
                values,
            )

    return read_verification_dispute(backend_id)


@router.get("/v1/objects/{object_id}/verification-dispute", response_model=VerificationDisputeResponse)
async def get_verification_dispute(object_id: str) -> VerificationDisputeResponse:
    return read_verification_dispute(object_id)


@router.post("/v1/objects/{object_id}/verification-dispute", response_model=VerificationDisputeResponse)
async def create_verification_dispute(
    object_id: str,
    payload: VerificationDisputeCreateRequest,
    x_ruinform_wallet_session: str | None = Header(default=None, alias="x-ruinform-wallet-session"),
) -> VerificationDisputeResponse:
    return open_verification_dispute(object_id, payload, x_ruinform_wallet_session)

from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel

from .object_passport import ObjectPassportNotFound, object_store
from .wallet_identity import _identity_row, resolve_wallet_session


router = APIRouter(tags=["verification-checkpoint"])
_TEST_OVERRIDE_OBJECTS = {"RF-0005"}


class VerificationCheckpointResponse(BaseModel):
    object_id: str
    exists: bool
    build_status: str
    verification_status: str
    proof_status: str | None = None
    object_match_evaluated: bool = False
    overall_match: int | None = None
    silhouette_match: int | None = None
    material_match: int | None = None
    construction_match: int | None = None
    detail_match: int | None = None
    verdict: str | None = None
    confidence: int | None = None
    summary: str | None = None
    matching_features: list[str] = []
    deviations: list[str] = []
    next_capture_request: str | None = None
    challenge_code_visible_in_all: bool | None = None
    challenge_code_match_confidence: int | None = None
    challenge_observations: list[str] = []
    updated_at_iso: str | None = None


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


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


def _read_payload(object_id: str) -> tuple[dict, str]:
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
        if path.exists():
            with sqlite3.connect(path) as conn:
                row = conn.execute("SELECT payload_json FROM ruinform_objects WHERE object_id=?", (object_id,)).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Object Passport not found")
    try:
        payload = json.loads(row[0])
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=500, detail="Object Passport checkpoint is unreadable") from exc
    return payload, str(row[0])


def _checkpoint(object_id: str, payload: dict) -> VerificationCheckpointResponse:
    proof_status = payload.get("verification_proof_status")
    verdict = payload.get("verification_verdict")
    exists = proof_status is not None or verdict is not None or payload.get("verification_updated_at_iso") is not None
    return VerificationCheckpointResponse(
        object_id=_public_object_id(object_id),
        exists=exists,
        build_status=str(payload.get("build_status") or "IDEA"),
        verification_status=str(payload.get("verification_status") or "UNVERIFIED"),
        proof_status=str(proof_status) if proof_status is not None else None,
        object_match_evaluated=bool(payload.get("verification_object_match_evaluated", False)),
        overall_match=payload.get("verification_score"),
        silhouette_match=payload.get("verification_silhouette_match"),
        material_match=payload.get("verification_material_match"),
        construction_match=payload.get("verification_construction_match"),
        detail_match=payload.get("verification_detail_match"),
        verdict=str(verdict) if verdict is not None else None,
        confidence=payload.get("verification_confidence"),
        summary=str(payload.get("verification_summary")) if payload.get("verification_summary") is not None else None,
        matching_features=list(payload.get("verification_matching_features") or []),
        deviations=list(payload.get("verification_deviations") or []),
        next_capture_request=str(payload.get("verification_next_capture_request")) if payload.get("verification_next_capture_request") is not None else None,
        challenge_code_visible_in_all=payload.get("verification_challenge_visible_in_all"),
        challenge_code_match_confidence=payload.get("verification_challenge_confidence"),
        challenge_observations=list(payload.get("verification_challenge_observations") or []),
        updated_at_iso=str(payload.get("verification_updated_at_iso")) if payload.get("verification_updated_at_iso") is not None else None,
    )


def _ensure_history_schema_sqlite(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS ruinform_verification_history (
            event_id TEXT PRIMARY KEY,
            object_id TEXT NOT NULL,
            event_type TEXT NOT NULL,
            snapshot_json TEXT NOT NULL,
            actor_wallet TEXT,
            created_at_iso TEXT NOT NULL
        )
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_ruinform_verification_history_object ON ruinform_verification_history(object_id, created_at_iso DESC)")


def _ensure_history_schema_postgres(conn) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS ruinform_verification_history (
                event_id TEXT PRIMARY KEY,
                object_id TEXT NOT NULL,
                event_type TEXT NOT NULL,
                snapshot_json TEXT NOT NULL,
                actor_wallet TEXT,
                created_at_iso TEXT NOT NULL
            )
            """
        )
        cur.execute("CREATE INDEX IF NOT EXISTS idx_ruinform_verification_history_object ON ruinform_verification_history(object_id, created_at_iso DESC)")
    conn.commit()


def _reset_payload(payload: dict) -> dict:
    for key in list(payload.keys()):
        if key.startswith("verification_"):
            payload.pop(key, None)
    payload["build_status"] = "IDEA"
    payload["verification_status"] = "UNVERIFIED"
    payload["last_verification_reset_at_iso"] = _utc_now_iso()
    return payload


def _write_payload_with_history(object_id: str, actor_wallet: str, event_type: str, snapshot_json: str, payload: dict) -> None:
    event_id = uuid4().hex
    now = _utc_now_iso()
    next_json = json.dumps(payload, separators=(",", ":"), ensure_ascii=False)
    database_url = _database_url()
    if database_url:
        import psycopg
        with psycopg.connect(database_url) as conn:
            _ensure_history_schema_postgres(conn)
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO ruinform_verification_history(event_id,object_id,event_type,snapshot_json,actor_wallet,created_at_iso) VALUES (%s,%s,%s,%s,%s,%s)",
                    (event_id, object_id, event_type, snapshot_json, actor_wallet, now),
                )
                cur.execute("UPDATE ruinform_objects SET payload_json=%s WHERE object_id=%s", (next_json, object_id))
            conn.commit()
        return
    with sqlite3.connect(_sqlite_path()) as conn:
        _ensure_history_schema_sqlite(conn)
        conn.execute(
            "INSERT INTO ruinform_verification_history(event_id,object_id,event_type,snapshot_json,actor_wallet,created_at_iso) VALUES (?,?,?,?,?,?)",
            (event_id, object_id, event_type, snapshot_json, actor_wallet, now),
        )
        conn.execute("UPDATE ruinform_objects SET payload_json=? WHERE object_id=?", (next_json, object_id))


def _soft_reset(object_id: str, actor_wallet: str, snapshot_json: str, payload: dict) -> None:
    _write_payload_with_history(object_id, actor_wallet, "RESET", snapshot_json, _reset_payload(payload))


def _test_override_payload(payload: dict) -> dict:
    now = _utc_now_iso()
    payload["build_status"] = "VERIFIED"
    payload["verification_status"] = "VERIFIED"
    payload["verification_proof_status"] = "valid"
    payload["verification_object_match_evaluated"] = True
    payload["verification_score"] = 92
    payload["verification_silhouette_match"] = 92
    payload["verification_material_match"] = 92
    payload["verification_construction_match"] = 92
    payload["verification_detail_match"] = 92
    payload["verification_verdict"] = "test_override_pass"
    payload["verification_confidence"] = 100
    payload["verification_summary"] = "DEVNET TEST OVERRIDE: RuF-0005 was manually advanced for mint-flow testing. This is not a production physical-verification result."
    payload["verification_matching_features"] = ["Devnet mint-flow test override"]
    payload["verification_deviations"] = []
    payload["verification_next_capture_request"] = None
    payload["verification_challenge_visible_in_all"] = True
    payload["verification_challenge_confidence"] = 100
    payload["verification_challenge_observations"] = ["Test-only creator-authorized override for RuF-0005"]
    payload["verification_test_override"] = True
    payload["verification_updated_at_iso"] = now
    payload["test_override_bootstrap_consumed"] = True
    return payload


def _bootstrap_ruf_0005_test_override() -> None:
    backend_id = "RF-0005"
    try:
        payload, raw = _read_payload(backend_id)
        if payload.get("test_override_bootstrap_consumed") is True:
            return
        identity = _identity_row(backend_id)
        actor = identity.creator_wallet or "SYSTEM_DEVNET_TEST"
        _write_payload_with_history(
            backend_id,
            actor,
            "TEST_OVERRIDE_BOOTSTRAP",
            raw,
            _test_override_payload(payload),
        )
    except Exception:
        # This is a one-object devnet migration only; it must never block service startup.
        return


_bootstrap_ruf_0005_test_override()


@router.get("/v1/objects/{object_id}/verification-checkpoint", response_model=VerificationCheckpointResponse)
async def get_verification_checkpoint(object_id: str) -> VerificationCheckpointResponse:
    backend_id = _backend_object_id(object_id)
    try:
        object_store().get(backend_id)
    except ObjectPassportNotFound as exc:
        raise HTTPException(status_code=404, detail="Object Passport not found") from exc
    payload, _ = _read_payload(backend_id)
    return _checkpoint(backend_id, payload)


@router.post("/v1/objects/{object_id}/verification-reset", response_model=VerificationCheckpointResponse)
async def reset_verification_checkpoint(
    object_id: str,
    x_ruinform_wallet_session: str | None = Header(default=None, alias="x-ruinform-wallet-session"),
) -> VerificationCheckpointResponse:
    backend_id = _backend_object_id(object_id)
    try:
        object_store().get(backend_id)
    except ObjectPassportNotFound as exc:
        raise HTTPException(status_code=404, detail="Object Passport not found") from exc

    session = resolve_wallet_session(x_ruinform_wallet_session)
    identity = _identity_row(backend_id)
    if not identity.creator_wallet or identity.creator_wallet != session.wallet_address:
        raise HTTPException(status_code=403, detail="Only the registered creator can reset this verification stage")

    payload, raw = _read_payload(backend_id)
    current = _checkpoint(backend_id, payload)
    if not current.exists:
        return current
    _soft_reset(backend_id, session.wallet_address, raw, payload)
    next_payload, _ = _read_payload(backend_id)
    return _checkpoint(backend_id, next_payload)


@router.post("/v1/objects/{object_id}/verification-test-override", response_model=VerificationCheckpointResponse)
async def test_override_verification_checkpoint(
    object_id: str,
    x_ruinform_wallet_session: str | None = Header(default=None, alias="x-ruinform-wallet-session"),
) -> VerificationCheckpointResponse:
    backend_id = _backend_object_id(object_id)
    if backend_id not in _TEST_OVERRIDE_OBJECTS:
        raise HTTPException(status_code=404, detail="Test override is not enabled for this Object ID")
    try:
        object_store().get(backend_id)
    except ObjectPassportNotFound as exc:
        raise HTTPException(status_code=404, detail="Object Passport not found") from exc

    session = resolve_wallet_session(x_ruinform_wallet_session)
    identity = _identity_row(backend_id)
    if not identity.creator_wallet or identity.creator_wallet != session.wallet_address:
        raise HTTPException(status_code=403, detail="Only the registered creator can apply the test override")

    payload, raw = _read_payload(backend_id)
    if payload.get("verification_test_override") is True and str(payload.get("verification_proof_status")).lower() == "valid":
        return _checkpoint(backend_id, payload)
    _write_payload_with_history(
        backend_id,
        session.wallet_address,
        "TEST_OVERRIDE",
        raw,
        _test_override_payload(payload),
    )
    next_payload, _ = _read_payload(backend_id)
    return _checkpoint(backend_id, next_payload)

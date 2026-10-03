from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from .verification import VerificationOutput


def verification_state_for(result: VerificationOutput) -> tuple[str, str]:
    """Map a two-gate verification result to durable passport state.

    Gate 1 (live proof) is binary and mandatory. No object similarity result can
    upgrade the passport unless the fresh challenge is valid. Gate 2 then maps
    valid physical evidence to VERIFIED / NEEDS_REVIEW / UNVERIFIED.
    """

    if (
        result.proof_status != "valid"
        or not result.challenge_code_visible_in_all
        or result.challenge_code_match_confidence < 80
        or not result.object_match_evaluated
    ):
        return "IDEA", "UNVERIFIED"

    if any(
        value is None
        for value in (
            result.overall_match,
            result.silhouette_match,
            result.material_match,
            result.construction_match,
            result.detail_match,
            result.confidence,
        )
    ):
        return "IDEA", "UNVERIFIED"

    overall_match = int(result.overall_match)
    confidence = int(result.confidence)

    if (
        result.verdict == "strong_match"
        and overall_match >= 85
        and confidence >= 80
        and not result.next_capture_request
    ):
        return "VERIFIED", "VERIFIED"

    if result.verdict == "weak_match" or overall_match < 50 or confidence < 40:
        return "IDEA", "UNVERIFIED"

    return "PHYSICAL", "NEEDS_REVIEW"


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _mutate_payload(payload_json: str, result: VerificationOutput) -> str:
    payload = json.loads(payload_json)
    build_status, verification_status = verification_state_for(result)
    payload["build_status"] = build_status
    payload["verification_status"] = verification_status

    # Preserve the AI assessment separately from the simplified passport state.
    # These fields are provenance: they remain available for creator appeals,
    # NFT metadata, and later human review without changing the permanent RuF ID.
    payload["verification_proof_status"] = result.proof_status
    payload["verification_object_match_evaluated"] = result.object_match_evaluated
    payload["verification_score"] = result.overall_match
    payload["verification_verdict"] = result.verdict
    payload["verification_confidence"] = result.confidence
    payload["verification_summary"] = result.summary
    payload["verification_challenge_confidence"] = result.challenge_code_match_confidence
    payload["verification_updated_at_iso"] = _utc_now_iso()
    return json.dumps(payload, separators=(",", ":"), ensure_ascii=False)


def _update_sqlite(*, source_session_id: str, candidate_id: str, result: VerificationOutput) -> bool:
    path = Path(os.getenv("RUINFORM_DB_PATH", ".ruinform/ruinform.db"))
    if not path.exists():
        return False
    with sqlite3.connect(path) as conn:
        row = conn.execute(
            "SELECT payload_json FROM ruinform_objects WHERE source_session_id = ? AND candidate_id = ?",
            (source_session_id, candidate_id),
        ).fetchone()
        if row is None:
            return False
        conn.execute(
            "UPDATE ruinform_objects SET payload_json = ? WHERE source_session_id = ? AND candidate_id = ?",
            (_mutate_payload(row[0], result), source_session_id, candidate_id),
        )
    return True


def _update_postgres(*, source_session_id: str, candidate_id: str, result: VerificationOutput) -> bool:
    database_url = os.getenv("DATABASE_URL") or os.getenv("RUINFORM_DATABASE_URL")
    if not database_url:
        return False
    import psycopg

    with psycopg.connect(database_url) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT payload_json FROM ruinform_objects WHERE source_session_id = %s AND candidate_id = %s",
                (source_session_id, candidate_id),
            )
            row = cur.fetchone()
            if row is None:
                return False
            cur.execute(
                "UPDATE ruinform_objects SET payload_json = %s WHERE source_session_id = %s AND candidate_id = %s",
                (_mutate_payload(row[0], result), source_session_id, candidate_id),
            )
        conn.commit()
    return True


def apply_verification_result(
    *,
    source_session_id: str,
    candidate_id: str,
    result: VerificationOutput,
) -> bool:
    """Update an existing Object Passport without changing its permanent ID."""

    if os.getenv("DATABASE_URL") or os.getenv("RUINFORM_DATABASE_URL"):
        return _update_postgres(
            source_session_id=source_session_id,
            candidate_id=candidate_id,
            result=result,
        )
    return _update_sqlite(
        source_session_id=source_session_id,
        candidate_id=candidate_id,
        result=result,
    )

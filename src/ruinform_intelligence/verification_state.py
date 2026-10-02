from __future__ import annotations

import json
import os
import sqlite3
from pathlib import Path

from .verification import VerificationOutput


def verification_state_for(result: VerificationOutput) -> tuple[str, str]:
    """Map a visual verification result to durable passport state.

    VERIFIED is intentionally conservative. A valid live challenge is a hard gate:
    visual similarity alone can never verify a passport. Anything credible but not
    decisive is kept for human/admin review; weak or invalid evidence never upgrades
    the passport merely because a camera submission happened.
    """

    if (
        not result.challenge_code_visible_in_all
        or result.challenge_code_match_confidence < 80
    ):
        return "IDEA", "UNVERIFIED"

    if (
        result.verdict == "strong_match"
        and result.overall_match >= 85
        and result.confidence >= 80
        and not result.next_capture_request
    ):
        return "VERIFIED", "VERIFIED"

    if result.verdict == "weak_match" or result.overall_match < 50 or result.confidence < 40:
        return "IDEA", "UNVERIFIED"

    return "PHYSICAL", "NEEDS_REVIEW"


def _mutate_payload(payload_json: str, result: VerificationOutput) -> str:
    payload = json.loads(payload_json)
    build_status, verification_status = verification_state_for(result)
    payload["build_status"] = build_status
    payload["verification_status"] = verification_status
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

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from uuid import uuid4


MIGRATION_ID = "legacy-rf0004-verification-20261003-v1"
OBJECT_ID = "RF-0004"
SOURCE_SESSION_ID = "f0bfd7b6-ab53-4085-8648-053e2fb95f54"
CANDIDATE_ID = "preview_02_mutation"
HISTORICAL_VERIFY_AT = "2026-10-03T00:49:30.846651Z"


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def recover_known_legacy_passports() -> None:
    """Recover one pre-checkpoint verification result without inventing provenance.

    RF-0004 was verified before durable verification checkpoint fields shipped.
    Render request logs preserve the successful verify-upload timestamp and the
    creator-confirmed result was captured in the product test. This migration is
    deliberately object-specific, idempotent, and refuses to replace any newer
    verification checkpoint.
    """

    database_url = os.getenv("DATABASE_URL") or os.getenv("RUINFORM_DATABASE_URL")
    if not database_url:
        return

    import psycopg

    with psycopg.connect(database_url) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT payload_json FROM ruinform_objects WHERE object_id=%s AND source_session_id=%s AND candidate_id=%s",
                (OBJECT_ID, SOURCE_SESSION_ID, CANDIDATE_ID),
            )
            row = cur.fetchone()
            if row is None:
                return

            try:
                payload = json.loads(row[0])
            except (TypeError, ValueError):
                return

            migrations = list(payload.get("legacy_migrations") or [])
            if MIGRATION_ID in migrations:
                return

            # Never overwrite a later durable verification run.
            if payload.get("verification_proof_status") is not None or payload.get("verification_updated_at_iso") is not None:
                return

            recovery = {
                "migration_id": MIGRATION_ID,
                "object_id": "RuF-0004",
                "source_session_id": SOURCE_SESSION_ID,
                "candidate_id": CANDIDATE_ID,
                "verify_upload_http_status": 200,
                "verify_upload_at_iso": HISTORICAL_VERIFY_AT,
                "source": "server request log + creator-confirmed product test result",
                "note": "Recovered after the pre-checkpoint UI result was lost from active passport state.",
            }

            previous_state = {
                "build_status": payload.get("build_status"),
                "verification_status": payload.get("verification_status"),
            }

            payload.update(
                {
                    "build_status": "IDEA",
                    "verification_status": "UNVERIFIED",
                    "verification_proof_status": "valid",
                    "verification_object_match_evaluated": True,
                    "verification_score": 14,
                    "verification_silhouette_match": 20,
                    "verification_material_match": 35,
                    "verification_construction_match": 5,
                    "verification_detail_match": 4,
                    "verification_verdict": "weak_match",
                    "verification_confidence": 91,
                    "verification_summary": (
                        "Live proof passes, but the photographed build does not preserve the defining transformation "
                        "of Command Overflow. It shows an intact black remote beside a flat paper sheet with a simple "
                        "hand-drawn remote rather than a continuous curling ribbon carrying a complete mirrored command field."
                    ),
                    "verification_next_capture_request": (
                        "Construct a continuous curled ribbon with a complete mirrored command field; capture a clear side "
                        "view showing how the ribbon emerges from or joins the intact remote; keep the physical VAA5 marker "
                        "visible in every photo."
                    ),
                    "verification_challenge_visible_in_all": True,
                    "verification_updated_at_iso": HISTORICAL_VERIFY_AT,
                    "verification_recovery": recovery,
                    "legacy_migrations": [*migrations, MIGRATION_ID],
                }
            )

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
            cur.execute(
                "CREATE INDEX IF NOT EXISTS idx_ruinform_verification_history_object ON ruinform_verification_history(object_id, created_at_iso DESC)"
            )
            cur.execute(
                "UPDATE ruinform_objects SET payload_json=%s WHERE object_id=%s AND source_session_id=%s AND candidate_id=%s",
                (
                    json.dumps(payload, separators=(",", ":"), ensure_ascii=False),
                    OBJECT_ID,
                    SOURCE_SESSION_ID,
                    CANDIDATE_ID,
                ),
            )
            cur.execute(
                "INSERT INTO ruinform_verification_history(event_id,object_id,event_type,snapshot_json,actor_wallet,created_at_iso) VALUES (%s,%s,%s,%s,%s,%s)",
                (
                    uuid4().hex,
                    OBJECT_ID,
                    "LEGACY_RECOVERY",
                    json.dumps({"recovery": recovery, "previous_state": previous_state}, separators=(",", ":"), ensure_ascii=False),
                    None,
                    _utc_now_iso(),
                ),
            )
        conn.commit()

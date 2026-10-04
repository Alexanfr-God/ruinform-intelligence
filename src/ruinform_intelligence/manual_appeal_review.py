from __future__ import annotations

import json
import os
import sqlite3
from typing import Literal

from fastapi import Header, HTTPException
from pydantic import BaseModel, Field

from . import object_economics_v2 as economics_v2
from . import verification_disputes as disputes


router = disputes.router
Decision = Literal["APPROVE", "REJECT", "REQUEST_NEW_PROOF"]


class ManualAppealDecision(BaseModel):
    decision: Decision
    note: str = Field(min_length=3, max_length=2400)
    score: int | None = Field(default=None, ge=0, le=100)


def _reviewed_object_payload(
    current: dict,
    *,
    decision: Decision,
    reviewer: str,
    note: str,
    score: int | None,
    resolved_at: str,
) -> dict:
    next_payload = dict(current)
    next_payload["verification_moderation_status"] = decision
    next_payload["verification_moderation_source"] = "HUMAN_APPEAL_REVIEW"
    next_payload["verification_moderation_reviewer"] = reviewer
    next_payload["verification_moderation_note"] = note
    next_payload["verification_moderation_score"] = score
    next_payload["verification_moderation_resolved_at_iso"] = resolved_at

    # The original machine assessment remains untouched. Human review controls
    # only the final state used by the product after an appeal.
    if decision == "APPROVE":
        next_payload["verification_human_approved"] = True
        next_payload["build_status"] = "VERIFIED"
        next_payload["verification_status"] = "VERIFIED"
    elif decision == "REQUEST_NEW_PROOF":
        next_payload["verification_human_approved"] = False
        next_payload["verification_status"] = "NEEDS_REVIEW"
        next_payload["verification_next_capture_request"] = note
    else:
        next_payload["verification_human_approved"] = False
    return next_payload


def resolve_appeal(object_id: str, payload: ManualAppealDecision, reviewer: str):
    backend_id = disputes._backend_object_id(object_id)
    row = disputes._latest_row(backend_id)
    if row is None:
        raise HTTPException(status_code=404, detail="No appeal exists for this object")
    if str(row[7]) != "OPEN":
        raise HTTPException(status_code=409, detail=f"Latest appeal is already {row[7]}")

    status = "OVERRIDDEN" if payload.decision == "APPROVE" else "UPHELD" if payload.decision == "REJECT" else "NEW_PROOF_REQUESTED"
    note = f"reviewer={reviewer}; {payload.note.strip()}"
    now = disputes._utc_now_iso()
    dispute_id = str(row[0])
    current_object = disputes._verification_snapshot(backend_id)
    next_object = _reviewed_object_payload(
        current_object,
        decision=payload.decision,
        reviewer=reviewer,
        note=payload.note.strip(),
        score=payload.score,
        resolved_at=now,
    )
    next_json = json.dumps(next_object, separators=(",", ":"), ensure_ascii=False)

    database_url = disputes._database_url()
    if database_url:
        import psycopg
        with psycopg.connect(database_url) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE ruinform_verification_disputes SET status=%s,resolution_note=%s,resolved_at_iso=%s,override_score=%s WHERE dispute_id=%s AND status='OPEN'",
                    (status, note, now, payload.score, dispute_id),
                )
                if cur.rowcount != 1:
                    raise HTTPException(status_code=409, detail="Appeal was already resolved")
                cur.execute("UPDATE ruinform_objects SET payload_json=%s WHERE object_id=%s", (next_json, backend_id))
            conn.commit()
    else:
        with sqlite3.connect(disputes._sqlite_path()) as conn:
            cursor = conn.execute(
                "UPDATE ruinform_verification_disputes SET status=?,resolution_note=?,resolved_at_iso=?,override_score=? WHERE dispute_id=? AND status='OPEN'",
                (status, note, now, payload.score, dispute_id),
            )
            if cursor.rowcount != 1:
                raise HTTPException(status_code=409, detail="Appeal was already resolved")
            conn.execute("UPDATE ruinform_objects SET payload_json=? WHERE object_id=?", (next_json, backend_id))
    return disputes.read_verification_dispute(backend_id)


@router.post("/v1/admin/objects/{object_id}/appeal/resolve", response_model=disputes.VerificationDisputeResponse)
async def manual_appeal_resolution(
    object_id: str,
    payload: ManualAppealDecision,
    x_ruinform_reviewer: str | None = Header(default=None, alias="x-ruinform-reviewer"),
):
    return resolve_appeal(object_id, payload, (x_ruinform_reviewer or "RUINFORM_ADMIN").strip()[:160])


_original_live_proof_status = economics_v2._live_proof_status


def _live_proof_status_with_review(object_id: str) -> str | None:
    try:
        object_payload = disputes._verification_snapshot(disputes._backend_object_id(object_id))
    except HTTPException:
        return _original_live_proof_status(object_id)
    if (
        object_payload.get("verification_human_approved") is True
        and str(object_payload.get("verification_status") or "").upper() == "VERIFIED"
    ):
        return "valid"
    return _original_live_proof_status(object_id)


economics_v2._live_proof_status = _live_proof_status_with_review


def _apply_one_time_founder_review() -> None:
    object_id = os.getenv("RUINFORM_BOOTSTRAP_APPROVE_APPEAL_OBJECT", "").strip()
    if not object_id:
        return
    try:
        resolve_appeal(
            object_id,
            ManualAppealDecision(
                decision="APPROVE",
                note=os.getenv(
                    "RUINFORM_BOOTSTRAP_APPROVE_APPEAL_NOTE",
                    "Founder approved this creator appeal after human review.",
                ),
                score=100,
            ),
            "RUINFORM_FOUNDER",
        )
    except HTTPException as exc:
        # One-time startup action is intentionally idempotent.
        if exc.status_code in {404, 409}:
            return
        raise


_apply_one_time_founder_review()

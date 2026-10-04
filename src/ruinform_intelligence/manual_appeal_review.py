from __future__ import annotations

import sqlite3
from typing import Literal

from fastapi import Header, HTTPException
from pydantic import BaseModel, Field

from . import verification_disputes as disputes


router = disputes.router
Decision = Literal["APPROVE", "REJECT", "REQUEST_NEW_PROOF"]


class ManualAppealDecision(BaseModel):
    decision: Decision
    note: str = Field(min_length=3, max_length=2400)
    score: int | None = Field(default=None, ge=0, le=100)


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
            conn.commit()
    else:
        with sqlite3.connect(disputes._sqlite_path()) as conn:
            cursor = conn.execute(
                "UPDATE ruinform_verification_disputes SET status=?,resolution_note=?,resolved_at_iso=?,override_score=? WHERE dispute_id=? AND status='OPEN'",
                (status, note, now, payload.score, dispute_id),
            )
            if cursor.rowcount != 1:
                raise HTTPException(status_code=409, detail="Appeal was already resolved")
    return disputes.read_verification_dispute(backend_id)


@router.post("/v1/admin/objects/{object_id}/appeal/resolve", response_model=disputes.VerificationDisputeResponse)
async def manual_appeal_resolution(
    object_id: str,
    payload: ManualAppealDecision,
    x_ruinform_reviewer: str | None = Header(default=None, alias="x-ruinform-reviewer"),
):
    return resolve_appeal(object_id, payload, (x_ruinform_reviewer or "RUINFORM_ADMIN").strip()[:160])

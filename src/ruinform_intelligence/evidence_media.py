from __future__ import annotations

import base64
import hashlib
import hmac
import os
from urllib.parse import quote

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import Response

from .models import ProjectState
from .run_store import SessionNotFound, create_run_store


router = APIRouter(tags=["evidence-media"])


def _secret() -> bytes:
    value = os.getenv("RUINFORM_API_TOKEN")
    if not value:
        raise RuntimeError("RUINFORM_API_TOKEN is required for signed evidence URLs")
    return value.encode("utf-8")


def evidence_signature(session_id: str, evidence_id: str) -> str:
    message = f"{session_id}:{evidence_id}".encode("utf-8")
    return hmac.new(_secret(), message, hashlib.sha256).hexdigest()


def signed_evidence_url(session_id: str, evidence_id: str) -> str:
    base = os.getenv("RUINFORM_PUBLIC_BASE_URL", "https://ruinform-intelligence.onrender.com").rstrip("/")
    signature = evidence_signature(session_id, evidence_id)
    return (
        f"{base}/public/evidence/{quote(session_id, safe='')}/{quote(evidence_id, safe='')}"
        f"?sig={signature}"
    )


def externalize_state_for_render(state: ProjectState, *, session_id: str) -> ProjectState:
    evidence = []
    for item in state.evidence:
        if item.source_type == "image" and item.uri and item.uri.startswith("data:"):
            evidence.append(
                item.model_copy(update={"uri": signed_evidence_url(session_id, item.evidence_id)})
            )
        else:
            evidence.append(item)
    return state.model_copy(update={"evidence": evidence})


def _decode_data_url(uri: str) -> tuple[str, bytes]:
    if not uri.startswith("data:") or ";base64," not in uri:
        raise ValueError("Evidence image is not stored as a base64 data URL")
    header, payload = uri.split(",", 1)
    media_type = header[5:].split(";", 1)[0] or "application/octet-stream"
    try:
        body = base64.b64decode(payload, validate=True)
    except Exception as exc:  # pragma: no cover - defensive decoding guard
        raise ValueError("Evidence image payload is invalid base64") from exc
    return media_type, body


@router.get("/public/evidence/{session_id}/{evidence_id}", response_class=Response)
async def public_evidence(
    session_id: str,
    evidence_id: str,
    sig: str = Query(..., min_length=64, max_length=64),
) -> Response:
    expected = evidence_signature(session_id, evidence_id)
    if not hmac.compare_digest(sig, expected):
        raise HTTPException(status_code=403, detail="Invalid evidence signature")

    try:
        session = create_run_store().get(session_id)
    except SessionNotFound as exc:
        raise HTTPException(status_code=404, detail="Evidence session not found") from exc

    item = next(
        (evidence for evidence in session.project_state.evidence if evidence.evidence_id == evidence_id),
        None,
    )
    if item is None or item.source_type != "image" or not item.uri:
        raise HTTPException(status_code=404, detail="Evidence image not found")

    try:
        media_type, body = _decode_data_url(item.uri)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    return Response(
        content=body,
        media_type=media_type,
        headers={"Cache-Control": "private, max-age=600"},
    )

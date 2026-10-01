from __future__ import annotations

import base64
from uuid import uuid4

import httpx
from fastapi import APIRouter, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel, Field

from .library_store import (
    LibraryEntry,
    LibraryEntryNotFound,
    create_library_store,
    generation_id_for,
)
from .live_api import _upload_to_data_url, get_session, store
from .live_evidence import continue_session_evidence
from .models import EvidenceItem
from .render_models import RenderResult
from .review_store import ReviewItemNotFound, capture_session_render, create_review_store
from .run_store import SessionNotFound, create_run_store, utc_now_iso


router = APIRouter(prefix="/v1/library", tags=["generation-library"])
_BRANCH_PARENT_EVIDENCE_ID = "branch_parent_future"


class CaptureRequest(BaseModel):
    owner_id: str = Field(min_length=8, max_length=160)
    session_id: str = Field(min_length=8, max_length=160)
    parent_generation_id: str | None = Field(default=None, min_length=64, max_length=64)


class VisibilityRequest(BaseModel):
    owner_id: str = Field(min_length=8, max_length=160)
    is_public: bool


class ForkRequest(BaseModel):
    owner_id: str = Field(min_length=8, max_length=160)


def _number(value, default=0) -> int:
    try:
        return max(0, min(100, int(round(float(value)))))
    except (TypeError, ValueError):
        return default


def _review_for_entry(entry: LibraryEntry):
    try:
        return create_review_store().get(entry.review_id)
    except ReviewItemNotFound as exc:
        raise HTTPException(status_code=404, detail="Generation snapshot is unavailable") from exc


def _archived_future_contract(review) -> str:
    """Freeze the accepted future's design logic into branch creative intent.

    A fork keeps the accepted artwork as its design ancestor. The original raw source
    inventory remains provenance/history, but once new matter is attached it must not
    silently become active source material again.
    """

    concept = review.concept_snapshot if isinstance(review.concept_snapshot, dict) else {}
    one_line = str(concept.get("one_line") or concept.get("oneLine") or "").strip()
    thesis = str(concept.get("artistic_thesis") or concept.get("artisticThesis") or "").strip()
    logic = str(concept.get("transformation_logic") or concept.get("transformationLogic") or "").strip()
    original_direction = str(review.creative_direction or "").strip()

    source_names = {
        material_id: name
        for material_id, name in zip(review.source_material_ids, review.source_items)
    }
    role_rows: list[str] = []
    raw_uses = concept.get("material_uses") if isinstance(concept.get("material_uses"), list) else []
    for raw in raw_uses[:8]:
        if not isinstance(raw, dict):
            continue
        material_id = str(raw.get("material_item_id") or "").strip()
        role = str(raw.get("role") or "").strip()
        if role:
            role_rows.append(f"{source_names.get(material_id, material_id or 'source')}: {role}")

    parts = [
        "ARCHIVED FUTURE BASIS — EVOLVE, DO NOT RESET.",
        f"LOCKED PARENT FORM: {review.candidate_name}.",
        f"PARENT ONE-LINE: {one_line}" if one_line else "",
        f"PARENT ARTISTIC THESIS: {thesis}" if thesis else "",
        f"PARENT TRANSFORMATION LOGIC: {logic}" if logic else "",
        f"PARENT SOURCE ROLES: {'; '.join(role_rows)}" if role_rows else "",
        f"ORIGINAL MAKER DIRECTION: {original_direction}" if original_direction else "",
        (
            "Treat the accepted parent render as the LOCKED DESIGN ANCESTOR of this branch, not as a loose mood reference and not as raw matter. "
            "Preserve its signature gesture, core function or spatial logic, recognizable silhouette, and visible material ancestry unless the maker explicitly asks to replace one of those traits. "
            "Only materials identified in the CURRENT branch material inventory are newly introduced physical matter. Original pre-generation source objects are historical provenance only and MUST NOT re-enter the active material pool just because they existed in the parent's old evidence set. "
            "Newly attached matter should support, extend, clothe, cushion, connect, brace, surface, or locally transform the existing parent object. Do not restart from the raw source set and do not invent an unrelated fresh object merely because new matter was added."
        ),
    ]
    return "\n".join(part for part in parts if part)[:3000]


def _entry_view(entry: LibraryEntry, *, reveal_owner: bool = False) -> dict[str, object]:
    review = _review_for_entry(entry)
    concept = review.concept_snapshot if isinstance(review.concept_snapshot, dict) else {}
    review_snapshot = review.review_snapshot if isinstance(review.review_snapshot, dict) else {}
    metrics = concept.get("metrics") if isinstance(concept.get("metrics"), dict) else {}
    score = _number(
        review_snapshot.get("rank_score")
        or review_snapshot.get("score")
        or concept.get("rank_score")
        or metrics.get("overall"),
        0,
    )
    one_line = str(
        concept.get("one_line")
        or concept.get("oneLine")
        or concept.get("artistic_thesis")
        or concept.get("artisticThesis")
        or concept.get("transformation_logic")
        or concept.get("transformationLogic")
        or "A saved RUINFORM future."
    )[:600]
    category = str(concept.get("category") or "object")[:80]

    source_pairs = list(zip(review.source_material_ids, review.source_items))
    raw_uses = concept.get("material_uses") if isinstance(concept.get("material_uses"), list) else []
    used_ids: list[str] = []
    for raw in raw_uses:
        if not isinstance(raw, dict):
            continue
        material_id = str(raw.get("material_item_id") or "").strip()
        if material_id and material_id not in used_ids:
            used_ids.append(material_id)
    used_set = set(used_ids)
    used_source_items = [name for material_id, name in source_pairs if material_id in used_set]
    used_source_ids = [material_id for material_id, _name in source_pairs if material_id in used_set]

    payload: dict[str, object] = {
        "id": entry.generation_id,
        "title": review.candidate_name,
        "imageAvailable": bool(review.render_url),
        "score": score,
        "category": category,
        "oneLine": one_line,
        "sourceItems": review.source_items[:12],
        "sourceCount": len(review.source_items),
        "usedSourceItems": used_source_items[:12],
        "usedSourceIds": used_source_ids[:12],
        "usedSourceCount": len(used_source_items),
        "isPublic": entry.is_public,
        "parentGenerationId": entry.parent_generation_id,
        "createdAt": entry.created_at_iso,
        "sessionId": entry.session_id,
        "candidateId": entry.candidate_id,
    }
    if reveal_owner:
        payload["ownerId"] = entry.owner_id
    return payload


def _authorized_entry(generation_id: str, owner_id: str | None) -> LibraryEntry:
    try:
        entry = create_library_store().get(generation_id)
    except LibraryEntryNotFound as exc:
        raise HTTPException(status_code=404, detail="Generation not found") from exc
    if not entry.is_public and entry.owner_id != owner_id:
        raise HTTPException(status_code=403, detail="This generation is private")
    return entry


def _branch_parent_render_url(session) -> str:
    for evidence in session.project_state.evidence:
        if evidence.evidence_id == _BRANCH_PARENT_EVIDENCE_ID and evidence.uri:
            return evidence.uri
    result = session.render_result
    if result is not None and result.accepted_image_url:
        return result.accepted_image_url
    return ""


def _branch_physical_state(session):
    """Return only the physical matter that belongs to the active branch turn.

    On the first branch addition, the fork still carries the parent's original raw
    photographs/material inventory. They are provenance, not active ingredients, so drop
    them before Material Eye reads the new upload. On later additions, keep prior NEW
    branch matter but temporarily remove the locked parent render so it is never analyzed
    as a physical material.
    """

    state = session.project_state
    has_parent_marker = any(
        item.evidence_id == _BRANCH_PARENT_EVIDENCE_ID for item in state.evidence
    )
    if not has_parent_marker:
        return state.model_copy(
            deep=True,
            update={
                "evidence": [],
                "materials": [],
                "claim_history": [],
                "unresolved_critical_unknowns": [],
                "next_user_request": None,
            },
        )
    return state.model_copy(
        deep=True,
        update={
            "evidence": [
                item for item in state.evidence
                if item.evidence_id != _BRANCH_PARENT_EVIDENCE_ID
            ]
        },
    )


@router.post("/capture")
def capture_generation(payload: CaptureRequest) -> dict[str, object]:
    try:
        session = create_run_store().get(payload.session_id)
    except SessionNotFound as exc:
        raise HTTPException(status_code=404, detail="Transformation session not found") from exc

    review = capture_session_render(session)
    if review is None:
        raise HTTPException(status_code=409, detail="Only an accepted render can be saved to the library")

    parent_id = payload.parent_generation_id
    if parent_id:
        try:
            parent = create_library_store().get(parent_id)
        except LibraryEntryNotFound as exc:
            raise HTTPException(status_code=400, detail="Parent generation does not exist") from exc
        if not parent.is_public and parent.owner_id != payload.owner_id:
            raise HTTPException(status_code=403, detail="Parent generation is private")

    entry = LibraryEntry(
        generation_id=generation_id_for(owner_id=payload.owner_id, review_id=review.review_id),
        owner_id=payload.owner_id,
        review_id=review.review_id,
        session_id=session.session_id,
        candidate_id=review.candidate_id,
        is_public=False,
        parent_generation_id=parent_id,
    )
    saved = create_library_store().save(entry)
    return {"ok": True, "generation": _entry_view(saved)}


@router.get("/mine")
def list_mine(owner_id: str = Query(min_length=8, max_length=160), limit: int = Query(default=24, ge=1, le=60)) -> dict[str, object]:
    rows = create_library_store().list_mine(owner_id, limit=limit)
    return {"ok": True, "items": [_entry_view(row) for row in rows]}


@router.get("/explore")
def list_explore(limit: int = Query(default=24, ge=1, le=60)) -> dict[str, object]:
    rows = create_library_store().list_public(limit=limit)
    return {"ok": True, "items": [_entry_view(row) for row in rows]}


@router.post("/{generation_id}/visibility")
def set_visibility(generation_id: str, payload: VisibilityRequest) -> dict[str, object]:
    try:
        row = create_library_store().set_public(
            generation_id,
            owner_id=payload.owner_id,
            is_public=payload.is_public,
        )
    except LibraryEntryNotFound as exc:
        raise HTTPException(status_code=404, detail="Generation not found") from exc
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail="This generation belongs to another owner") from exc
    return {"ok": True, "generation": _entry_view(row)}


@router.post("/{generation_id}/fork")
def fork_generation(generation_id: str, payload: ForkRequest) -> dict[str, object]:
    entry = _authorized_entry(generation_id, payload.owner_id)
    try:
        review = create_review_store().get(entry.review_id)
        source = create_run_store().get(review.session_id)
    except (ReviewItemNotFound, SessionNotFound) as exc:
        raise HTTPException(status_code=409, detail="The source generation cannot be resumed") from exc

    if source.futures is None or not any(
        item.candidate.candidate_id == review.candidate_id
        for item in source.futures.selected_futures
    ):
        raise HTTPException(status_code=409, detail="The source future is no longer available in its session")

    branch_contract = _archived_future_contract(review)
    forked_state = source.project_state.model_copy(
        deep=True,
        update={
            "creative_intent": source.project_state.creative_intent.model_copy(
                update={"direction": branch_contract}
            )
        },
    )

    now = utc_now_iso()
    forked = source.model_copy(
        deep=True,
        update={
            "session_id": str(uuid4()),
            "stage": "completed",
            "project_state": forked_state,
            "selected_candidate_id": review.candidate_id,
            "render_result": RenderResult.model_validate(review.render_snapshot),
            "build_plan": None,
            "build_review": None,
            "build_revision_trace": None,
            "last_error": None,
            "last_error_stage": None,
            "created_at_iso": now,
            "updated_at_iso": now,
        },
    )
    saved = create_run_store().save(forked)
    return {
        "ok": True,
        "sessionId": saved.session_id,
        "sourceGenerationId": generation_id,
        "generation": _entry_view(entry),
    }


@router.post("/branch-evidence/{session_id}")
async def add_branch_evidence(
    session_id: str,
    images: list[UploadFile] = File(...),
    user_context: str = Form(default=""),
) -> dict[str, object]:
    """Attach NEW matter to a locked archived future without reactivating old raw inputs."""

    if not 1 <= len(images) <= 8:
        raise HTTPException(status_code=400, detail="Upload between 1 and 8 images")
    new_urls: list[str] = []
    try:
        source_session = get_session(session_id)
        locked_intent = source_session.project_state.creative_intent.model_copy(deep=True)
        parent_render_url = _branch_parent_render_url(source_session)
        if not parent_render_url:
            raise ValueError("Archived parent render is unavailable for branch evolution")

        physical_state = _branch_physical_state(source_session)
        analysis_session = source_session.model_copy(
            deep=True,
            update={"project_state": physical_state},
        )
        for index, image in enumerate(images, start=1):
            new_urls.append(await _upload_to_data_url(image, index=index))

        updated = await continue_session_evidence(
            session=analysis_session,
            new_image_urls=new_urls,
            user_statement=(
                user_context.strip()
                or "New physical matter added to evolve the locked archived RUINFORM future."
            ),
            measurements=[],
            store=store(),
        )

        parent_reference = EvidenceItem(
            evidence_id=_BRANCH_PARENT_EVIDENCE_ID,
            source_type="image",
            uri=parent_render_url,
            text=(
                "LOCKED PARENT FUTURE VISUAL REFERENCE. Design ancestry only; "
                "do not classify this render as newly supplied physical matter."
            ),
        )
        updated_state = updated.project_state.model_copy(
            update={
                "creative_intent": locked_intent,
                # Parent goes first so every vision stage sees the locked object even
                # when the maker adds several new photographs in one branch turn.
                "evidence": [parent_reference, *updated.project_state.evidence],
            }
        )
        updated = store().save(updated.model_copy(update={"project_state": updated_state}))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {
        "ok": True,
        "sessionId": updated.session_id,
        "projectId": updated.project_id,
        "stage": updated.stage,
        "projectState": updated.project_state.model_dump(mode="json"),
    }


@router.get("/{generation_id}/image")
async def read_generation_image(
    generation_id: str,
    owner_id: str | None = Query(default=None, max_length=160),
) -> Response:
    entry = _authorized_entry(generation_id, owner_id)
    review = _review_for_entry(entry)
    source = review.render_url
    if not source:
        raise HTTPException(status_code=404, detail="Generation image is unavailable")

    if source.startswith("data:image/"):
        try:
            header, encoded = source.split(",", 1)
            media_type = header.split(";", 1)[0][5:]
            raw = base64.b64decode(encoded, validate=True)
        except (ValueError, base64.binascii.Error) as exc:
            raise HTTPException(status_code=500, detail="Stored generation image is invalid") from exc
        return Response(
            content=raw,
            media_type=media_type,
            headers={"cache-control": "public, max-age=86400" if entry.is_public else "private, max-age=3600"},
        )

    if source.startswith("https://"):
        try:
            async with httpx.AsyncClient(timeout=20.0, follow_redirects=True) as client:
                upstream = await client.get(source)
                upstream.raise_for_status()
        except httpx.HTTPError as exc:
            raise HTTPException(status_code=502, detail="Could not load generation image") from exc
        return Response(
            content=upstream.content,
            media_type=upstream.headers.get("content-type", "image/jpeg"),
            headers={"cache-control": "public, max-age=86400" if entry.is_public else "private, max-age=3600"},
        )

    raise HTTPException(status_code=500, detail="Unsupported stored generation image")


@router.get("/{generation_id}")
def read_generation(generation_id: str, owner_id: str | None = Query(default=None, max_length=160)) -> dict[str, object]:
    entry = _authorized_entry(generation_id, owner_id)
    return {"ok": True, "generation": _entry_view(entry)}

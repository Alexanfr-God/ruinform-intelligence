from __future__ import annotations

from uuid import uuid4

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from .library_store import (
    LibraryEntry,
    LibraryEntryNotFound,
    create_library_store,
    generation_id_for,
)
from .render_models import RenderResult
from .review_store import ReviewItemNotFound, capture_session_render, create_review_store
from .run_store import SessionNotFound, create_run_store, utc_now_iso


router = APIRouter(prefix="/v1/library", tags=["generation-library"])


class CaptureRequest(BaseModel):
    owner_id: str = Field(min_length=8, max_length=160)
    session_id: str = Field(min_length=8, max_length=160)


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


def _entry_view(entry: LibraryEntry, *, reveal_owner: bool = False) -> dict[str, object]:
    try:
        review = create_review_store().get(entry.review_id)
    except ReviewItemNotFound as exc:
        raise HTTPException(status_code=404, detail="Generation snapshot is unavailable") from exc

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

    payload: dict[str, object] = {
        "id": entry.generation_id,
        "title": review.candidate_name,
        "imageUrl": review.render_url,
        "score": score,
        "category": category,
        "oneLine": one_line,
        "sourceItems": review.source_items[:12],
        "sourceCount": len(review.source_items),
        "isPublic": entry.is_public,
        "parentGenerationId": entry.parent_generation_id,
        "createdAt": entry.created_at_iso,
        "sessionId": entry.session_id,
        "candidateId": entry.candidate_id,
    }
    if reveal_owner:
        payload["ownerId"] = entry.owner_id
    return payload


@router.post("/capture")
def capture_generation(payload: CaptureRequest) -> dict[str, object]:
    try:
        session = create_run_store().get(payload.session_id)
    except SessionNotFound as exc:
        raise HTTPException(status_code=404, detail="Transformation session not found") from exc

    review = capture_session_render(session)
    if review is None:
        raise HTTPException(status_code=409, detail="Only an accepted render can be saved to the library")

    entry = LibraryEntry(
        generation_id=generation_id_for(owner_id=payload.owner_id, review_id=review.review_id),
        owner_id=payload.owner_id,
        review_id=review.review_id,
        session_id=session.session_id,
        candidate_id=review.candidate_id,
        is_public=False,
    )
    saved = create_library_store().save(entry)
    return {"ok": True, "generation": _entry_view(saved)}


@router.get("/mine")
def list_mine(owner_id: str = Query(min_length=8, max_length=160), limit: int = Query(default=48, ge=1, le=100)) -> dict[str, object]:
    rows = create_library_store().list_mine(owner_id, limit=limit)
    return {"ok": True, "items": [_entry_view(row) for row in rows]}


@router.get("/explore")
def list_explore(limit: int = Query(default=48, ge=1, le=100)) -> dict[str, object]:
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
    try:
        entry = create_library_store().get(generation_id)
    except LibraryEntryNotFound as exc:
        raise HTTPException(status_code=404, detail="Generation not found") from exc

    if not entry.is_public and entry.owner_id != payload.owner_id:
        raise HTTPException(status_code=403, detail="This generation is private")

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

    now = utc_now_iso()
    forked = source.model_copy(
        deep=True,
        update={
            "session_id": str(uuid4()),
            "stage": "completed",
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


@router.get("/{generation_id}")
def read_generation(generation_id: str, owner_id: str | None = Query(default=None, max_length=160)) -> dict[str, object]:
    try:
        entry = create_library_store().get(generation_id)
    except LibraryEntryNotFound as exc:
        raise HTTPException(status_code=404, detail="Generation not found") from exc
    if not entry.is_public and entry.owner_id != owner_id:
        raise HTTPException(status_code=403, detail="This generation is private")
    return {"ok": True, "generation": _entry_view(entry)}

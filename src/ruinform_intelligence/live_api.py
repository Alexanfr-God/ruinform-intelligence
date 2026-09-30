from __future__ import annotations

import asyncio
import base64
import logging
import os
from typing import Literal

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from pydantic import BaseModel, Field, HttpUrl

from .evidence_loop import MeasurementInput
from .future_models import FuturePreferences
from .live_evidence import continue_session_evidence
from .live_futures import discover_session_futures
from .live_render import render_session_candidate
from .live_transform import start_session
from .material_eye import MaterialEyeError, analyze_evidence
from .models import EvidenceItem, ProjectConstraints
from .provider_factory import create_higgsfield_provider
from .render_gateway import RenderGatewayError
from .render_provider import RenderProviderError
from .run_store import SessionNotFound, SqliteRunStore, TransformationSession

router = APIRouter(prefix="/v1/live-transformations", tags=["live-transformations"])
logger = logging.getLogger("ruinform.live_api")
_store: SqliteRunStore | None = None
_future_tasks: dict[str, asyncio.Task[None]] = {}
_ALLOWED_IMAGE_TYPES = {"image/jpeg", "image/png", "image/webp"}
_MAX_UPLOAD_FILES = 8
_MAX_UPLOAD_BYTES = 8 * 1024 * 1024


def store() -> SqliteRunStore:
    global _store
    if _store is None:
        _store = SqliteRunStore()
    return _store


def get_session(session_id: str) -> TransformationSession:
    try:
        return store().get(session_id)
    except SessionNotFound as exc:
        raise HTTPException(status_code=404, detail="Transformation session not found") from exc


async def _upload_to_data_url(upload: UploadFile, *, index: int) -> str:
    media_type = upload.content_type or ""
    if media_type not in _ALLOWED_IMAGE_TYPES:
        raise ValueError(f"Unsupported image type for image {index}: {media_type or 'unknown'}")
    raw = await upload.read(_MAX_UPLOAD_BYTES + 1)
    if not raw:
        raise ValueError(f"Image {index} is empty")
    if len(raw) > _MAX_UPLOAD_BYTES:
        raise ValueError(f"Image {index} exceeds 8 MB")
    return f"data:{media_type};base64,{base64.b64encode(raw).decode('ascii')}"


class StartRequest(BaseModel):
    image_urls: list[HttpUrl] = Field(min_length=1, max_length=8)
    user_context: str | None = Field(default=None, max_length=4000)
    constraints: ProjectConstraints = Field(default_factory=ProjectConstraints)


class ContinueEvidenceRequest(BaseModel):
    new_image_urls: list[HttpUrl] = Field(default_factory=list, max_length=4)
    user_statement: str | None = Field(default=None, max_length=4000)
    measurements: list[MeasurementInput] = Field(default_factory=list, max_length=20)


class DiscoverRequest(BaseModel):
    user_intent: str | None = Field(default=None, max_length=4000)
    preferences: FuturePreferences = Field(default_factory=FuturePreferences)
    max_revision_rounds: int = Field(default=2, ge=0, le=5)
    mode: Literal["hybrid", "art", "buildable", "functional"] = "hybrid"
    difficulty_mode: Literal["easy", "medium", "wild"] | None = None


class RenderRequestBody(BaseModel):
    aspect_ratio: str = Field(default="4:5", max_length=16)
    max_attempts: int = Field(default=2, ge=1, le=2)
    user_prompt: str | None = Field(default=None, max_length=1200)
    presentation_mode: Literal["standard", "post_apocalyptic"] = "post_apocalyptic"


async def _discover_futures_job(session_id: str, payload: DiscoverRequest) -> None:
    """Run the expensive vision/design pass outside the request-response timeout window."""
    try:
        logger.info(
            "futures async:start session=%s mode=%s difficulty=%s",
            session_id,
            payload.mode,
            payload.difficulty_mode or "project-default",
        )
        await discover_session_futures(
            session=get_session(session_id),
            preferences=payload.preferences,
            user_intent=payload.user_intent,
            max_revision_rounds=payload.max_revision_rounds,
            store=store(),
            mode=payload.mode,
            difficulty_mode=payload.difficulty_mode,
        )
        logger.info("futures async:done session=%s", session_id)
    except Exception:  # background failures must become observable session state
        logger.exception("futures async:failed session=%s", session_id)
        try:
            current = get_session(session_id)
            store().save(current.model_copy(update={"stage": "failed"}))
        except Exception:
            logger.exception("futures async:could not persist failure session=%s", session_id)
    finally:
        _future_tasks.pop(session_id, None)


@router.post("/start", response_model=TransformationSession)
async def start(payload: StartRequest) -> TransformationSession:
    if not os.getenv("OPENAI_API_KEY"):
        raise HTTPException(status_code=503, detail="OPENAI_API_KEY is not configured")
    return await start_session(
        image_urls=[str(url) for url in payload.image_urls],
        user_context=payload.user_context,
        constraints=payload.constraints,
        store=store(),
    )


@router.post("/start-upload", response_model=TransformationSession)
async def start_upload(
    images: list[UploadFile] = File(...),
    user_context: str = Form(default=""),
) -> TransformationSession:
    """Start the visual-first Workshop flow from direct image uploads.

    This route exists for server-to-server website bridges. It avoids requiring the
    intelligence service or OpenAI to fetch private Higgsfield-hosted media URLs.
    Evidence is stored as data URLs in the durable transformation session; the existing
    evidence-media layer externalizes those images as signed public URLs only when a
    renderer needs them.
    """
    if not os.getenv("OPENAI_API_KEY"):
        raise HTTPException(status_code=503, detail="OPENAI_API_KEY is not configured")
    if not 1 <= len(images) <= _MAX_UPLOAD_FILES:
        raise HTTPException(status_code=400, detail="Upload between 1 and 8 images")

    evidence: list[EvidenceItem] = []
    try:
        for index, image in enumerate(images, start=1):
            evidence.append(
                EvidenceItem(
                    evidence_id=f"image_{index:03d}",
                    source_type="image",
                    uri=await _upload_to_data_url(image, index=index),
                )
            )
        state, _summary = await analyze_evidence(
            evidence=evidence,
            user_context=user_context.strip() or None,
            constraints=ProjectConstraints(),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except MaterialEyeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    return store().save(
        TransformationSession(
            project_id=state.project_id,
            stage="ready_for_futures",
            project_state=state,
            reasoning_mode="concept",
            concept_mode_acknowledged=True,
            concept_notice_version="website-workshop-2026-09",
        )
    )


@router.get("/{session_id}", response_model=TransformationSession)
async def read_session(session_id: str) -> TransformationSession:
    return get_session(session_id)


@router.post("/{session_id}/evidence", response_model=TransformationSession)
async def add_evidence(session_id: str, payload: ContinueEvidenceRequest) -> TransformationSession:
    return await continue_session_evidence(
        session=get_session(session_id),
        new_image_urls=[str(url) for url in payload.new_image_urls],
        user_statement=payload.user_statement,
        measurements=payload.measurements,
        store=store(),
    )


@router.post("/{session_id}/futures/start")
async def discover_start(session_id: str, payload: DiscoverRequest) -> dict[str, object]:
    """Start future discovery and return immediately.

    Cloud/CDN request timeouts are shorter than a high-reasoning vision pass. The browser
    bridge should call this endpoint once, then poll GET /{session_id}. Duplicate starts are
    idempotent while a task is active and after futures are already available.
    """
    session = get_session(session_id)
    if session.futures is not None and session.stage in {"futures_ready", "rendering", "completed", "build_plan_ready"}:
        return {"ok": True, "pending": False, "session_id": session_id, "stage": session.stage}

    active = _future_tasks.get(session_id)
    if active is not None and not active.done():
        return {"ok": True, "pending": True, "session_id": session_id, "stage": "futures_generating"}

    if session.stage == "failed":
        session = store().save(session.model_copy(update={"stage": "ready_for_futures"}))

    task = asyncio.create_task(_discover_futures_job(session_id, payload))
    _future_tasks[session_id] = task
    return {"ok": True, "pending": True, "session_id": session_id, "stage": "futures_generating"}


@router.post("/{session_id}/futures", response_model=TransformationSession)
async def discover(session_id: str, payload: DiscoverRequest) -> TransformationSession:
    """Compatibility synchronous route for non-Workshop callers."""
    try:
        return await discover_session_futures(
            session=get_session(session_id),
            preferences=payload.preferences,
            user_intent=payload.user_intent,
            max_revision_rounds=payload.max_revision_rounds,
            store=store(),
            mode=payload.mode,
            difficulty_mode=payload.difficulty_mode,
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/{session_id}/render/{candidate_id}", response_model=TransformationSession)
async def render(session_id: str, candidate_id: str, payload: RenderRequestBody) -> TransformationSession:
    cleanup_client = None
    try:
        active_provider = create_higgsfield_provider()
        if isinstance(active_provider, tuple):
            provider, cleanup_client = active_provider
        else:
            provider = active_provider
        try:
            return await render_session_candidate(
                session=get_session(session_id),
                candidate_id=candidate_id,
                provider=provider,
                store=store(),
                aspect_ratio=payload.aspect_ratio,
                max_attempts=payload.max_attempts,
                user_prompt=payload.user_prompt,
                presentation_mode=payload.presentation_mode,
            )
        finally:
            if cleanup_client is not None:
                await cleanup_client.aclose()
    except (RenderProviderError, RenderGatewayError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

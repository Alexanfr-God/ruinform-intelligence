from __future__ import annotations

import os

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field, HttpUrl

from .evidence_loop import MeasurementInput
from .future_models import FuturePreferences
from .live_evidence import continue_session_evidence
from .live_futures import discover_session_futures
from .live_render import render_session_candidate
from .live_transform import start_session
from .models import ProjectConstraints
from .provider_factory import create_higgsfield_provider
from .render_gateway import RenderGatewayError
from .render_provider import RenderProviderError
from .run_store import SessionNotFound, SqliteRunStore, TransformationSession

router = APIRouter(prefix="/v1/live-transformations", tags=["live-transformations"])
_store: SqliteRunStore | None = None


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


class RenderRequestBody(BaseModel):
    aspect_ratio: str = Field(default="4:5", max_length=16)
    max_attempts: int = Field(default=3, ge=1, le=5)


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


@router.post("/{session_id}/futures", response_model=TransformationSession)
async def discover(session_id: str, payload: DiscoverRequest) -> TransformationSession:
    try:
        return await discover_session_futures(
            session=get_session(session_id),
            preferences=payload.preferences,
            user_intent=payload.user_intent,
            max_revision_rounds=payload.max_revision_rounds,
            store=store(),
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/{session_id}/render/{candidate_id}", response_model=TransformationSession)
async def render(session_id: str, candidate_id: str, payload: RenderRequestBody) -> TransformationSession:
    try:
        provider, client = create_higgsfield_provider()
        try:
            return await render_session_candidate(
                session=get_session(session_id),
                candidate_id=candidate_id,
                provider=provider,
                store=store(),
                aspect_ratio=payload.aspect_ratio,
                max_attempts=payload.max_attempts,
            )
        finally:
            await client.aclose()
    except (RenderProviderError, RenderGatewayError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

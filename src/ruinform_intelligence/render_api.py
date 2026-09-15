from __future__ import annotations

import os

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field, HttpUrl

from .future_models import ReviewedFuture
from .models import ProjectState
from .render_models import ProviderRender, RenderCritique, RenderRequest
from .render_prompt import compile_render_request
from .render_review import enforce_render_gate
from .render_review_agent import RenderReviewAgentError, evaluate_render


router = APIRouter(prefix="/v1/renders", tags=["renders"])


class PrepareRenderRequest(BaseModel):
    project_state: ProjectState
    future: ReviewedFuture
    aspect_ratio: str = Field(default="4:5", max_length=16)


class ReviewRenderRequest(BaseModel):
    future: ReviewedFuture
    render_request: RenderRequest
    image_url: HttpUrl
    provider: str = "external"
    provider_job_id: str | None = None


@router.post("/prepare", response_model=RenderRequest)
async def prepare_render(payload: PrepareRenderRequest) -> RenderRequest:
    try:
        return compile_render_request(
            state=payload.project_state,
            future=payload.future,
            aspect_ratio=payload.aspect_ratio,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/review", response_model=RenderCritique)
async def review_render(payload: ReviewRenderRequest) -> RenderCritique:
    if not os.getenv("OPENAI_API_KEY"):
        raise HTTPException(status_code=503, detail="OPENAI_API_KEY is not configured on the server")
    render = ProviderRender(
        provider=payload.provider,
        image_url=payload.image_url,
        provider_job_id=payload.provider_job_id,
    )
    try:
        raw = await evaluate_render(
            future=payload.future,
            request=payload.render_request,
            render=render,
        )
    except RenderReviewAgentError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return enforce_render_gate(raw)

from __future__ import annotations

import os

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from .future_models import FutureFormsResult, FuturePreferences
from .future_pipeline import FuturePipelineError, discover_future_forms
from .models import ProjectState


router = APIRouter(prefix="/v1/futures", tags=["future-forms"])


class FutureFormsRequest(BaseModel):
    project_state: ProjectState
    user_intent: str | None = Field(default=None, max_length=4000)
    preferences: FuturePreferences = Field(default_factory=FuturePreferences)


@router.post("/generate", response_model=FutureFormsResult)
async def generate_future_forms(payload: FutureFormsRequest) -> FutureFormsResult:
    if not os.getenv("OPENAI_API_KEY"):
        raise HTTPException(
            status_code=503,
            detail="OPENAI_API_KEY is not configured on the server",
        )

    try:
        return await discover_future_forms(
            state=payload.project_state,
            preferences=payload.preferences,
            user_intent=payload.user_intent,
        )
    except FuturePipelineError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

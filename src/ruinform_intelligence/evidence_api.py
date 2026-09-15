from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field, HttpUrl

from .evidence_gate import can_advance_to_ideation
from .evidence_loop import EvidenceLoopResult, MeasurementInput, continue_evidence_loop
from .material_eye import MaterialEyeError
from .models import ProjectState


router = APIRouter(prefix="/v1/evidence-loop", tags=["evidence-loop"])


class EvidenceLoopRequest(BaseModel):
    current_state: ProjectState
    new_image_urls: list[HttpUrl] = Field(default_factory=list, max_length=4)
    user_statement: str | None = Field(default=None, max_length=4000)
    measurements: list[MeasurementInput] = Field(default_factory=list, max_length=20)


class EvidenceLoopResponse(EvidenceLoopResult):
    can_advance_to_ideation: bool


@router.post("/continue", response_model=EvidenceLoopResponse)
async def evidence_loop_continue(payload: EvidenceLoopRequest) -> EvidenceLoopResponse:
    try:
        result = await continue_evidence_loop(
            current_state=payload.current_state,
            new_image_urls=[str(url) for url in payload.new_image_urls],
            user_statement=payload.user_statement,
            measurements=payload.measurements,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except MaterialEyeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    return EvidenceLoopResponse(
        **result.model_dump(),
        can_advance_to_ideation=can_advance_to_ideation(result.project_state),
    )

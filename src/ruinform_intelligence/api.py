from __future__ import annotations

import os

from fastapi import Depends, FastAPI, HTTPException
from pydantic import BaseModel, Field, HttpUrl

from .access_control import require_api_access
from .evidence_contract import EvidenceContractReport, validate_state_contract
from .evidence_gate import can_advance_to_ideation
from .material_eye import MaterialEyeError, analyze_materials
from .models import ProjectConstraints, ProjectState


app = FastAPI(
    title="RUINFORM Intelligence",
    version="0.3.0",
    description="Evidence-first intelligence for physical matter.",
    dependencies=[Depends(require_api_access)],
)


class MaterialEyeRequest(BaseModel):
    image_urls: list[HttpUrl] = Field(min_length=1, max_length=8)
    user_context: str | None = Field(default=None, max_length=4000)
    constraints: ProjectConstraints = Field(default_factory=ProjectConstraints)
    project_id: str | None = None


class MaterialEyeResponse(BaseModel):
    analysis_summary: str
    project_state: ProjectState
    can_advance_to_ideation: bool
    evidence_contract: EvidenceContractReport


@app.get("/health")
async def health() -> dict[str, str]:
    storage = "postgres" if (os.getenv("DATABASE_URL") or os.getenv("RUINFORM_DATABASE_URL")) else "sqlite"
    return {
        "status": "ok",
        "service": "ruinform-intelligence",
        "build": "RFM-INT-0003",
        "storage": storage,
    }


@app.post("/v1/material-eye/analyze", response_model=MaterialEyeResponse)
async def material_eye_analyze(payload: MaterialEyeRequest) -> MaterialEyeResponse:
    if not os.getenv("OPENAI_API_KEY"):
        raise HTTPException(
            status_code=503,
            detail="OPENAI_API_KEY is not configured on the server",
        )

    try:
        state, summary = await analyze_materials(
            image_urls=[str(url) for url in payload.image_urls],
            user_context=payload.user_context,
            constraints=payload.constraints,
            project_id=payload.project_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except MaterialEyeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    return MaterialEyeResponse(
        analysis_summary=summary,
        project_state=state,
        can_advance_to_ideation=can_advance_to_ideation(state),
        evidence_contract=validate_state_contract(state),
    )

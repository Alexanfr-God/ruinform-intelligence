from __future__ import annotations

import os

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import RedirectResponse
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


@app.middleware("http")
async def bridge_legacy_lab_navigation(request: Request, call_next):
    """Keep authenticated Studio users out of the legacy Basic-Auth Lab trap.

    Studio uses a signed cookie while the old /lab pages still use HTTP Basic. A
    historical BACK TO EVIDENCE LAB link therefore caused browsers to challenge for
    credentials again. When a Studio cookie is present and a user navigates to the
    legacy session page, send them back to the equivalent Studio session instead.
    """
    path = request.url.path
    if (
        request.method == "GET"
        and path.startswith("/lab/")
        and request.cookies.get("ruinform_studio_session")
    ):
        suffix = path[len("/lab/"):]
        if suffix and "/" not in suffix:
            return RedirectResponse(url=f"/studio/{suffix}", status_code=303)
    return await call_next(request)


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

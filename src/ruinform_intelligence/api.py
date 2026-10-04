from __future__ import annotations

import html
import os

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from openai import RateLimitError
from pydantic import BaseModel, Field, HttpUrl

from .access_control import require_api_access
from .evidence_contract import EvidenceContractReport, validate_state_contract
from .evidence_gate import can_advance_to_ideation
from .generation_registry import router as generation_registry_router
from .material_eye import MaterialEyeError, analyze_materials
from .models import ProjectConstraints, ProjectState
from .nft_devnet import router as nft_devnet_router
from .nft_reconciliation import router as nft_reconciliation_router
from .nft_reconcile_system import router as nft_reconcile_system_router
from . import nft_schema_patch as _nft_schema_patch  # noqa: F401
from . import passport_provenance_patch as _passport_provenance_patch  # noqa: F401
from .nft_public import router as nft_public_router
from .object_economics_v3 import router as object_economics_router
from .object_transfers import router as object_transfers_router
from .release_channels import router as release_channels_router
from .artifact_standard_v1 import router as artifact_standard_router
from .artifact_sales import router as artifact_sales_router
from .verification_api import router as verification_router
from .verification_checkpoint import router as verification_checkpoint_router
from .verification_disputes import router as verification_disputes_router
from .wallet_identity import router as wallet_identity_router


app = FastAPI(
    title="RUINFORM Intelligence",
    version="0.3.0",
    description="Evidence-first intelligence for physical matter.",
    dependencies=[Depends(require_api_access)],
)


def _studio_back_path(path: str) -> str:
    parts = [part for part in path.split("/") if part]
    if len(parts) >= 2 and parts[0] == "studio":
        return f"/studio/{parts[1]}"
    return "/studio/new"


def _openai_rate_limit_response(request: Request, exc: RateLimitError):
    body = getattr(exc, "body", None)
    error_code = body.get("code") if isinstance(body, dict) else None
    detail = str(exc)
    credits_exhausted = (
        error_code == "credit_balance_exhausted"
        or "no credits remaining" in detail.lower()
        or "insufficient_quota" in detail.lower()
    )

    if credits_exhausted:
        title = "OPENAI API CREDITS EXHAUSTED."
        message = (
            "RUINFORM reached OpenAI successfully, but the API account has no credits remaining. "
            "Add API credits in OpenAI Platform Billing, then retry this step. Your Studio project, "
            "controls, uploaded source photos, and session are preserved."
        )
        status_code = 402
    else:
        title = "OPENAI API RATE LIMIT."
        message = (
            "OpenAI is temporarily rate-limiting this request. Wait briefly and retry. "
            "Your RUINFORM project session is preserved."
        )
        status_code = 429

    if request.url.path.startswith("/studio/"):
        back = _studio_back_path(request.url.path)
        page = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"/><meta name="viewport" content="width=device-width,initial-scale=1"/>
<title>RUINFORM / API BLOCKED</title>
<style>
:root{{color-scheme:dark}}*{{box-sizing:border-box}}body{{margin:0;background:#080807;color:#eee8dd;font-family:ui-monospace,SFMono-Regular,Menlo,monospace}}main{{max-width:900px;margin:0 auto;padding:72px 22px}}h1{{font-size:clamp(42px,8vw,96px);line-height:.88;letter-spacing:-.06em;margin:0 0 28px}}p{{line-height:1.6;color:#b8b0a4;max-width:780px}}.k{{font-size:12px;letter-spacing:.2em;color:#8f887b;margin-bottom:16px}}.panel{{border:1px solid #3a352e;background:#10100e;padding:20px;margin:28px 0}}a{{color:#eee8dd}}.warn{{color:#d5ad74}}
</style></head><body><main>
<div class="k">RUINFORM / OPENAI API</div>
<h1>{html.escape(title)}</h1>
<div class="panel"><p class="warn">{html.escape(message)}</p></div>
<p><a href="{html.escape(back, quote=True)}">BACK TO PROJECT</a></p>
</main></body></html>"""
        return HTMLResponse(page, status_code=status_code)

    return JSONResponse(
        status_code=status_code,
        content={
            "detail": message,
            "code": "openai_api_credits_exhausted" if credits_exhausted else "openai_api_rate_limited",
        },
    )


@app.middleware("http")
async def bridge_legacy_lab_navigation(request: Request, call_next):
    """Keep authenticated Studio users out of the legacy Basic-Auth Lab trap."""
    path = request.url.path
    if (
        request.method == "GET"
        and path.startswith("/lab/")
        and request.cookies.get("ruinform_studio_session")
    ):
        suffix = path[len("/lab/"):]
        if suffix and "/" not in suffix:
            return RedirectResponse(url=f"/studio/{suffix}", status_code=303)
    try:
        return await call_next(request)
    except RateLimitError as exc:
        return _openai_rate_limit_response(request, exc)


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
        "build": "RFM-INT-0040",
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
        state = ProjectState()
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


app.include_router(verification_router)
app.include_router(verification_checkpoint_router)
app.include_router(verification_disputes_router)
app.include_router(wallet_identity_router)
app.include_router(generation_registry_router)
app.include_router(object_economics_router)
app.include_router(nft_devnet_router)
app.include_router(nft_reconciliation_router)
app.include_router(nft_reconcile_system_router)
app.include_router(nft_public_router)
app.include_router(release_channels_router)
app.include_router(object_transfers_router)
app.include_router(artifact_standard_router)
app.include_router(artifact_sales_router)

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, HttpUrl


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class RenderReference(StrictModel):
    evidence_id: str
    image_url: HttpUrl
    material_item_id: str | None
    note: str | None


class RenderRequest(StrictModel):
    candidate_id: str
    prompt: str
    negative_constraints: list[str]
    references: list[RenderReference]
    aspect_ratio: str = "4:5"


class ProviderRender(StrictModel):
    provider: str
    # External providers may return HTTPS URLs; GPT Image returns base64 image data.
    # Keep the renderer contract vendor-neutral by allowing either representation.
    image_url: str
    provider_job_id: str | None
    provider_metadata: dict[str, str | int | float | bool | None] = Field(default_factory=dict)


class RenderViolation(StrictModel):
    code: str
    severity: Literal["warning", "critical"]
    message: str


class RenderCritique(StrictModel):
    status: Literal["pass", "regenerate", "reject"]
    brief_fidelity_score: int = Field(ge=0, le=100)
    source_material_fidelity_score: int = Field(ge=0, le=100)
    provenance_visibility_score: int = Field(ge=0, le=100)
    geometry_consistency_score: int = Field(ge=0, le=100)
    invention_risk_score: int = Field(ge=0, le=100)
    violations: list[RenderViolation]
    failed_contract_requirement_ids: list[str] = Field(default_factory=list)
    regeneration_instructions: list[str]
    summary: str


class RenderAttempt(BaseModel):
    attempt_index: int = Field(ge=1, le=5)
    request: RenderRequest
    render: ProviderRender
    critique: RenderCritique


class RenderResult(BaseModel):
    candidate_id: str
    status: Literal["pass", "failed"]
    # Can be an HTTPS URL or a data:image/... URL from GPT Image.
    accepted_image_url: str | None = None
    attempts: list[RenderAttempt] = Field(default_factory=list)
    failure_reason: str | None = None

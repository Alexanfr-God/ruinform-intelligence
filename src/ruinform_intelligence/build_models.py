from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class BuildStep(StrictModel):
    step_number: int = Field(ge=1, le=20)
    title: str
    action: str
    source_material_ids: list[str] = Field(default_factory=list)
    added_materials: list[str] = Field(default_factory=list)
    tools: list[str] = Field(default_factory=list)
    verify: str
    stop_if: list[str] = Field(default_factory=list)


class BuildPlan(StrictModel):
    candidate_id: str
    title: str
    plan_mode: Literal["verified", "concept_prototype"]
    result_description: str
    difficulty: Literal["easy", "moderate", "advanced"]
    estimated_time_minutes: int | None = Field(default=None, ge=1, le=10080)
    added_materials: list[str] = Field(default_factory=list)
    tools: list[str] = Field(default_factory=list)
    preparation_checks: list[str] = Field(default_factory=list)
    steps: list[BuildStep] = Field(min_length=2, max_length=12)
    unresolved_before_use: list[str] = Field(default_factory=list)
    safety_gates: list[str] = Field(default_factory=list)
    final_verification: list[str] = Field(default_factory=list)
    maker_note: str

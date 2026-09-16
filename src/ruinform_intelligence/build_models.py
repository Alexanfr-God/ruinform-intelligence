from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class BuildStep(StrictModel):
    step_number: int = Field(ge=1, le=20)
    title: str
    action: str
    source_material_ids: list[str]
    added_materials: list[str]
    tools: list[str]
    verify: str
    stop_if: list[str]


class BuildPlan(StrictModel):
    candidate_id: str
    title: str
    plan_mode: Literal["verified", "concept_prototype"]
    result_description: str
    difficulty: Literal["easy", "moderate", "advanced"]
    estimated_time_minutes: int | None = Field(ge=1, le=10080)
    added_materials: list[str]
    tools: list[str]
    preparation_checks: list[str]
    steps: list[BuildStep] = Field(min_length=2, max_length=12)
    unresolved_before_use: list[str]
    safety_gates: list[str]
    final_verification: list[str]
    maker_note: str

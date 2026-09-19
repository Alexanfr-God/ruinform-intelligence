from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class MeasurementRequirement(StrictModel):
    measurement_id: str
    what_to_measure: str
    how_to_measure: str
    used_for: str
    blocks_step_numbers: list[int]


class SubstituteOption(StrictModel):
    original_item: str
    substitute: str
    when_allowed: str


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
    """Actionable Build Master output.

    The v1 fields are required in the Structured Output schema. A before-validator fills
    them only when loading legacy v0.2 plans that are already stored in production, so a
    deploy never makes old sessions unreadable.
    """

    plan_version: str
    candidate_id: str
    title: str
    plan_mode: Literal["verified", "concept_prototype"]
    result_description: str
    difficulty: Literal["easy", "moderate", "advanced"]
    estimated_time_minutes: int | None = Field(ge=1, le=10080)
    known_facts: list[str]
    measurements_required: list[MeasurementRequirement]
    engineering_assumptions: list[str]
    added_materials: list[str]
    tools: list[str]
    substitute_options: list[SubstituteOption]
    preparation_checks: list[str]
    steps: list[BuildStep] = Field(min_length=2, max_length=12)
    unresolved_before_use: list[str]
    safety_gates: list[str]
    final_verification: list[str]
    maker_note: str

    @model_validator(mode="before")
    @classmethod
    def _upgrade_legacy_plan(cls, value: Any) -> Any:
        if not isinstance(value, dict):
            return value
        upgraded = dict(value)
        upgraded.setdefault("plan_version", "legacy_v0_2")
        upgraded.setdefault("known_facts", [])
        upgraded.setdefault("measurements_required", [])
        upgraded.setdefault("engineering_assumptions", [])
        upgraded.setdefault("substitute_options", [])
        return upgraded


BuildCriticStatus = Literal["pass", "revise", "block"]


class BuildCriticReview(StrictModel):
    candidate_id: str
    status: BuildCriticStatus
    evidence_grounding_score: int = Field(ge=0, le=100)
    physical_credibility_score: int = Field(ge=0, le=100)
    sequence_quality_score: int = Field(ge=0, le=100)
    visual_fidelity_score: int = Field(ge=0, le=100)
    completeness_score: int = Field(ge=0, le=100)
    safety_completeness_score: int = Field(ge=0, le=100)
    reasons: list[str]
    required_changes: list[str]
    blocking_unknowns: list[str]


class BuildRevisionTrace(StrictModel):
    version: str
    attempted: bool
    before_status: BuildCriticStatus
    after_status: BuildCriticStatus | None
    changes_requested: list[str]
    policy: str

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class FuturePreferences(BaseModel):
    originality: float = Field(default=1.0, ge=0.0, le=3.0)
    artistic_impact: float = Field(default=1.0, ge=0.0, le=3.0)
    usefulness: float = Field(default=1.0, ge=0.0, le=3.0)
    ease: float = Field(default=1.0, ge=0.0, le=3.0)
    value: float = Field(default=1.0, ge=0.0, le=3.0)
    only_use_owned_materials: bool = False
    avoid_categories: list[str] = Field(default_factory=list)


class MaterialUse(StrictModel):
    material_item_id: str
    role: str
    estimated_fraction: float | None = Field(ge=0.0, le=1.0)
    note: str | None


class CandidateForm(StrictModel):
    candidate_id: str
    name: str
    one_line: str
    category: Literal[
        "functional_art",
        "sculpture",
        "wearable",
        "interior",
        "utility",
        "lighting",
        "furniture",
        "other",
    ]
    artistic_thesis: str
    transformation_logic: str
    material_uses: list[MaterialUse]
    added_materials: list[str]
    required_tools: list[str]
    key_operations: list[str]
    unresolved_dependencies: list[str]


class CandidatePool(StrictModel):
    candidates: list[CandidateForm]


class FeasibilityReview(StrictModel):
    candidate_id: str
    status: Literal["pass", "revise", "reject"]
    feasibility_score: int = Field(ge=0, le=100)
    material_fit_score: int = Field(ge=0, le=100)
    buildability_score: int = Field(ge=0, le=100)
    originality_score: int = Field(ge=0, le=100)
    artistic_impact_score: int = Field(ge=0, le=100)
    usefulness_score: int = Field(ge=0, le=100)
    value_potential_score: int = Field(ge=0, le=100)
    reasons: list[str]
    required_changes: list[str]
    unresolved_dependencies: list[str]


class ReviewBatch(StrictModel):
    reviews: list[FeasibilityReview]


class RevisionRecord(BaseModel):
    round_index: int = Field(ge=1, le=5)
    critique_status: Literal["revise"]
    requested_changes: list[str]
    candidate_before: CandidateForm
    candidate_after: CandidateForm


class VisualMaterialTrace(StrictModel):
    material_item_id: str
    intended_location: str
    source_character_to_preserve: str
    appearance_constraints: list[str]


class VisualBrief(StrictModel):
    candidate_id: str
    title: str
    object_summary: str
    silhouette: str
    geometry_notes: list[str]
    material_traces: list[VisualMaterialTrace]
    visible_connections: list[str]
    composition: str
    camera: str
    lighting: str
    environment: str
    provenance_cues: list[str]
    unknowns_to_keep_ambiguous: list[str]
    forbidden_inventions: list[str]


class ReviewedFuture(BaseModel):
    candidate: CandidateForm
    review: FeasibilityReview
    rank_score: float = Field(ge=0.0, le=100.0)
    revision_history: list[RevisionRecord] = Field(default_factory=list)
    visual_brief: VisualBrief | None = None


class FutureFormsResult(BaseModel):
    internal_candidate_count: int
    reviewed_candidate_count: int
    revision_attempt_count: int = 0
    selected_futures: list[ReviewedFuture]
    needs_regeneration: bool = False
    regeneration_reason: str | None = None

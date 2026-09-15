from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class FuturePreferences(BaseModel):
    originality: float = Field(default=1.0, ge=0.0, le=3.0)
    artistic_impact: float = Field(default=1.0, ge=0.0, le=3.0)
    usefulness: float = Field(default=1.0, ge=0.0, le=3.0)
    ease: float = Field(default=1.0, ge=0.0, le=3.0)
    value: float = Field(default=1.0, ge=0.0, le=3.0)
    only_use_owned_materials: bool = False
    avoid_categories: list[str] = Field(default_factory=list)


class MaterialUse(BaseModel):
    material_item_id: str
    role: str
    estimated_fraction: float | None = Field(default=None, ge=0.0, le=1.0)
    note: str | None = None


class CandidateForm(BaseModel):
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
    added_materials: list[str] = Field(default_factory=list)
    required_tools: list[str] = Field(default_factory=list)
    key_operations: list[str] = Field(default_factory=list)
    unresolved_dependencies: list[str] = Field(default_factory=list)


class CandidatePool(BaseModel):
    candidates: list[CandidateForm]


class FeasibilityReview(BaseModel):
    candidate_id: str
    status: Literal["pass", "revise", "reject"]
    feasibility_score: int = Field(ge=0, le=100)
    material_fit_score: int = Field(ge=0, le=100)
    buildability_score: int = Field(ge=0, le=100)
    originality_score: int = Field(ge=0, le=100)
    artistic_impact_score: int = Field(ge=0, le=100)
    usefulness_score: int = Field(ge=0, le=100)
    value_potential_score: int = Field(ge=0, le=100)
    reasons: list[str] = Field(default_factory=list)
    required_changes: list[str] = Field(default_factory=list)
    unresolved_dependencies: list[str] = Field(default_factory=list)


class ReviewBatch(BaseModel):
    reviews: list[FeasibilityReview]


class ReviewedFuture(BaseModel):
    candidate: CandidateForm
    review: FeasibilityReview
    rank_score: float = Field(ge=0.0, le=100.0)


class FutureFormsResult(BaseModel):
    internal_candidate_count: int
    reviewed_candidate_count: int
    selected_futures: list[ReviewedFuture]
    needs_regeneration: bool = False
    regeneration_reason: str | None = None

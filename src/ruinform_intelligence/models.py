from __future__ import annotations

from enum import Enum
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, Field


EvidenceSourceType = Literal["image", "user_statement", "measurement", "tool_result"]
ClaimChangeType = Literal["new", "confirmed", "revised", "contradicted"]
DifficultyMode = Literal["easy", "medium", "wild"]
BackgroundMode = Literal["clean_studio", "ruinform_world"]


class ClaimKind(str, Enum):
    FACT = "fact"
    HYPOTHESIS = "hypothesis"
    UNKNOWN = "unknown"


class EvidenceRef(BaseModel):
    evidence_id: str
    source_type: EvidenceSourceType
    note: str | None = None


class MaterialObservation(BaseModel):
    observation_id: str = Field(default_factory=lambda: str(uuid4()))
    property_key: str | None = None
    label: str
    claim_kind: ClaimKind
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    evidence: list[EvidenceRef] = Field(default_factory=list)
    consequence_if_wrong: Literal["low", "medium", "high"] = "low"
    change_type: ClaimChangeType = "new"
    prior_observation_ids: list[str] = Field(default_factory=list)


class Unknown(BaseModel):
    unknown_id: str = Field(default_factory=lambda: str(uuid4()))
    property_key: str | None = None
    question: str
    reason: str
    consequence_if_unresolved: Literal["low", "medium", "high"]
    preferred_evidence: list[str] = Field(default_factory=list)


class MaterialItem(BaseModel):
    item_id: str = Field(default_factory=lambda: str(uuid4()))
    display_name: str
    observations: list[MaterialObservation] = Field(default_factory=list)
    unknowns: list[Unknown] = Field(default_factory=list)


class EvidenceItem(BaseModel):
    evidence_id: str = Field(default_factory=lambda: str(uuid4()))
    source_type: EvidenceSourceType
    uri: str | None = None
    text: str | None = None
    property_key: str | None = None
    value: str | float | int | bool | None = None
    unit: str | None = None
    created_at_iso: str | None = None


class ProjectConstraints(BaseModel):
    tools_available: list[str] = Field(default_factory=list)
    skills: list[str] = Field(default_factory=list)
    budget_max: float | None = None
    time_budget_minutes: int | None = None
    location_notes: str | None = None


class CreativeIntent(BaseModel):
    """User-controlled creative guidance that survives the whole RUINFORM pipeline.

    ``direction`` is optional human language. It guides the system but never replaces
    the evidence, material reality, safety constraints, or RUINFORM design rules.
    Longer briefs are allowed so a user can describe composition, gesture and exclusions
    without turning the field into an unrestricted text-to-image prompt.
    ``difficulty_mode`` controls transformation complexity. ``background_mode`` is a
    presentation choice and should not change the core object concept.
    """

    direction: str | None = Field(default=None, max_length=3000)
    difficulty_mode: DifficultyMode = "medium"
    background_mode: BackgroundMode = "clean_studio"


class ProjectState(BaseModel):
    project_id: str = Field(default_factory=lambda: str(uuid4()))
    stage: Literal[
        "evidence_collection",
        "material_understanding",
        "ideation",
        "engineering",
        "build",
        "verification",
        "ownership",
    ] = "evidence_collection"
    evidence: list[EvidenceItem] = Field(default_factory=list)
    materials: list[MaterialItem] = Field(default_factory=list)
    claim_history: list[MaterialObservation] = Field(default_factory=list)
    constraints: ProjectConstraints = Field(default_factory=ProjectConstraints)
    creative_intent: CreativeIntent = Field(default_factory=CreativeIntent)
    unresolved_critical_unknowns: list[str] = Field(default_factory=list)
    next_user_request: str | None = None

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


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
    concept_mode: bool = False


MATERIAL_ROLES = ("hero", "structure", "connector", "surface", "symbolic")


class MaterialUse(StrictModel):
    material_item_id: str
    role: str = Field(
        description=(
            "Primary authored role of this source in the future. Use exactly one of: "
            "hero, structure, connector, surface, symbolic. HERO carries the signature gesture; "
            "STRUCTURE carries/supports form or load; CONNECTOR creates a necessary relationship between parts; "
            "SURFACE materially changes skin/texture/coverage; SYMBOLIC is physically present because its identity "
            "or provenance carries essential meaning. Do not use SYMBOLIC as permission for decorative filler."
        ),
        json_schema_extra={"enum": list(MATERIAL_ROLES)},
    )
    estimated_fraction: float | None = Field(ge=0.0, le=1.0)
    note: str | None

    @field_validator("role", mode="before")
    @classmethod
    def normalize_legacy_role(cls, value: object) -> object:
        """Keep archived sessions readable while new structured output uses RF-003 roles.

        Old sessions used free-text role labels such as body/base/brace. The JSON schema
        now constrains new Design Brain output to canonical roles, while common historic
        labels are normalized when older sessions are loaded.
        """
        if not isinstance(value, str):
            return value
        raw = value.strip().lower()
        if raw in MATERIAL_ROLES:
            return raw
        aliases = (
            ("hero", ("body", "primary", "focal", "anchor", "main", "vessel")),
            ("structure", ("structural", "base", "brace", "support", "frame", "stand", "spine")),
            ("connector", ("connect", "joint", "hinge", "fastener", "link", "binding", "tie")),
            ("surface", ("skin", "cover", "layer", "texture", "cladding", "wrap", "membrane")),
            ("symbolic", ("symbol", "narrative", "meaning", "semantic", "accent")),
        )
        for canonical, words in aliases:
            if any(word in raw for word in words):
                return canonical
        # Unknown historical labels are preserved rather than corrupting archived meaning.
        # New model output cannot emit them because the strict JSON schema exposes an enum.
        return raw


class MaterialOmission(StrictModel):
    material_item_id: str
    reason: str = Field(
        min_length=4,
        max_length=320,
        description=(
            "Why this supplied source is intentionally NOT used in this future. The reason should explain why omission "
            "makes the object clearer/stronger or why the source does not earn a necessary role."
        ),
    )


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
    material_uses: list[MaterialUse] = Field(
        description=(
            "Only source items that genuinely participate in the future. Every used source gets one primary RF-003 role. "
            "Do not include an item merely to increase source coverage."
        )
    )
    omitted_materials: list[MaterialOmission] = Field(
        description=(
            "Every supplied source item that is not present in material_uses must be listed here with an honest omission reason. "
            "Omission is a valid design decision and is preferable to token participation."
        )
    )
    added_materials: list[str]
    required_tools: list[str]
    key_operations: list[str]
    unresolved_dependencies: list[str]

    @model_validator(mode="before")
    @classmethod
    def preserve_legacy_candidates(cls, value: object) -> object:
        """Archived CandidateForm JSON predates explicit omission accounting."""
        if isinstance(value, dict) and "omitted_materials" not in value:
            value = dict(value)
            value["omitted_materials"] = []
        return value

    @model_validator(mode="after")
    def validate_material_decisions(self) -> "CandidateForm":
        used = [item.material_item_id for item in self.material_uses]
        omitted = [item.material_item_id for item in self.omitted_materials]
        if len(used) != len(set(used)):
            raise ValueError("A source material may appear only once in material_uses")
        if len(omitted) != len(set(omitted)):
            raise ValueError("A source material may appear only once in omitted_materials")
        overlap = set(used) & set(omitted)
        if overlap:
            raise ValueError(
                "A source material cannot be both used and omitted: " + ", ".join(sorted(overlap))
            )
        return self


class SemanticRequirement(StrictModel):
    requirement_id: str
    kind: Literal["transformation", "operation", "material_role"]
    text: str


class FutureSemanticContract(StrictModel):
    version: Literal["v1"] = "v1"
    candidate_id: str
    requirements: list[SemanticRequirement]


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
    critique_status: Literal["revise", "reject"]
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
    semantic_contract: FutureSemanticContract | None = None


class FutureFormsResult(BaseModel):
    internal_candidate_count: int
    reviewed_candidate_count: int
    revision_attempt_count: int = 0
    selected_futures: list[ReviewedFuture]
    needs_regeneration: bool = False
    regeneration_reason: str | None = None
    retrieval_trace: dict[str, Any] = Field(default_factory=dict)

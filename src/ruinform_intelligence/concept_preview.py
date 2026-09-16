from __future__ import annotations

import json
import os

from openai import AsyncOpenAI
from pydantic import BaseModel, ConfigDict, Field

from .future_models import CandidateForm, CandidatePool, FeasibilityReview, FutureFormsResult, ReviewedFuture
from .models import ProjectState
from .reasoning_state import compact_state_json


DEFAULT_MODEL = "gpt-5.6"


class ConceptPreviewError(RuntimeError):
    pass


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class PreviewCandidate(_StrictModel):
    candidate: CandidateForm
    buildability_hint: int = Field(ge=0, le=100)
    originality_hint: int = Field(ge=0, le=100)
    artistic_impact_hint: int = Field(ge=0, le=100)
    usefulness_hint: int = Field(ge=0, le=100)
    value_hint: int = Field(ge=0, le=100)
    confidence_note: str


class PreviewBatch(_StrictModel):
    candidates: list[PreviewCandidate] = Field(min_length=4, max_length=4)


def _instructions(mode: str) -> str:
    return f"""
You are RUINFORM CONCEPT ARCHITECT.
Your job is to rapidly propose exactly four visually strong future objects from the user's existing matter.
This is a PREVIEW stage, not engineering approval. Do not waste time on detailed fabrication analysis.

MODE: {mode.upper()}

Rules:
- Create four genuinely different concepts, not four variations of one idea.
- Prefer transformed objects over passive arrangements of intact objects.
- At least one concept should be surprisingly artistic, one should be plausibly buildable, one should be functional or useful, and one may be hybrid/premium.
- Preserve recognizable traces of source materials.
- Ordinary missing dimensions are not blockers at this stage; use trim-to-fit, wrap-to-fit, fold-to-fit, position-to-fit, adjustable joins, or scale-to-fit language.
- Never invent verified measurements, electrical ratings, heat resistance, load capacity, pressure ratings, or structural certifications.
- If an idea would require those facts later, list them under unresolved_dependencies.
- Cheap ordinary additions such as glue, cord, zip ties, simple fasteners, tape, a small base, wire, thread, or brackets are allowed unless clearly incompatible.
- Keep required tools modest. Avoid advanced fabrication unless the concept truly needs it.
- Make each concept easy to understand in a single hero image.
- Candidate IDs must be preview_01 through preview_04.
- Use only material_item_id values present in the project state.
- Scores are directional hints for preview UX only, not safety or engineering scores.

Return only the strict JSON schema requested by the API.
""".strip()


async def generate_concept_preview(
    *,
    state: ProjectState,
    mode: str = "hybrid",
    user_intent: str | None = None,
    client: AsyncOpenAI | None = None,
    model: str | None = None,
) -> FutureFormsResult:
    model = model or os.getenv("RUINFORM_CONCEPT_PREVIEW_MODEL", DEFAULT_MODEL)
    client = client or AsyncOpenAI()

    response = await client.responses.create(
        model=model,
        reasoning={"effort": "medium"},
        instructions=_instructions(mode),
        input=[
            {
                "role": "user",
                "content": [
                    {
                        "type": "input_text",
                        "text": (
                            "Generate a fast concept preview from this material state.\n\n"
                            f"Project state: {compact_state_json(state)}\n\n"
                            f"User intent: {user_intent or 'open exploration'}"
                        ),
                    }
                ],
            }
        ],
        text={
            "format": {
                "type": "json_schema",
                "name": "ruinform_concept_preview",
                "strict": True,
                "schema": PreviewBatch.model_json_schema(),
            }
        },
    )

    if not response.output_text:
        raise ConceptPreviewError("Concept Architect returned no preview")
    try:
        batch = PreviewBatch.model_validate(json.loads(response.output_text))
    except (json.JSONDecodeError, ValueError) as exc:
        raise ConceptPreviewError("Concept Architect returned invalid structured output") from exc

    material_ids = {item.item_id for item in state.materials}
    reviewed: list[ReviewedFuture] = []
    seen_ids: set[str] = set()
    for item in batch.candidates:
        candidate = item.candidate
        if candidate.candidate_id in seen_ids:
            raise ConceptPreviewError("Concept Architect returned duplicate candidate IDs")
        seen_ids.add(candidate.candidate_id)
        unknown_ids = {use.material_item_id for use in candidate.material_uses} - material_ids
        if unknown_ids:
            raise ConceptPreviewError(
                "Concept Architect referenced unknown material IDs: " + ", ".join(sorted(unknown_ids))
            )
        review = FeasibilityReview(
            candidate_id=candidate.candidate_id,
            status="pass",
            feasibility_score=item.buildability_hint,
            material_fit_score=85,
            buildability_score=item.buildability_hint,
            originality_score=item.originality_hint,
            artistic_impact_score=item.artistic_impact_hint,
            usefulness_score=item.usefulness_hint,
            value_potential_score=item.value_hint,
            reasons=["Fast preview only; detailed feasibility is intentionally deferred until after visual selection."],
            required_changes=[],
            unresolved_dependencies=list(candidate.unresolved_dependencies),
        )
        rank = round(
            0.25 * item.buildability_hint
            + 0.25 * item.originality_hint
            + 0.25 * item.artistic_impact_hint
            + 0.15 * item.usefulness_hint
            + 0.10 * item.value_hint,
            2,
        )
        reviewed.append(
            ReviewedFuture(
                candidate=candidate,
                review=review,
                rank_score=rank,
                revision_history=[],
                visual_brief=None,
            )
        )

    reviewed.sort(key=lambda value: value.rank_score, reverse=True)
    return FutureFormsResult(
        internal_candidate_count=4,
        reviewed_candidate_count=0,
        revision_attempt_count=0,
        selected_futures=reviewed,
        needs_regeneration=False,
        regeneration_reason=None,
    )

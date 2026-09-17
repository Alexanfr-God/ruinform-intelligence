from __future__ import annotations

import json
import os

from openai import AsyncOpenAI
from pydantic import BaseModel, ConfigDict, Field

from .future_models import CandidateForm, FeasibilityReview, FutureFormsResult, ReviewedFuture
from .models import ProjectState
from .prompt_loader import load_prompt_file
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
    base = load_prompt_file("design_brain.md")
    return (
        base
        + "\n\nCURRENT MODE: "
        + mode.upper()
        + "\nCandidate IDs must be exactly preview_01 through preview_04. "
        + "Scores are directional hints for preview UX only, never safety certification."
    )


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

    content: list[dict[str, object]] = [
        {
            "type": "input_text",
            "text": (
                "Invent four RUINFORM futures from the ACTUAL source photographs attached to this message. "
                "Study the images directly before proposing concepts. Do not treat the ProjectState text as a replacement for visual inspection.\n\n"
                f"Project state: {compact_state_json(state)}\n\n"
                f"User intent: {user_intent or 'open exploration'}\n\n"
                "The product goal is not generic upcycling. Create desirable post-consumer artifacts with visible source provenance, "
                "strong silhouette, one authored transformation gesture, and believable material logic."
            ),
        }
    ]

    image_count = 0
    for evidence in state.evidence:
        if evidence.source_type != "image" or not evidence.uri:
            continue
        content.append({"type": "input_image", "image_url": evidence.uri})
        image_count += 1
        if image_count >= 6:
            break

    response = await client.responses.create(
        model=model,
        reasoning={"effort": "high"},
        instructions=_instructions(mode),
        input=[{"role": "user", "content": content}],
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
        raise ConceptPreviewError("Design Brain returned no preview")
    try:
        batch = PreviewBatch.model_validate(json.loads(response.output_text))
    except (json.JSONDecodeError, ValueError) as exc:
        raise ConceptPreviewError("Design Brain returned invalid structured output") from exc

    material_ids = {item.item_id for item in state.materials}
    reviewed: list[ReviewedFuture] = []
    seen_ids: set[str] = set()
    for item in batch.candidates:
        candidate = item.candidate
        if candidate.candidate_id in seen_ids:
            raise ConceptPreviewError("Design Brain returned duplicate candidate IDs")
        seen_ids.add(candidate.candidate_id)
        unknown_ids = {use.material_item_id for use in candidate.material_uses} - material_ids
        if unknown_ids:
            raise ConceptPreviewError(
                "Design Brain referenced unknown material IDs: " + ", ".join(sorted(unknown_ids))
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
            reasons=["Vision-first Design Brain preview; detailed feasibility is intentionally deferred until after visual selection."],
            required_changes=[],
            unresolved_dependencies=list(candidate.unresolved_dependencies),
        )
        rank = round(
            0.20 * item.buildability_hint
            + 0.30 * item.originality_hint
            + 0.30 * item.artistic_impact_hint
            + 0.10 * item.usefulness_hint
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

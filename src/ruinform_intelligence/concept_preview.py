from __future__ import annotations

import json
import os

from openai import AsyncOpenAI
from pydantic import BaseModel, ConfigDict, Field

from .future_models import CandidateForm, FeasibilityReview, FutureFormsResult, ReviewedFuture
from .models import ProjectState
from .prompt_loader import load_prompt_file
from .reasoning_state import compact_state_json
from .taste_library import TasteLibraryError, load_design_brain_runtime_context


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


def _preview_schema(material_ids: list[str]) -> dict[str, object]:
    """Lock structured output to the material IDs that actually exist in this project."""
    schema = PreviewBatch.model_json_schema()
    defs = schema.get("$defs")
    if not isinstance(defs, dict):
        return schema

    material_use = defs.get("MaterialUse")
    if isinstance(material_use, dict):
        properties = material_use.get("properties")
        if isinstance(properties, dict):
            properties["material_item_id"] = {
                "type": "string",
                "enum": material_ids,
            }

    candidate_form = defs.get("CandidateForm")
    if isinstance(candidate_form, dict):
        properties = candidate_form.get("properties")
        if isinstance(properties, dict):
            properties["candidate_id"] = {
                "type": "string",
                "enum": ["preview_01", "preview_02", "preview_03", "preview_04"],
            }

    return schema


def _instructions(mode: str) -> str:
    base = load_prompt_file("design_brain.md")
    try:
        knowledge = load_design_brain_runtime_context()
    except TasteLibraryError as exc:
        raise ConceptPreviewError(
            "Design Brain knowledge pack could not be loaded: " + str(exc)
        ) from exc

    return (
        base
        + "\n\n"
        + knowledge
        + "\n\nPREVIEW stage: this is concept exploration, not engineering approval. "
        + "Detailed feasibility and engineering validation are intentionally deferred until after selection. "
        + "When exact dimensions are unknown, use scale-to-fit, trim-to-fit, mark-from-real-object, or adjustable-fit language rather than inventing measurements. "
        + "Return exactly four concepts. "
        + "The four concepts must not be four variations of one Taste Library card. Transfer different operators to the actual source matter."
        + "\n\nCURRENT MODE: "
        + mode.upper()
        + "\nCandidate IDs must be exactly preview_01 through preview_04. "
        + "Scores are directional hints for preview UX only, never safety certification."
    )


def _difficulty_contract(mode: str) -> str:
    if mode == "easy":
        return (
            "EASY: prioritize household/basic hand tools, reversible or simple joins, low material alteration, "
            "and normally 0-2 simple added parts. Avoid specialist fabrication and unnecessary mechanisms. "
            "The concept still needs one authored design gesture; easy must not mean boring."
        )
    if mode == "wild":
        return (
            "WILD: allow radical geometry, mechanisms, aggressive transformation and specialist fabrication when the idea earns it. "
            "Do not invent complexity merely for spectacle. Preserve visible source provenance and keep the physical logic understandable."
        )
    return (
        "MEDIUM: allow basic workshop operations such as drilling, cutting, bending, clamping and simple mechanisms, "
        "with roughly 0-4 supporting parts when needed. Seek a strong authored transformation without turning the source into an unrelated prop."
    )


def _creative_direction(state: ProjectState, user_intent: str | None) -> str:
    stored = (state.creative_intent.direction or "").strip()
    extra = (user_intent or "").strip()
    if stored and extra and stored != extra:
        return f"PROJECT DIRECTION: {stored}\nSESSION ADJUSTMENT: {extra}"
    return stored or extra or "OPEN EXPLORATION — surprise the user within RUINFORM rules."


def _source_participation_contract(state: ProjectState) -> str:
    count = len(state.materials)
    if count <= 1:
        return (
            "There is one source item. It must remain the unmistakable origin of the concept and carry the primary design gesture."
        )
    if count <= 4:
        return (
            f"There are {count} source items. Each concept should normally integrate at least two of them, and at least two of the four concepts "
            "should integrate ALL source items unless Creative Direction explicitly excludes one. Every used source needs a real structural, functional, "
            "material, spatial, or narrative role. Do not include a source as token decoration. If a concept intentionally omits a source because using it "
            "would weaken the idea, state that decision briefly in unresolved_dependencies."
        )
    return (
        f"There are {count} source items. Do not force all of them into every concept. Each concept should use a coherent subset of at least three when possible, "
        "and the batch as a whole should explore the full source set. Every selected source must perform a real role rather than act as decoration."
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

    material_ids = [item.item_id for item in state.materials]
    if not material_ids:
        raise ConceptPreviewError("Design Brain requires at least one identified material")

    material_contract = "\n".join(
        f"- {item.item_id} = {item.display_name}" for item in state.materials
    )
    intent = state.creative_intent
    content: list[dict[str, object]] = [
        {
            "type": "input_text",
            "text": (
                "Invent four RUINFORM futures from the ACTUAL source photographs attached to this message. "
                "Study the images directly before proposing concepts. Do not treat the ProjectState text as a replacement for visual inspection.\n\n"
                f"Project state: {compact_state_json(state)}\n\n"
                "MATERIAL ID CONTRACT — material_uses may reference ONLY these exact IDs; never invent or rewrite an ID:\n"
                f"{material_contract}\n\n"
                "SOURCE PARTICIPATION CONTRACT:\n"
                f"{_source_participation_contract(state)}\n\n"
                "CREATIVE DIRECTION CONTRACT:\n"
                f"{_creative_direction(state, user_intent)}\n"
                "Treat explicit constraints such as 'no electronics', 'keep intact', 'wall object', or 'useful' as strong project guidance. "
                "Treat mood words as preferences, not permission to ignore the real source objects. This is not a generic text-to-image prompt.\n\n"
                "DIFFICULTY CONTRACT:\n"
                f"{_difficulty_contract(intent.difficulty_mode)}\n\n"
                f"BACKGROUND MODE: {intent.background_mode}. This is a later presentation choice. DO NOT let the background mode determine the object idea. "
                "Invent the object first; the same concept must survive on a clean neutral background.\n\n"
                "COLLECTIBLE AUTHORSHIP TEST:\n"
                "The concept must still feel deliberate and valuable if photographed alone on a clean white/grey background with no apocalypse scenery. "
                "Authorship should come from geometry, negative space, tension, repetition, balance, material contrast, or an unusually clear functional relationship — "
                "not from grime, signage, random hardware, or cinematic background. Reject school-project logic where one object is merely taped, clipped, or bracketed next to another. "
                "Supporting hardware is allowed only when it enables the source-driven idea and must remain visually subordinate.\n\n"
                "The product goal is not generic upcycling. Create desirable post-consumer artifacts with visible source provenance, "
                "strong silhouette, one authored transformation gesture, and believable material logic. "
                "Use the Taste Library as a grammar of design moves, never as a catalogue of objects to reproduce."
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

    if image_count == 0:
        raise ConceptPreviewError(
            "Vision-first Design Brain requires at least one original source photograph"
        )

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
                "schema": _preview_schema(material_ids),
            }
        },
    )

    if not response.output_text:
        raise ConceptPreviewError("Design Brain returned no preview")
    try:
        batch = PreviewBatch.model_validate(json.loads(response.output_text))
    except (json.JSONDecodeError, ValueError) as exc:
        raise ConceptPreviewError("Design Brain returned invalid structured output") from exc

    material_id_set = set(material_ids)
    reviewed: list[ReviewedFuture] = []
    seen_ids: set[str] = set()
    for item in batch.candidates:
        candidate = item.candidate
        if candidate.candidate_id in seen_ids:
            raise ConceptPreviewError("Design Brain returned duplicate candidate IDs")
        seen_ids.add(candidate.candidate_id)
        used_ids = {use.material_item_id for use in candidate.material_uses}
        unknown_ids = used_ids - material_id_set
        if unknown_ids:
            raise ConceptPreviewError(
                "Design Brain referenced unknown material IDs: " + ", ".join(sorted(unknown_ids))
            )
        coverage_ratio = len(used_ids) / max(1, len(material_id_set))
        material_fit_score = round(100 * coverage_ratio)
        review = FeasibilityReview(
            candidate_id=candidate.candidate_id,
            status="pass",
            feasibility_score=item.buildability_hint,
            material_fit_score=material_fit_score,
            buildability_score=item.buildability_hint,
            originality_score=item.originality_hint,
            artistic_impact_score=item.artistic_impact_hint,
            usefulness_score=item.usefulness_hint,
            value_potential_score=item.value_hint,
            reasons=[
                "Vision-first Design Brain preview using original source photographs, persistent Creative Intent, RUINFORM Skill/Style rules, and Taste Library grammar; detailed feasibility is intentionally deferred until after visual selection.",
                f"Source participation: {len(used_ids)}/{len(material_id_set)} identified source items have an explicit concept role.",
            ],
            required_changes=[],
            unresolved_dependencies=list(candidate.unresolved_dependencies),
        )
        rank = round(
            0.15 * item.buildability_hint
            + 0.25 * item.originality_hint
            + 0.25 * item.artistic_impact_hint
            + 0.10 * item.usefulness_hint
            + 0.10 * item.value_hint
            + 0.15 * material_fit_score,
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

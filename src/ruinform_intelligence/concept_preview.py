from __future__ import annotations

import json
import os

from openai import AsyncOpenAI
from pydantic import BaseModel, ConfigDict, Field

from .feasibility import FeasibilityError, review_candidate_pool
from .future_models import CandidateForm, CandidatePool, FeasibilityReview, FutureFormsResult, ReviewedFuture
from .memory_retriever import build_wave3_retrieval_context
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


def _instructions(mode: str, memory_context: str | None = None) -> str:
    base = load_prompt_file("design_brain.md")
    try:
        knowledge = memory_context or load_design_brain_runtime_context()
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
        + "The four concepts must not be four variations of one retrieved Taste Library card. Transfer different operators to the actual source matter. "
        + "MEMORY INFLUENCE CAP: retrieved memory may contribute an operator or warning, but it must not dictate category, silhouette, mechanism recipe, or the number of source objects used. "
        + "At least two concepts must emerge primarily from the current source geometry/material behavior. A conditional lesson such as interaction readability applies only if a concept naturally becomes interactive. "
        + "SOURCE ECONOMY: use the smallest coherent subset that makes the strongest object. Intentional omission is better than token participation. "
        + "DIVERSITY GATE: no more than two concepts may share the same dominant mechanism family; at least one concept must have no moving mechanism unless the user explicitly requests motion."
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
            f"There are {count} source items. Each concept should use the SMALLEST coherent subset that makes the strongest authored object. "
            "No concept is required to use all source items. A two-object idea that is clear and memorable is better than a four-object idea with token roles. "
            "Across the four-concept batch, give each source item at least one meaningful chance when its geometry or material behavior suggests one, but intentional omission is valid. "
            "Every used source must carry a necessary structural, functional, material, spatial, or narrative role. If removing a source makes the concept stronger, omit it and briefly explain the omission in unresolved_dependencies. "
            "When there are three or four source items, normally at least two concepts should use fewer than the full set unless Creative Direction explicitly asks to combine everything."
        )
    return (
        f"There are {count} source items. Do not force all of them into every concept. Each concept should use a coherent subset chosen for the strongest single gesture, "
        "and the batch as a whole should explore the broader source set. Every selected source must perform a real role rather than act as decoration."
    )


def _fallback_review(item: PreviewCandidate, *, used_count: int, total_count: int) -> FeasibilityReview:
    coverage_ratio = used_count / max(1, total_count)
    material_fit_score = round(100 * coverage_ratio)
    return FeasibilityReview(
        candidate_id=item.candidate.candidate_id,
        status="pass",
        feasibility_score=item.buildability_hint,
        material_fit_score=material_fit_score,
        buildability_score=item.buildability_hint,
        originality_score=item.originality_hint,
        artistic_impact_score=item.artistic_impact_hint,
        usefulness_score=item.usefulness_hint,
        value_potential_score=item.value_hint,
        reasons=[
            "Pre-render critic unavailable; showing Design Brain preview with conservative fallback scoring.",
            f"Source participation: {used_count}/{total_count} identified source items have an explicit concept role.",
        ],
        required_changes=[],
        unresolved_dependencies=list(item.candidate.unresolved_dependencies),
    )


def _rank_with_gate(review: FeasibilityReview) -> float:
    gate_score = {"pass": 100.0, "revise": 60.0, "reject": 20.0}[review.status]
    return round(
        0.15 * review.feasibility_score
        + 0.10 * review.material_fit_score
        + 0.10 * review.buildability_score
        + 0.20 * review.originality_score
        + 0.20 * review.artistic_impact_score
        + 0.05 * review.usefulness_score
        + 0.10 * review.value_potential_score
        + 0.10 * gate_score,
        2,
    )


def _critic_note(review: FeasibilityReview) -> str:
    if review.status == "pass":
        reason = review.reasons[0] if review.reasons else "credible direction worth visualizing"
        return f"PRE-RENDER CRITIC PASS — {reason}"
    changes = " · ".join(review.required_changes[:2])
    if not changes:
        changes = review.reasons[0] if review.reasons else "simplify or rethink before spending render tokens"
    return f"PRE-RENDER CRITIC {review.status.upper()} — {changes}"


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

    try:
        memory = build_wave3_retrieval_context(
            state=state,
            mode=mode,
            user_intent=user_intent,
        )
    except TasteLibraryError as exc:
        raise ConceptPreviewError(
            "Wave 3 memory retrieval could not load RUINFORM knowledge: " + str(exc)
        ) from exc

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
                "The Wave 3 memory pack is evidence and design grammar, never a catalogue of objects to reproduce."
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
        instructions=_instructions(mode, memory.prompt_context),
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

    preview_pool = CandidatePool(candidates=[item.candidate for item in batch.candidates])
    critic_error: str | None = None
    try:
        critic_batch = await review_candidate_pool(
            state=state,
            pool=preview_pool,
            concept_mode=True,
            client=client,
            reasoning_effort=os.getenv("RUINFORM_PRE_RENDER_CRITIC_REASONING", "low"),
            retrieval_trace=memory.trace,
        )
        critic_by_id = {review.candidate_id: review for review in critic_batch.reviews}
    except FeasibilityError as exc:
        critic_error = str(exc)
        critic_by_id = {}

    reviewed: list[ReviewedFuture] = []
    critic_trace: list[dict[str, object]] = []
    for item in batch.candidates:
        candidate = item.candidate
        used_ids = {use.material_item_id for use in candidate.material_uses}
        review = critic_by_id.get(candidate.candidate_id)
        if review is None:
            review = _fallback_review(
                item,
                used_count=len(used_ids),
                total_count=len(material_id_set),
            )

        source_reason = (
            f"Source participation: {len(used_ids)}/{len(material_id_set)} identified source items have an explicit concept role. "
            "Coverage itself is not a quality score; source economy is preferred."
        )
        review = review.model_copy(update={"reasons": list(review.reasons) + [source_reason]})

        gate_note = _critic_note(review)
        candidate = candidate.model_copy(
            update={
                "unresolved_dependencies": [gate_note] + list(candidate.unresolved_dependencies)
            }
        )
        rank = _rank_with_gate(review)
        reviewed.append(
            ReviewedFuture(
                candidate=candidate,
                review=review,
                rank_score=rank,
                revision_history=[],
                visual_brief=None,
            )
        )
        critic_trace.append(
            {
                "candidate_id": candidate.candidate_id,
                "name": candidate.name,
                "status": review.status,
                "rank_score": rank,
                "material_fit_score": review.material_fit_score,
                "required_changes": list(review.required_changes),
                "reasons": list(review.reasons[:2]),
            }
        )

    reviewed.sort(key=lambda value: value.rank_score, reverse=True)
    retrieval_trace = dict(memory.trace)
    retrieval_trace["pre_render_critic"] = {
        "version": "wave3_pre_render_critic_v1",
        "reasoning_effort": os.getenv("RUINFORM_PRE_RENDER_CRITIC_REASONING", "low"),
        "error": critic_error,
        "candidates": critic_trace,
    }

    return FutureFormsResult(
        internal_candidate_count=4,
        reviewed_candidate_count=len(critic_by_id),
        revision_attempt_count=0,
        selected_futures=reviewed,
        needs_regeneration=False,
        regeneration_reason=None,
        retrieval_trace=retrieval_trace,
    )
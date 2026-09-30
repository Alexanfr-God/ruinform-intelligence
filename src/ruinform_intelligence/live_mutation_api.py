from __future__ import annotations

import json
import logging
import os

from fastapi import APIRouter, HTTPException
from openai import AsyncOpenAI
from pydantic import BaseModel, ConfigDict, Field

from .evidence_media import externalize_state_for_render
from .future_models import CandidateForm, FeasibilityReview, ReviewedFuture
from .live_api import get_session, store
from .run_store import TransformationSession


router = APIRouter(prefix="/v1/live-transformations", tags=["live-transformations"])
logger = logging.getLogger("ruinform.live_mutation")
DEFAULT_MODEL = "gpt-5.6"
_MIN_ADOPT_SOURCE_SCORE = 35
_MIN_ADOPT_PROVENANCE_SCORE = 30


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class AdoptMutationRequest(BaseModel):
    user_note: str | None = Field(default=None, max_length=800)


class MutationDraft(_StrictModel):
    candidate: CandidateForm
    adoption_summary: str


def _mutation_schema(material_ids: list[str], candidate_id: str) -> dict[str, object]:
    schema = MutationDraft.model_json_schema()
    defs = schema.get("$defs")
    if not isinstance(defs, dict):
        return schema

    candidate_form = defs.get("CandidateForm")
    if isinstance(candidate_form, dict):
        properties = candidate_form.get("properties")
        if isinstance(properties, dict):
            properties["candidate_id"] = {"type": "string", "enum": [candidate_id]}
            material_uses = properties.get("material_uses")
            if isinstance(material_uses, dict):
                material_uses["minItems"] = 1

    material_use = defs.get("MaterialUse")
    if isinstance(material_use, dict):
        properties = material_use.get("properties")
        if isinstance(properties, dict):
            properties["material_item_id"] = {
                "type": "string",
                "enum": material_ids,
            }
    return schema


def _conservative_review(
    *,
    candidate: CandidateForm,
    source_future: ReviewedFuture,
) -> FeasibilityReview:
    old = source_future.review
    return FeasibilityReview(
        candidate_id=candidate.candidate_id,
        status="pass",
        feasibility_score=min(old.feasibility_score, 82),
        material_fit_score=min(old.material_fit_score, 82),
        buildability_score=min(old.buildability_score, 82),
        originality_score=min(old.originality_score, 88),
        artistic_impact_score=min(old.artistic_impact_score, 88),
        usefulness_score=min(old.usefulness_score, 82),
        value_potential_score=min(old.value_potential_score, 85),
        reasons=[
            "User explicitly adopted a productive render mutation as a new future rather than claiming it matches the previous future.",
            "Scores are carried forward conservatively from the pre-render concept and are not physical verification or safety certification.",
        ],
        required_changes=[],
        unresolved_dependencies=list(candidate.unresolved_dependencies),
    )


@router.post(
    "/{session_id}/render/{candidate_id}/adopt",
    response_model=TransformationSession,
)
async def adopt_render_mutation(
    session_id: str,
    candidate_id: str,
    payload: AdoptMutationRequest,
) -> TransformationSession:
    """Turn an interesting failed render into a new explicit future contract.

    This route never pretends the failed image matched the original future. It asks the
    vision model to describe the actual visible mutation using the real source-material
    IDs, replaces the selected future with that new contract, and unlocks the existing
    image as the accepted visual target. Extremely source-detached images remain blocked.
    """
    session = get_session(session_id)
    if session.futures is None:
        raise HTTPException(status_code=409, detail="Generate futures before adopting a mutation")
    if session.render_result is None or session.render_result.status != "failed":
        raise HTTPException(status_code=409, detail="Only a failed critic-gated render can be adopted as a mutation")
    if session.render_result.candidate_id != candidate_id:
        raise HTTPException(status_code=409, detail="The failed render does not belong to this candidate")

    source_future = next(
        (
            item
            for item in session.futures.selected_futures
            if item.candidate.candidate_id == candidate_id
        ),
        None,
    )
    if source_future is None:
        raise HTTPException(status_code=404, detail="Selected future is not available in this session")

    attempts = session.render_result.attempts
    if not attempts:
        raise HTTPException(status_code=409, detail="No rendered mutation is available to adopt")
    last_attempt = attempts[-1]
    image_url = session.render_result.accepted_image_url or last_attempt.render.image_url
    if not image_url:
        raise HTTPException(status_code=409, detail="No rendered mutation image is available to adopt")

    critique = last_attempt.critique
    if (
        critique.source_material_fidelity_score < _MIN_ADOPT_SOURCE_SCORE
        or critique.provenance_visibility_score < _MIN_ADOPT_PROVENANCE_SCORE
    ):
        raise HTTPException(
            status_code=422,
            detail=(
                "This mutation is too detached from the supplied source matter to adopt safely. "
                "Retry the render or choose another future."
            ),
        )

    material_ids = [item.item_id for item in session.project_state.materials]
    if not material_ids:
        raise HTTPException(status_code=409, detail="No source materials are available for mutation adoption")

    mutation_id = f"{candidate_id}_mutation"
    render_state = externalize_state_for_render(
        session.project_state,
        session_id=session.session_id,
    )
    material_contract = "\n".join(
        f"- {item.item_id} = {item.display_name}" for item in render_state.materials
    )
    note = (payload.user_note or "").strip()[:800]

    content: list[dict[str, object]] = [
        {
            "type": "input_text",
            "text": (
                "RUINFORM PRODUCTIVE MUTATION ADOPTION. The user explicitly likes the generated image even though the Render Critic rejected it against the OLD future. "
                "Do not repair the old future and do not pretend the image matched it. Treat the generated image as a new visual discovery and describe the ACTUAL visible object as a new buildable future contract.\n\n"
                f"OLD FUTURE: {source_future.candidate.model_dump_json()}\n\n"
                f"OLD CRITIC SUMMARY: {critique.summary}\n"
                f"OLD CRITIC REGENERATION NOTES: {'; '.join(critique.regeneration_instructions)}\n\n"
                "REAL SOURCE MATERIAL IDS — candidate.material_uses may reference only these exact IDs:\n"
                f"{material_contract}\n\n"
                f"USER ADOPTION NOTE: {note or 'No extra note. Preserve the interesting visible mutation as honestly as possible.'}\n\n"
                "Rules for the NEW future:\n"
                "- Describe only geometry, relationships and source-material roles that are actually visible in the generated mutation.\n"
                "- Preserve recognizable source provenance. Do not relabel invented major objects as if they came from the source photos.\n"
                "- Small necessary fasteners, bindings, backing, cushion/fill or support pieces that were visibly invented may be listed under added_materials.\n"
                "- If the image resembles furniture, sculpture or another category more than the old idea, use the category that matches the image.\n"
                "- key_operations and required_tools must describe a plausible way to recreate the visible result, without invented measurements or safety claims.\n"
                "- unresolved_dependencies must explicitly flag anything that cannot be verified from the image or source evidence.\n"
                "- Give the mutation a concise new name based on what it actually became.\n"
                "- This is concept adoption, not engineering certification."
            ),
        },
        {"type": "input_image", "image_url": str(image_url), "detail": "high"},
    ]
    for evidence in render_state.evidence:
        if evidence.source_type == "image" and evidence.uri:
            content.append({"type": "input_image", "image_url": evidence.uri, "detail": "high"})
            if sum(1 for item in content if item.get("type") == "input_image") >= 7:
                break

    client = AsyncOpenAI()
    model = os.getenv("RUINFORM_MUTATION_ADOPTION_MODEL", DEFAULT_MODEL)
    response = await client.responses.create(
        model=model,
        reasoning={"effort": "medium"},
        instructions=(
            "You are RUINFORM Mutation Curator. Convert a productive image-generation deviation into an honest new concept contract. "
            "The rendered image is authoritative for the new form; the source photographs are authoritative for provenance. "
            "Never claim that invented major matter came from the user. Return only the requested structured output."
        ),
        input=[{"role": "user", "content": content}],
        text={
            "format": {
                "type": "json_schema",
                "name": "ruinform_mutation_adoption",
                "strict": True,
                "schema": _mutation_schema(material_ids, mutation_id),
            }
        },
    )
    if not response.output_text:
        raise HTTPException(status_code=502, detail="Mutation curator returned no structured future")
    try:
        draft = MutationDraft.model_validate(json.loads(response.output_text))
    except (json.JSONDecodeError, ValueError) as exc:
        logger.exception("Mutation curator returned invalid structured output")
        raise HTTPException(status_code=502, detail="Mutation curator returned invalid structured future") from exc

    used_ids = {item.material_item_id for item in draft.candidate.material_uses}
    if not used_ids or not used_ids.issubset(set(material_ids)):
        raise HTTPException(status_code=502, detail="Mutation curator produced an invalid source-material mapping")

    new_review = _conservative_review(candidate=draft.candidate, source_future=source_future)
    adopted_future = ReviewedFuture(
        candidate=draft.candidate,
        review=new_review,
        rank_score=min(source_future.rank_score, 82.0),
        revision_history=list(source_future.revision_history),
        visual_brief=None,
    )
    selected = [
        adopted_future if item.candidate.candidate_id == candidate_id else item
        for item in session.futures.selected_futures
    ]
    adopted_result = session.render_result.model_copy(
        update={
            "candidate_id": mutation_id,
            "status": "pass",
            "accepted_image_url": str(image_url),
            "failure_reason": f"Adopted as a new future: {draft.adoption_summary[:500]}",
        }
    )
    saved = store().save(
        session.model_copy(
            update={
                "stage": "completed",
                "selected_candidate_id": mutation_id,
                "futures": session.futures.model_copy(update={"selected_futures": selected}),
                "render_result": adopted_result,
                "build_plan": None,
                "build_review": None,
                "build_revision_trace": None,
            }
        )
    )
    logger.info(
        "mutation adopted session=%s from=%s to=%s source=%s provenance=%s",
        session_id,
        candidate_id,
        mutation_id,
        critique.source_material_fidelity_score,
        critique.provenance_visibility_score,
    )
    return saved

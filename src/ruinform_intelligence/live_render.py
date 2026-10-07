from __future__ import annotations

import logging
from typing import Literal

from .evidence_media import externalize_state_for_render
from .future_models import FutureSemanticContract
from .render_director import VisualDirectorError, fallback_visual_direction, generate_visual_direction, select_render_mode
from .render_gateway import RenderGatewayError, render_future
from .render_models import RenderAttempt, RenderCritique, RenderRequest, RenderResult
from .render_prompt import compile_preview_render_request
from .render_provider import RenderProvider, RenderProviderError
from .render_review import enforce_render_gate
from .render_review_agent import RenderReviewAgentError, evaluate_render
from .run_store import SqliteRunStore, TransformationSession
from .semantic_contract import freeze_semantic_contract
from .visual_brief import generate_visual_brief


logger = logging.getLogger("ruinform.live_render")
_CONCEPT_RENDER_ATTEMPTS = 3


def _repair_preview_request(request: RenderRequest, instructions: list[str]) -> RenderRequest:
    if not instructions:
        instructions = [
            "Improve fidelity to the immutable Future contract without introducing new required geometry."
        ]
    directive = (
        "\n\nCRITIC-GUIDED REGENERATION DIRECTIVES — IMPLEMENTATION HINTS ONLY; "
        "THEY MUST NOT ALTER THE IMMUTABLE FUTURE CONTRACT:\n"
        + "\n".join(f"- {item}" for item in instructions)
    )
    return request.model_copy(update={"prompt": request.prompt + directive})


def _contract_repair_instructions(
    review: RenderCritique,
    contract: FutureSemanticContract,
) -> list[str]:
    """Convert critic failures into bounded repair hints.

    Free-form critic prose is intentionally not forwarded to the renderer. Otherwise a
    retry can turn a suggestion into a new hard requirement, causing semantic drift across
    repeated renders. Only immutable requirement IDs may drive automatic repair.
    """

    by_id = {item.requirement_id: item for item in contract.requirements}
    instructions: list[str] = []
    for requirement_id in review.failed_contract_requirement_ids:
        requirement = by_id.get(requirement_id)
        if requirement is None:
            continue
        visual_hint = ""
        requirement_text = requirement.text.casefold()
        if "saddle strap" in requirement_text:
            visual_hint = (
                " Visually: show a simple U/omega-shaped pipe saddle strap arching over the OUTSIDE of the elbow/fitting, "
                "with one fixing foot on each side screwed into the base; the fitting itself is not drilled. "
                "Do not replace it with a side bracket, internal clamp, hidden glue, or fabricated cage."
            )
        elif "collar" in requirement_text:
            visual_hint = (
                " Visually: show the collar as a thin fitted sleeve/ring at the contact between the inserted part and the opening, "
                "not as a large invented housing."
            )
        instructions.append(
            f"Repair [{requirement.requirement_id}]: make this existing contract requirement more visibly legible — {requirement.text}."
            f"{visual_hint} Do not add an exact count, new part, new topology, or stricter sequence that is not stated here."
        )
    if instructions:
        return instructions
    if review.status in {"regenerate", "reject"}:
        return [
            "Improve visible fidelity to the immutable Future contract and supplied source ancestry. "
            "Do not invent new mandatory counts, parts, symmetry, topology, or sequence details."
        ]
    return []


def _persist_semantic_contract(
    *,
    session: TransformationSession,
    candidate_id: str,
    store: SqliteRunStore,
):
    if session.futures is None:
        raise ValueError("Generate futures before rendering")
    selected = list(session.futures.selected_futures)
    future_index = next(
        (index for index, item in enumerate(selected) if item.candidate.candidate_id == candidate_id),
        None,
    )
    if future_index is None:
        raise ValueError(f"Candidate {candidate_id} is not an approved visible future")
    future = selected[future_index]
    if future.semantic_contract is not None:
        return session, future, future.semantic_contract

    contract = freeze_semantic_contract(future.candidate)
    future = future.model_copy(update={"semantic_contract": contract})
    selected[future_index] = future
    session = store.save(
        session.model_copy(
            update={
                "futures": session.futures.model_copy(update={"selected_futures": selected})
            }
        )
    )
    return session, future, contract


async def render_session_candidate(
    *,
    session: TransformationSession,
    candidate_id: str,
    provider: RenderProvider,
    store: SqliteRunStore,
    aspect_ratio: str = "4:5",
    max_attempts: int = 2,
    user_prompt: str | None = None,
    presentation_mode: Literal["standard", "post_apocalyptic"] = "post_apocalyptic",
) -> TransformationSession:
    if isinstance(provider, tuple):
        provider = provider[0]

    session, future, semantic_contract = _persist_semantic_contract(
        session=session,
        candidate_id=candidate_id,
        store=store,
    )
    if future.review.status == "reject":
        raise ValueError("Rejected future cannot be rendered")

    concept_mode = session.reasoning_mode == "concept" and session.concept_mode_acknowledged

    session = store.save(
        session.model_copy(
            update={"stage": "rendering", "selected_candidate_id": candidate_id}
        )
    )
    source_state = session.project_state
    render_state = externalize_state_for_render(
        source_state,
        session_id=session.session_id,
    )

    # Render controls are intentionally request-scoped. They guide this image only and do not
    # rewrite the durable project state, selected Future, or immutable semantic contract.
    clean_user_prompt = (user_prompt or "").strip()[:1200]
    existing_direction = (source_state.creative_intent.direction or "").strip()
    if clean_user_prompt:
        render_direction = (
            f"{existing_direction}\n\nRENDER-SPECIFIC USER NOTE: {clean_user_prompt}"
            if existing_direction
            else f"RENDER-SPECIFIC USER NOTE: {clean_user_prompt}"
        )
    else:
        render_direction = existing_direction or None
    render_intent = source_state.creative_intent.model_copy(
        update={
            "direction": render_direction,
            "background_mode": "ruinform_world" if presentation_mode == "post_apocalyptic" else "clean_studio",
        }
    )
    # The Visual Director should receive the original in-session image evidence. Those
    # browser uploads are stored as data URLs and can be sent directly as multimodal
    # input, avoiding an unnecessary public URL fetch hop. The actual image renderer
    # still receives externalized HTTPS references because alternate providers such as
    # Higgsfield require fetchable URLs.
    director_state = source_state.model_copy(update={"creative_intent": render_intent})
    render_state = render_state.model_copy(update={"creative_intent": render_intent})

    if concept_mode:
        render_mode = select_render_mode(future)
        logger.info(
            "render director:start session=%s candidate=%s mode=%s presentation=%s user_note=%s contract=%s",
            session.session_id,
            candidate_id,
            render_mode,
            presentation_mode,
            bool(clean_user_prompt),
            semantic_contract.version,
        )
        try:
            direction = await generate_visual_direction(
                state=director_state,
                future=future,
                render_mode=render_mode,
            )
            logger.info(
                "render director:done session=%s candidate=%s mode=%s hero=%s",
                session.session_id,
                candidate_id,
                direction.render_mode,
                direction.hero_material_id,
            )
        except VisualDirectorError as exc:
            logger.warning(
                "render director:fallback session=%s candidate=%s reason=%s",
                session.session_id,
                candidate_id,
                exc,
            )
            direction = fallback_visual_direction(
                state=render_state,
                future=future,
                render_mode=render_mode,
            )

        request = compile_preview_render_request(
            state=render_state,
            future=future,
            direction=direction,
            aspect_ratio=aspect_ratio,
        )
        attempt_limit = min(max_attempts, _CONCEPT_RENDER_ATTEMPTS)
        attempts: list[RenderAttempt] = []
        last_image_url: str | None = None

        for attempt_index in range(1, attempt_limit + 1):
            logger.info(
                "render preview:start session=%s candidate=%s attempt=%s/%s refs=%s mode=%s",
                session.session_id,
                candidate_id,
                attempt_index,
                attempt_limit,
                len(request.references),
                direction.render_mode,
            )
            try:
                render = await provider.render(request)
                last_image_url = render.image_url
                raw_review = await evaluate_render(
                    future=future,
                    semantic_contract=semantic_contract,
                    request=request,
                    render=render,
                    source_image_urls=[
                        str(evidence.uri)
                        for evidence in director_state.evidence
                        if evidence.source_type == "image" and evidence.uri
                    ],
                )
            except (RenderProviderError, RenderReviewAgentError, ValueError) as exc:
                raise RenderGatewayError(str(exc)) from exc

            review = enforce_render_gate(raw_review)
            attempts.append(
                RenderAttempt(
                    attempt_index=attempt_index,
                    request=request,
                    render=render,
                    critique=review,
                )
            )
            logger.info(
                "render critic session=%s candidate=%s attempt=%s status=%s brief=%s source=%s provenance=%s geometry=%s invention=%s failed_contract=%s provider=%s job=%s",
                session.session_id,
                candidate_id,
                attempt_index,
                review.status,
                review.brief_fidelity_score,
                review.source_material_fidelity_score,
                review.provenance_visibility_score,
                review.geometry_consistency_score,
                review.invention_risk_score,
                ",".join(review.failed_contract_requirement_ids) or "none",
                render.provider,
                render.provider_job_id,
            )

            # Persist every completed render+critic attempt while the job is still alive.
            # This makes progress observable to the browser and preserves the latest
            # generated image if the process is restarted before the next repair pass.
            session = store.save(
                session.model_copy(
                    update={
                        "stage": "rendering",
                        "render_result": RenderResult(
                            candidate_id=future.candidate.candidate_id,
                            status="failed",
                            accepted_image_url=last_image_url,
                            attempts=attempts,
                            failure_reason="Quality review is still in progress.",
                        ),
                    }
                )
            )

            if review.status == "pass":
                result = RenderResult(
                    candidate_id=future.candidate.candidate_id,
                    status="pass",
                    accepted_image_url=render.image_url,
                    attempts=attempts,
                    failure_reason=None,
                )
                return store.save(
                    session.model_copy(update={"stage": "completed", "render_result": result})
                )

            if attempt_index >= attempt_limit:
                break

            repair_instructions = _contract_repair_instructions(review, semantic_contract)
            if review.status == "reject":
                repair_instructions = [
                    "Start the visual composition over while preserving the same immutable Future contract and source ancestry. "
                    "Do not preserve failed invented geometry and do not introduce any new hard requirement.",
                    *repair_instructions,
                ]
            request = _repair_preview_request(request, repair_instructions)

        result = RenderResult(
            candidate_id=future.candidate.candidate_id,
            status="failed",
            accepted_image_url=last_image_url,
            attempts=attempts,
            failure_reason=f"No concept render passed the visual trust gate within {attempt_limit} attempts.",
        )
        return store.save(
            session.model_copy(update={"stage": "failed", "render_result": result})
        )

    if future.visual_brief is None:
        logger.info("render visual-brief:start session=%s candidate=%s", session.session_id, candidate_id)
        brief = await generate_visual_brief(
            state=render_state,
            candidate=future.candidate,
            review=future.review,
            concept_mode=concept_mode,
        )
        future = future.model_copy(update={"visual_brief": brief})
        updated_selected = [
            future if item.candidate.candidate_id == candidate_id else item
            for item in session.futures.selected_futures
        ]
        session = store.save(
            session.model_copy(
                update={
                    "futures": session.futures.model_copy(
                        update={"selected_futures": updated_selected}
                    )
                }
            )
        )
        logger.info("render visual-brief:done session=%s candidate=%s", session.session_id, candidate_id)

    logger.info("render provider:start session=%s candidate=%s", session.session_id, candidate_id)
    result = await render_future(
        state=render_state,
        future=future,
        provider=provider,
        aspect_ratio=aspect_ratio,
        max_attempts=max_attempts,
    )
    logger.info(
        "render provider:done session=%s candidate=%s status=%s attempts=%s",
        session.session_id,
        candidate_id,
        result.status,
        len(result.attempts),
    )
    stage = "completed" if result.status == "pass" else "failed"
    return store.save(
        session.model_copy(update={"stage": stage, "render_result": result})
    )

from __future__ import annotations

import logging
from typing import Literal

from .evidence_media import externalize_state_for_render
from .render_director import VisualDirectorError, fallback_visual_direction, generate_visual_direction, select_render_mode
from .render_gateway import RenderGatewayError, render_future
from .render_models import RenderAttempt, RenderRequest, RenderResult
from .render_prompt import compile_preview_render_request
from .render_provider import RenderProvider, RenderProviderError
from .render_review import enforce_render_gate
from .render_review_agent import RenderReviewAgentError, evaluate_render
from .run_store import SqliteRunStore, TransformationSession
from .visual_brief import generate_visual_brief


logger = logging.getLogger("ruinform.live_render")
_CONCEPT_RENDER_ATTEMPTS = 2


def _repair_preview_request(request: RenderRequest, instructions: list[str]) -> RenderRequest:
    if not instructions:
        instructions = [
            "Regenerate more faithfully to the selected future and the supplied source photographs."
        ]
    directive = "\n\nCRITIC-GUIDED REGENERATION DIRECTIVES:\n" + "\n".join(
        f"- {item}" for item in instructions
    )
    return request.model_copy(update={"prompt": request.prompt + directive})


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

    if session.futures is None:
        raise ValueError("Generate futures before rendering")
    future = next(
        (
            item
            for item in session.futures.selected_futures
            if item.candidate.candidate_id == candidate_id
        ),
        None,
    )
    if future is None:
        raise ValueError(f"Candidate {candidate_id} is not an approved visible future")
    if future.review.status == "reject":
        raise ValueError("Rejected future cannot be rendered")

    concept_mode = session.reasoning_mode == "concept" and session.concept_mode_acknowledged

    session = store.save(
        session.model_copy(
            update={"stage": "rendering", "selected_candidate_id": candidate_id}
        )
    )
    render_state = externalize_state_for_render(
        session.project_state,
        session_id=session.session_id,
    )

    # Render controls are intentionally request-scoped. They guide this image only and do not
    # rewrite the durable project state or the selected future. This keeps a user's optional
    # render note and presentation choice from leaking into later projects or build evidence.
    clean_user_prompt = (user_prompt or "").strip()[:1200]
    existing_direction = (render_state.creative_intent.direction or "").strip()
    if clean_user_prompt:
        render_direction = (
            f"{existing_direction}\n\nRENDER-SPECIFIC USER NOTE: {clean_user_prompt}"
            if existing_direction
            else f"RENDER-SPECIFIC USER NOTE: {clean_user_prompt}"
        )
    else:
        render_direction = existing_direction or None
    render_intent = render_state.creative_intent.model_copy(
        update={
            "direction": render_direction,
            "background_mode": "ruinform_world" if presentation_mode == "post_apocalyptic" else "clean_studio",
        }
    )
    render_state = render_state.model_copy(update={"creative_intent": render_intent})

    if concept_mode:
        render_mode = select_render_mode(future)
        logger.info(
            "render director:start session=%s candidate=%s mode=%s presentation=%s user_note=%s",
            session.session_id,
            candidate_id,
            render_mode,
            presentation_mode,
            bool(clean_user_prompt),
        )
        try:
            direction = await generate_visual_direction(
                state=render_state,
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
                    request=request,
                    render=render,
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
                "render critic session=%s candidate=%s attempt=%s status=%s brief=%s source=%s provenance=%s geometry=%s invention=%s provider=%s job=%s",
                session.session_id,
                candidate_id,
                attempt_index,
                review.status,
                review.brief_fidelity_score,
                review.source_material_fidelity_score,
                review.provenance_visibility_score,
                review.geometry_consistency_score,
                review.invention_risk_score,
                render.provider,
                render.provider_job_id,
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

            repair_instructions = list(review.regeneration_instructions)
            if review.status == "reject":
                repair_instructions = [
                    "The previous image was fundamentally incompatible with the selected future. Start the visual composition over rather than polishing or preserving that failed topology.",
                    "Re-anchor the next image to the supplied source photographs, the selected transformation, its signature gesture, and its required negative space. Do not keep invented geometry merely because it looked attractive.",
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

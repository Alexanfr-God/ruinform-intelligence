from __future__ import annotations

import logging
from typing import Literal

from .evidence_media import externalize_state_for_render
from .render_director import VisualDirectorError, fallback_visual_direction, generate_visual_direction, select_render_mode
from .render_gateway import render_future
from .render_models import RenderResult
from .render_prompt import compile_preview_render_request
from .render_provider import RenderProvider
from .run_store import SqliteRunStore, TransformationSession
from .visual_brief import generate_visual_brief


logger = logging.getLogger("ruinform.live_render")


async def render_session_candidate(
    *,
    session: TransformationSession,
    candidate_id: str,
    provider: RenderProvider,
    store: SqliteRunStore,
    aspect_ratio: str = "4:5",
    max_attempts: int = 3,
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

        # Visual-first path stays single-pass at the image provider. The added Visual Director
        # sees the real source images plus the request-scoped user note/presentation choice.
        request = compile_preview_render_request(
            state=render_state,
            future=future,
            direction=direction,
            aspect_ratio=aspect_ratio,
        )
        logger.info(
            "render preview:start session=%s candidate=%s refs=%s mode=%s",
            session.session_id,
            candidate_id,
            len(request.references),
            direction.render_mode,
        )
        render = await provider.render(request)
        logger.info(
            "render preview:done session=%s candidate=%s provider=%s job=%s",
            session.session_id,
            candidate_id,
            render.provider,
            render.provider_job_id,
        )
        result = RenderResult(
            candidate_id=future.candidate.candidate_id,
            status="pass",
            accepted_image_url=render.image_url,
            attempts=[],
            failure_reason=None,
        )
        return store.save(
            session.model_copy(update={"stage": "completed", "render_result": result})
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

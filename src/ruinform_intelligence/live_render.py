from __future__ import annotations

import logging

from .evidence_media import externalize_state_for_render
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

    if concept_mode:
        # Visual-first path: one deterministic prompt compilation + one provider call.
        # We deliberately defer the expensive VisualBrief and strict Render Critic until
        # the user has decided the visual direction is worth pursuing.
        request = compile_preview_render_request(
            state=render_state,
            future=future,
            aspect_ratio=aspect_ratio,
        )
        logger.info(
            "render preview:start session=%s candidate=%s refs=%s",
            session.session_id,
            candidate_id,
            len(request.references),
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
            state=session.project_state,
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

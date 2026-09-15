from __future__ import annotations

import logging

from .render_gateway import render_future
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

    session = store.save(
        session.model_copy(
            update={"stage": "rendering", "selected_candidate_id": candidate_id}
        )
    )
    logger.info("render provider:start session=%s candidate=%s", session.session_id, candidate_id)
    result = await render_future(
        state=session.project_state,
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

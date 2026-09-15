from __future__ import annotations

from .render_gateway import render_future
from .render_provider import RenderProvider
from .run_store import SqliteRunStore, TransformationSession


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

    session = store.save(
        session.model_copy(
            update={"stage": "rendering", "selected_candidate_id": candidate_id}
        )
    )
    result = await render_future(
        state=session.project_state,
        future=future,
        provider=provider,
        aspect_ratio=aspect_ratio,
        max_attempts=max_attempts,
    )
    stage = "completed" if result.status == "pass" else "failed"
    return store.save(
        session.model_copy(update={"stage": stage, "render_result": result})
    )

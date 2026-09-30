from __future__ import annotations

import logging

from .concept_preview import generate_concept_preview
from .evidence_gate import can_advance_to_ideation
from .future_models import FuturePreferences
from .future_pipeline import discover_future_forms
from .run_store import SqliteRunStore, TransformationSession


logger = logging.getLogger("ruinform.live_futures")


async def discover_session_futures(
    *,
    session: TransformationSession,
    preferences: FuturePreferences,
    user_intent: str | None,
    max_revision_rounds: int,
    store: SqliteRunStore,
) -> TransformationSession:
    verified_ready = can_advance_to_ideation(session.project_state)
    concept_ready = session.reasoning_mode == "concept" and session.concept_mode_acknowledged
    if not verified_ready and not concept_ready:
        raise ValueError("Project still needs more evidence before future discovery")

    effective_preferences = preferences.model_copy(
        update={"concept_mode": bool(concept_ready)}
    )

    if concept_ready:
        logger.info("futures vision-preview:start session=%s", session.session_id)
        futures = await generate_concept_preview(
            state=session.project_state,
            mode="hybrid",
            user_intent=user_intent,
        )
        logger.info(
            "futures vision-preview:done session=%s visible=%s",
            session.session_id,
            len(futures.selected_futures),
        )
    else:
        logger.info("futures verified:start session=%s", session.session_id)
        futures = await discover_future_forms(
            state=session.project_state,
            preferences=effective_preferences,
            user_intent=user_intent,
            max_revision_rounds=max_revision_rounds,
        )
        logger.info(
            "futures verified:done session=%s visible=%s",
            session.session_id,
            len(futures.selected_futures),
        )

    return store.save(
        session.model_copy(update={"stage": "futures_ready", "futures": futures})
    )

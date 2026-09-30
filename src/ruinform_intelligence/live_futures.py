from __future__ import annotations

import logging
from typing import Literal

from .evidence_gate import can_advance_to_ideation
from .future_models import FuturePreferences
from .future_pipeline import discover_future_forms
from .run_store import SqliteRunStore, TransformationSession
from .self_healing_preview import generate_concept_preview


logger = logging.getLogger("ruinform.live_futures")
ConceptMode = Literal["hybrid", "art", "buildable", "functional"]
DifficultyMode = Literal["easy", "medium", "wild"]
_VISIBLE_FUTURE_COUNT = 2


def _internal_candidate_count(mode: ConceptMode) -> int:
    """Spend search budget where it protects quality.

    MIX/HYBRID remains broad enough to benefit from one extra internal direction,
    while focused modes can go straight to two candidates. In every case the same
    pre-render critic and one-pass self-healing remain enabled.
    """
    return 3 if mode == "hybrid" else 2


def _visible_preview(futures):
    """Expose only the two strongest directions to the Workshop."""
    ranked = list(futures.selected_futures)
    usable = [item for item in ranked if item.review.status != "reject"]
    chosen = usable[:_VISIBLE_FUTURE_COUNT]
    if len(chosen) < _VISIBLE_FUTURE_COUNT:
        chosen_ids = {item.candidate.candidate_id for item in chosen}
        chosen.extend(
            item
            for item in ranked
            if item.candidate.candidate_id not in chosen_ids
        )
        chosen = chosen[:_VISIBLE_FUTURE_COUNT]
    return futures.model_copy(update={"selected_futures": chosen})


async def discover_session_futures(
    *,
    session: TransformationSession,
    preferences: FuturePreferences,
    user_intent: str | None,
    max_revision_rounds: int,
    store: SqliteRunStore,
    mode: ConceptMode = "hybrid",
    difficulty_mode: DifficultyMode | None = None,
) -> TransformationSession:
    verified_ready = can_advance_to_ideation(session.project_state)
    concept_ready = session.reasoning_mode == "concept" and session.concept_mode_acknowledged
    if not verified_ready and not concept_ready:
        raise ValueError("Project still needs more evidence before future discovery")

    effective_preferences = preferences.model_copy(
        update={"concept_mode": bool(concept_ready)}
    )

    working_state = session.project_state
    if difficulty_mode is not None:
        working_state = working_state.model_copy(
            update={
                "creative_intent": working_state.creative_intent.model_copy(
                    update={"difficulty_mode": difficulty_mode}
                )
            }
        )

    if concept_ready:
        candidate_count = _internal_candidate_count(mode)
        logger.info(
            "futures vision-preview:start session=%s mode=%s difficulty=%s internal_budget=%s exposed=%s",
            session.session_id,
            mode,
            working_state.creative_intent.difficulty_mode,
            candidate_count,
            _VISIBLE_FUTURE_COUNT,
        )
        futures = await generate_concept_preview(
            state=working_state,
            mode=mode,
            user_intent=user_intent,
            candidate_count=candidate_count,
        )
        internal_visible = len(futures.selected_futures)
        futures = _visible_preview(futures)
        logger.info(
            "futures vision-preview:done session=%s internal_visible=%s exposed=%s statuses=%s",
            session.session_id,
            internal_visible,
            len(futures.selected_futures),
            ",".join(item.review.status for item in futures.selected_futures),
        )
    else:
        logger.info("futures verified:start session=%s", session.session_id)
        futures = await discover_future_forms(
            state=working_state,
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
        session.model_copy(
            update={
                "stage": "futures_ready",
                "futures": futures,
                "project_state": working_state,
            }
        )
    )

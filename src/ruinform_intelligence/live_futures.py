from __future__ import annotations

from .evidence_gate import can_advance_to_ideation
from .future_models import FuturePreferences
from .future_pipeline import discover_future_forms
from .run_store import SqliteRunStore, TransformationSession


async def discover_session_futures(
    *,
    session: TransformationSession,
    preferences: FuturePreferences,
    user_intent: str | None,
    max_revision_rounds: int,
    store: SqliteRunStore,
) -> TransformationSession:
    if not can_advance_to_ideation(session.project_state):
        raise ValueError("Project still needs more evidence before future discovery")
    futures = await discover_future_forms(
        state=session.project_state,
        preferences=preferences,
        user_intent=user_intent,
        max_revision_rounds=max_revision_rounds,
    )
    return store.save(
        session.model_copy(update={"stage": "futures_ready", "futures": futures})
    )

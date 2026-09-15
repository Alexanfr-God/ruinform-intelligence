from __future__ import annotations

from .future_models import FuturePreferences
from .run_store import SqliteRunStore, TransformationSession


async def discover_session_futures(
    *,
    session: TransformationSession,
    preferences: FuturePreferences,
    user_intent: str | None,
    max_revision_rounds: int,
    store: SqliteRunStore,
) -> TransformationSession:
    raise NotImplementedError

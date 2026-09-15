from __future__ import annotations

from .evidence_gate import can_advance_to_ideation
from .material_eye import analyze_materials
from .models import ProjectConstraints
from .run_store import SqliteRunStore, TransformationSession


async def start_session(
    *,
    image_urls: list[str],
    user_context: str | None,
    constraints: ProjectConstraints,
    store: SqliteRunStore,
) -> TransformationSession:
    state, _ = await analyze_materials(
        image_urls=image_urls,
        user_context=user_context,
        constraints=constraints,
    )
    stage = "ready_for_futures" if can_advance_to_ideation(state) else "evidence_required"
    return store.save(
        TransformationSession(project_id=state.project_id, stage=stage, project_state=state)
    )

from __future__ import annotations

from .evidence_gate import can_advance_to_ideation
from .evidence_loop import MeasurementInput, continue_evidence_loop
from .run_store import SqliteRunStore, TransformationSession


async def continue_session_evidence(
    *,
    session: TransformationSession,
    new_image_urls: list[str],
    user_statement: str | None,
    measurements: list[MeasurementInput],
    store: SqliteRunStore,
) -> TransformationSession:
    result = await continue_evidence_loop(
        current_state=session.project_state,
        new_image_urls=new_image_urls,
        user_statement=user_statement,
        measurements=measurements,
    )
    stage = "ready_for_futures" if can_advance_to_ideation(result.project_state) else "evidence_required"
    return store.save(
        session.model_copy(
            update={
                "stage": stage,
                "project_state": result.project_state,
                "futures": None,
                "selected_candidate_id": None,
                "render_result": None,
            }
        )
    )

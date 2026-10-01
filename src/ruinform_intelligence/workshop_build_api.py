from __future__ import annotations

import asyncio
import logging

from fastapi import APIRouter, HTTPException

from .build_evidence import state_for_build_candidate
from .build_master import BuildMasterError, generate_reviewed_build_package
from .run_store import SessionNotFound, create_run_store


router = APIRouter(prefix="/v1/live-transformations", tags=["workshop-build-gate"])
logger = logging.getLogger("ruinform.workshop_build_api")
_build_tasks: dict[str, asyncio.Task[None]] = {}


def _session(session_id: str):
    try:
        return create_run_store().get(session_id)
    except SessionNotFound as exc:
        raise HTTPException(status_code=404, detail="Transformation session not found") from exc


def _selected_future(session):
    if session.futures is None or not session.selected_candidate_id:
        raise HTTPException(status_code=409, detail="Select and render a future before the build gate")
    future = next(
        (
            item
            for item in session.futures.selected_futures
            if item.candidate.candidate_id == session.selected_candidate_id
        ),
        None,
    )
    if future is None:
        raise HTTPException(status_code=409, detail="Selected future is unavailable")
    if future.review.status != "pass":
        raise HTTPException(status_code=409, detail="Only a passed future may enter the build gate")
    return future


def _payload(session, *, pending: bool = False) -> dict[str, object]:
    plan = session.build_plan
    review = session.build_review
    return {
        "ok": True,
        "pending": pending,
        "sessionId": session.session_id,
        "candidateId": session.selected_candidate_id,
        "stage": "build_generating" if pending else session.stage,
        "readyToBuild": bool(plan is not None and review is not None and review.status == "pass"),
        "plan": plan.model_dump(mode="json") if plan is not None else None,
        "review": review.model_dump(mode="json") if review is not None else None,
        "revisionTrace": session.build_revision_trace.model_dump(mode="json") if session.build_revision_trace is not None else None,
        "lastError": session.last_error,
    }


async def _build_job(session_id: str) -> None:
    try:
        current = _session(session_id)
        future = _selected_future(current)
        render = current.render_result
        if render is None or render.status != "pass" or not render.accepted_image_url:
            raise BuildMasterError("Build gate requires the accepted render")
        if render.candidate_id != future.candidate.candidate_id:
            raise BuildMasterError("Approved render does not match the selected future")

        scoped_state = state_for_build_candidate(
            current.project_state,
            future.candidate.candidate_id,
        )
        package = await generate_reviewed_build_package(
            state=scoped_state,
            future=future,
            accepted_image_url=str(render.accepted_image_url),
            concept_mode=True,
        )
        latest = _session(session_id)
        create_run_store().save(
            latest.model_copy(
                update={
                    "stage": "build_plan_ready",
                    "build_plan": package.plan,
                    "build_review": package.review,
                    "build_revision_trace": package.revision_trace,
                    "last_error": None,
                    "last_error_stage": None,
                }
            )
        )
    except Exception as exc:
        logger.exception("workshop build gate failed session=%s", session_id)
        try:
            latest = _session(session_id)
            create_run_store().save(
                latest.model_copy(
                    update={
                        "stage": "failed",
                        "last_error": str(exc)[:1200],
                        "last_error_stage": "build_gate",
                    }
                )
            )
        except Exception:
            logger.exception("could not persist build gate failure session=%s", session_id)
    finally:
        _build_tasks.pop(session_id, None)


@router.post("/{session_id}/build/start")
async def start_build_gate(session_id: str) -> dict[str, object]:
    session = _session(session_id)
    future = _selected_future(session)
    render = session.render_result
    if render is None or render.status != "pass" or not render.accepted_image_url:
        raise HTTPException(status_code=409, detail="Accepted render required before build gate")
    if render.candidate_id != future.candidate.candidate_id:
        raise HTTPException(status_code=409, detail="Accepted render does not match selected future")

    if session.build_plan is not None and session.build_review is not None:
        return _payload(session, pending=False)

    active = _build_tasks.get(session_id)
    if active is not None and not active.done():
        return _payload(session, pending=True)

    if session.stage == "failed" and session.last_error_stage == "build_gate":
        session = create_run_store().save(
            session.model_copy(
                update={
                    "stage": "completed",
                    "last_error": None,
                    "last_error_stage": None,
                }
            )
        )

    task = asyncio.create_task(_build_job(session_id))
    _build_tasks[session_id] = task
    return _payload(session, pending=True)


@router.get("/{session_id}/build")
async def read_build_gate(session_id: str) -> dict[str, object]:
    session = _session(session_id)
    active = _build_tasks.get(session_id)
    if active is not None and not active.done():
        return _payload(session, pending=True)
    if session.stage == "failed" and session.last_error_stage == "build_gate":
        return {
            "ok": False,
            "pending": False,
            "sessionId": session.session_id,
            "stage": session.stage,
            "code": "build_gate_failed",
            "detail": session.last_error or "Build gate failed",
        }
    return _payload(session, pending=False)

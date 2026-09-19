from __future__ import annotations

import html
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse

from .build_evidence import (
    count_candidate_evidence_rounds,
    evidence_property_key,
    parse_physical_value,
    round_marker,
    upload_to_data_url,
    utc_now_iso,
)
from .build_master import BuildMasterError
from .models import EvidenceItem
from . import studio as studio_module
from .workshop_evidence_ux import derive_workshop_evidence_request


router = APIRouter(tags=["studio-build-evidence"])
_MAX_EVIDENCE_ROUNDS = 6


def _future_for_session(session):
    if session.futures is None or not session.selected_candidate_id:
        return None
    return next(
        (
            future
            for future in session.futures.selected_futures
            if future.candidate.candidate_id == session.selected_candidate_id
        ),
        None,
    )


@router.post(
    "/studio/{session_id}/build/evidence",
    response_class=HTMLResponse,
    dependencies=[Depends(studio_module._require_access)],
)
async def studio_build_evidence_submit(session_id: str, request: Request) -> str:
    session = studio_module._session(session_id)
    future = _future_for_session(session)
    if future is None:
        raise HTTPException(status_code=400, detail="Selected future is unavailable")
    if (
        session.render_result is None
        or session.render_result.status != "pass"
        or session.render_result.accepted_image_url is None
        or session.render_result.candidate_id != future.candidate.candidate_id
    ):
        raise HTTPException(status_code=409, detail="Build evidence requires the same approved render")
    if session.build_plan is None or session.build_review is None:
        raise HTTPException(status_code=409, detail="Run MAKE IT REAL before adding build evidence")
    if session.build_review.status == "pass":
        return studio_module._page(
            studio_module._build_page(session),
            title="RUINFORM / MAKE IT REAL",
        )

    round_count = count_candidate_evidence_rounds(
        session.project_state,
        future.candidate.candidate_id,
    )
    if round_count >= _MAX_EVIDENCE_ROUNDS:
        return studio_module._page(
            "<div class='k'>BUILD EVIDENCE / ROUND LIMIT</div><h1>STOP.</h1>"
            "<p>This prototype has already used six evidence-resume rounds. Do not keep looping the same handoff. "
            "Re-inspect the concept or start a revised design direction.</p>"
            f"<p><a href='/studio/{html.escape(session_id)}/build'>BACK TO BUILD</a></p>",
            title="RUINFORM / BUILD EVIDENCE LIMIT",
        )

    evidence_request = derive_workshop_evidence_request(
        plan=session.build_plan,
        review=session.build_review,
        candidate_id=future.candidate.candidate_id,
    )
    if evidence_request is None:
        raise HTTPException(status_code=409, detail="No build evidence is currently requested")

    form = await request.form()
    new_evidence: list[EvidenceItem] = []
    evidence_ids: list[str] = []
    candidate_id = future.candidate.candidate_id

    for task in evidence_request.tasks:
        answer_key = f"answer__{task.task_id}"
        photo_key = f"photo__{task.task_id}"
        answer_value = form.get(answer_key)
        answer = answer_value.strip() if isinstance(answer_value, str) else ""
        if answer:
            parsed_value, parsed_unit = parse_physical_value(answer)
            evidence_id = f"build_text_{uuid4()}"
            new_evidence.append(
                EvidenceItem(
                    evidence_id=evidence_id,
                    source_type="measurement" if task.input_kind == "measurement" else "user_statement",
                    property_key=evidence_property_key(candidate_id, task),
                    text=f"{task.title}: {answer}",
                    value=parsed_value if parsed_value is not None else None,
                    unit=parsed_unit,
                    created_at_iso=utc_now_iso(),
                )
            )
            evidence_ids.append(evidence_id)

        photo_value = form.get(photo_key)
        if photo_value is not None and getattr(photo_value, "filename", ""):
            try:
                data_url = await upload_to_data_url(photo_value)
            except ValueError as exc:
                return studio_module._page(
                    "<div class='k'>BUILD EVIDENCE / UPLOAD ERROR</div><h1>STOP.</h1>"
                    f"<p>{html.escape(str(exc))}</p>"
                    f"<p><a href='/studio/{html.escape(session_id)}/build'>BACK TO BUILD</a></p>",
                    title="RUINFORM / BUILD EVIDENCE ERROR",
                )
            evidence_id = f"build_image_{uuid4()}"
            new_evidence.append(
                EvidenceItem(
                    evidence_id=evidence_id,
                    source_type="image",
                    property_key=evidence_property_key(candidate_id, task),
                    uri=data_url,
                    text=f"Evidence photo for: {task.title}",
                    created_at_iso=utc_now_iso(),
                )
            )
            evidence_ids.append(evidence_id)

    if not new_evidence:
        return studio_module._page(
            "<div class='k'>BUILD EVIDENCE / EMPTY ROUND</div><h1>ADD A REAL FACT.</h1>"
            "<p>Nothing was submitted. Add at least one measurement, inspection finding, documented fact, or evidence photo. "
            "Do not estimate from the generated render.</p>"
            f"<p><a href='/studio/{html.escape(session_id)}/build'>BACK TO BUILD</a></p>",
            title="RUINFORM / BUILD EVIDENCE",
        )

    before_status = session.build_review.status
    updated_state = session.project_state.model_copy(
        update={"evidence": list(session.project_state.evidence) + new_evidence}
    )

    try:
        package = await studio_module.generate_reviewed_build_package(
            state=updated_state,
            future=future,
            accepted_image_url=str(session.render_result.accepted_image_url),
            concept_mode=True,
        )
    except BuildMasterError as exc:
        return studio_module._page(
            "<div class='k'>BUILD EVIDENCE / RESUME ERROR</div><h1>STOP.</h1>"
            f"<p>{html.escape(str(exc))}</p>"
            f"<p><a href='/studio/{html.escape(session_id)}/build'>BACK TO BUILD</a></p>",
            title="RUINFORM / BUILD EVIDENCE ERROR",
        )

    marker = round_marker(
        candidate_id,
        round_count + 1,
        evidence_ids,
        before_status,
        package.review.status,
    )
    updated_state = updated_state.model_copy(
        update={"evidence": list(updated_state.evidence) + [marker]}
    )
    session = studio_module._studio_store().save(
        session.model_copy(
            update={
                "project_state": updated_state,
                "stage": "build_plan_ready",
                "build_plan": package.plan,
                "build_review": package.review,
                "build_revision_trace": package.revision_trace,
            }
        )
    )
    return studio_module._page(
        studio_module._build_page(session),
        title="RUINFORM / MAKE IT REAL",
    )

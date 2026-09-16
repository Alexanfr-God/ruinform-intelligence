from __future__ import annotations

import html

from fastapi import APIRouter, Depends
from fastapi.responses import HTMLResponse

from .build_master import BuildMasterError, generate_build_plan
from .lab import _get_session, _lab_store, _page, _require_lab_access
from .live_render import render_session_candidate
from .provider_factory import create_higgsfield_provider
from .render_gateway import RenderGatewayError
from .render_provider import RenderProviderError


router = APIRouter(tags=["lab-postproduction"])


def _list_html(items: list[str], *, empty: str = "none") -> str:
    if not items:
        return f"<p class='muted'>{html.escape(empty)}</p>"
    return "<ul>" + "".join(f"<li>{html.escape(item)}</li>" for item in items) + "</ul>"


def _postproduction_page(session) -> str:
    result = session.render_result
    plan = session.build_plan
    if result is None:
        return _page("<h1>NO RENDER.</h1><p>The session contains no render result.</p>")

    concept = session.reasoning_mode == "concept" and session.concept_mode_acknowledged
    image = ""
    if result.accepted_image_url:
        image = (
            f"<img class='result' src='{html.escape(str(result.accepted_image_url), quote=True)}' "
            "alt='RUINFORM generated future form' />"
        )

    review_html = ""
    if result.attempts:
        critique = result.attempts[-1].critique
        review_html = (
            f"<div class='scores'><span>BRIEF FIDELITY {critique.brief_fidelity_score}</span>"
            f"<span>SOURCE FIDELITY {critique.source_material_fidelity_score}</span>"
            f"<span>PROVENANCE {critique.provenance_visibility_score}</span>"
            f"<span>INVENTION RISK {critique.invention_risk_score}</span></div>"
            f"<p>{html.escape(critique.summary)}</p>"
        )

    failure = f"<pre>{html.escape(result.failure_reason)}</pre>" if result.failure_reason else ""
    if result.status != "pass" or plan is None:
        return _page(
            f"""
<div class='kicker'>RENDER GATE / {html.escape(result.status.upper())}</div>
<h1>RENDER REJECTED.</h1>
{image}{review_html}{failure}
<p class='muted'>No build plan is produced from a render that did not pass the visual trust gate.</p>
<div class='rule'></div><p><a href='/lab/{html.escape(session.session_id)}/futures'>BACK TO FUTURES</a></p>
"""
        )

    steps: list[str] = []
    for step in plan.steps:
        sources = ", ".join(step.source_material_ids) or "no source item specified"
        extras = ", ".join(step.added_materials) or "none"
        tools = ", ".join(step.tools) or "none"
        stop = _list_html(step.stop_if, empty="no special stop condition")
        steps.append(
            f"""
<section class='candidate'>
<div class='kicker'>STEP {step.step_number:02d}</div>
<h2>{html.escape(step.title)}</h2>
<p>{html.escape(step.action)}</p>
<p class='muted'>Source matter: {html.escape(sources)}<br>Added: {html.escape(extras)}<br>Tools: {html.escape(tools)}</p>
<p><strong>CHECK:</strong> {html.escape(step.verify)}</p>
<details class='more'><summary>STOP CONDITIONS</summary>{stop}</details>
</section>
"""
        )

    concept_notice = ""
    if concept:
        concept_notice = (
            "<div class='concept'><div class='kicker'>CONCEPT PROTOTYPE / UNVERIFIED</div>"
            "<p class='warning'>This build plan uses measure-to-fit logic where exact facts are missing. It is a prototype path, not engineering or safety certification. Safety-critical unknowns remain gates before powered, wearable, load-bearing, heated, pressurized, food-contact, or other real-world use.</p></div>"
        )

    time_text = f"~{plan.estimated_time_minutes} min" if plan.estimated_time_minutes else "measure during prototype"
    return _page(
        f"""
<div class='kicker'>THE MAKER / POST-PRODUCTION / RFM-INT-0003</div>
<h1>MAKE<br>IT REAL.</h1>
{concept_notice}
{image}
{review_html}
<div class='rule'></div>
<h2>{html.escape(plan.title)}</h2>
<p>{html.escape(plan.result_description)}</p>
<div class='scores'><span>MODE {html.escape(plan.plan_mode.upper())}</span><span>DIFFICULTY {html.escape(plan.difficulty.upper())}</span><span>TIME {html.escape(time_text)}</span></div>
<div class='grid2'>
<div><div class='kicker'>ADDED MATERIALS</div>{_list_html(plan.added_materials)}</div>
<div><div class='kicker'>TOOLS</div>{_list_html(plan.tools)}</div>
</div>
<div class='rule'></div><div class='kicker'>BEFORE YOU START</div>{_list_html(plan.preparation_checks)}
<div class='rule'></div><div class='kicker'>BUILD SEQUENCE</div>{''.join(steps)}
<div class='rule'></div><div class='grid2'>
<div><div class='kicker'>UNRESOLVED BEFORE REAL USE</div>{_list_html(plan.unresolved_before_use)}</div>
<div><div class='kicker'>SAFETY GATES</div>{_list_html(plan.safety_gates)}</div>
</div>
<div class='rule'></div><div class='kicker'>FINAL VERIFICATION</div>{_list_html(plan.final_verification)}
<p>{html.escape(plan.maker_note)}</p>
<div class='rule'></div>
<p><a href='/lab/{html.escape(session.session_id)}/futures'>TRY ANOTHER FUTURE</a></p>
<p><a href='/lab'>START A NEW OBJECT SET</a></p>
"""
    )


@router.post(
    "/lab/{session_id}/render/{candidate_id}",
    response_class=HTMLResponse,
    response_model=None,
    dependencies=[Depends(_require_lab_access)],
)
async def render_and_postproduce(session_id: str, candidate_id: str) -> str:
    session = _get_session(session_id)
    try:
        provider, client = create_higgsfield_provider()
        try:
            session = await render_session_candidate(
                session=session,
                candidate_id=candidate_id,
                provider=provider,
                store=_lab_store(),
                aspect_ratio="4:5",
                max_attempts=3,
            )
        finally:
            await client.aclose()
    except (RenderProviderError, RenderGatewayError, RuntimeError, ValueError) as exc:
        return _page(
            f"<div class='kicker'>RENDER / ERROR</div><h1>STOP.</h1><pre>{html.escape(str(exc))}</pre>"
            f"<p><a href='/lab/{html.escape(session_id)}/futures'>BACK TO FUTURES</a></p>"
        )

    if session.render_result is None or session.render_result.status != "pass":
        return _postproduction_page(session)

    if session.futures is None:
        return _page("<h1>NO FUTURES.</h1><p>Cannot build without an approved future.</p>")
    future = next(
        (
            item
            for item in session.futures.selected_futures
            if item.candidate.candidate_id == candidate_id
        ),
        None,
    )
    if future is None:
        return _page("<h1>FUTURE LOST.</h1><p>The selected future is not present in this session.</p>")

    concept_mode = session.reasoning_mode == "concept" and session.concept_mode_acknowledged
    try:
        plan = await generate_build_plan(
            state=session.project_state,
            future=future,
            concept_mode=concept_mode,
        )
    except BuildMasterError as exc:
        return _page(
            f"<div class='kicker'>BUILD MASTER / ERROR</div><h1>RENDER FOUND.</h1>"
            f"<p>The visualization passed, but post-production could not be generated.</p>"
            f"<pre>{html.escape(str(exc))}</pre>"
            f"<p><a href='/lab/{html.escape(session_id)}/futures'>BACK TO FUTURES</a></p>"
        )

    session = _lab_store().save(
        session.model_copy(update={"stage": "build_plan_ready", "build_plan": plan})
    )
    return _postproduction_page(session)

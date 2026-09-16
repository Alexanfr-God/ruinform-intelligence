from __future__ import annotations

import html
import os
import secrets

from fastapi import APIRouter, Depends, Form, HTTPException, status
from fastapi.responses import HTMLResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials

from .build_master import BuildMasterError, generate_build_plan
from .concept_preview import ConceptPreviewError, generate_concept_preview
from .provider_factory import create_higgsfield_provider
from .render_gateway import RenderGatewayError
from .render_provider import RenderProviderError
from .run_store import SessionNotFound, SqliteRunStore, TransformationSession
from .live_render import render_session_candidate


router = APIRouter(tags=["studio"])
security = HTTPBasic()
_store: SqliteRunStore | None = None


def _require_access(credentials: HTTPBasicCredentials = Depends(security)) -> None:
    expected_user = os.getenv("RUINFORM_LAB_USER", "maker")
    expected_password = os.getenv("RUINFORM_LAB_PASSWORD")
    if not expected_password:
        raise HTTPException(status_code=503, detail="RUINFORM_LAB_PASSWORD is not configured")
    if not (
        secrets.compare_digest(credentials.username, expected_user)
        and secrets.compare_digest(credentials.password, expected_password)
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid studio credentials",
            headers={"WWW-Authenticate": "Basic"},
        )


def _studio_store() -> SqliteRunStore:
    global _store
    if _store is None:
        _store = SqliteRunStore()
    return _store


def _session(session_id: str) -> TransformationSession:
    try:
        return _studio_store().get(session_id)
    except SessionNotFound as exc:
        raise HTTPException(status_code=404, detail="Studio session not found") from exc


def _page(body: str, *, title: str = "RUINFORM STUDIO") -> str:
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"/><meta name="viewport" content="width=device-width,initial-scale=1"/>
<title>{html.escape(title)}</title>
<style>
:root{{color-scheme:dark}}*{{box-sizing:border-box}}body{{margin:0;background:#080807;color:#eee8dd;font-family:ui-monospace,SFMono-Regular,Menlo,monospace}}main{{max-width:1180px;margin:0 auto;padding:46px 22px 100px}}h1{{font-size:clamp(42px,8vw,104px);line-height:.88;letter-spacing:-.065em;margin:0 0 24px}}h2{{font-size:24px}}p{{line-height:1.55}}a{{color:#eee8dd}}.k{{font-size:12px;letter-spacing:.2em;color:#8f887b;margin-bottom:15px}}.muted{{color:#8f887b}}.rule{{border-top:1px solid #302d28;margin:32px 0}}.panel{{border:1px solid #343029;background:#0f0f0d;padding:20px;margin:18px 0}}.grid{{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:16px}}.card{{border:1px solid #3b3730;background:#11110f;padding:18px}}.badge{{display:inline-block;border:1px solid #6f5940;padding:5px 8px;margin:0 8px 8px 0;font-size:11px;letter-spacing:.08em}}.scores{{font-size:12px;color:#aaa296;line-height:1.7}}label{{display:block;margin:16px 0 8px;color:#b9b1a4}}input,textarea,select,button{{width:100%;background:#12110f;color:#eee8dd;border:1px solid #3d3932;padding:13px;font:inherit}}button{{cursor:pointer;background:#e8e0d1;color:#111;border:0;font-weight:700;margin-top:15px}}button.secondary{{background:#171613;color:#eee8dd;border:1px solid #4a443c}}img.hero{{width:100%;display:block;border:1px solid #3d3932;margin:20px 0}}.warning{{color:#d5ad74}}.step{{border-left:2px solid #675540;padding-left:16px;margin:20px 0}}#busy{{display:none;position:fixed;inset:0;background:rgba(5,5,4,.92);z-index:20;align-items:center;justify-content:center;text-align:center;padding:20px}}#busy.on{{display:flex}}#busy h2{{font-size:clamp(28px,5vw,64px);margin:8px 0}}@media(max-width:760px){{.grid{{grid-template-columns:1fr}}}}
</style></head><body><div id="busy"><div><div class="k">RUINFORM / WORKING</div><h2 id="busy-title">FINDING POSSIBLE FUTURES.</h2><p class="muted">This stage is intentionally lightweight. Detailed engineering waits until you approve a visual.</p></div></div><main>{body}</main>
<script>
document.querySelectorAll('form[data-busy]').forEach(function(form){{form.addEventListener('submit',function(){{var b=document.getElementById('busy');var t=document.getElementById('busy-title');if(form.dataset.busyTitle)t.textContent=form.dataset.busyTitle;b.classList.add('on');Array.from(form.querySelectorAll('button')).forEach(function(x){{x.disabled=true}});}});}});
</script></body></html>"""


def _materials_summary(session: TransformationSession) -> str:
    rows = []
    for item in session.project_state.materials:
        rows.append(f"<span class='badge'>{html.escape(item.display_name)}</span>")
    return "".join(rows) or "<span class='muted'>No material labels available</span>"


def _concept_form(session: TransformationSession) -> str:
    return f"""
<div class='k'>RUINFORM / STAGED INTELLIGENCE</div>
<h1>IDEA FIRST.<br>BUILD LATER.</h1>
<p>We now spend intelligence in the order a human actually needs it: first decide whether the idea is worth pursuing, then render it, and only after you approve the visual do we spend tokens on detailed build logic.</p>
<div class='panel'><div class='k'>SOURCE MATTER</div>{_materials_summary(session)}</div>
<form method='post' action='/studio/{html.escape(session.session_id)}/concepts' data-busy data-busy-title='FINDING 4 POSSIBLE FUTURES.'>
<label>CREATIVE MODE</label>
<select name='mode'>
<option value='hybrid'>HYBRID — art + real object</option>
<option value='art'>ART — strongest visual idea</option>
<option value='buildable'>BUILDABLE — simplest physical transformation</option>
<option value='functional'>FUNCTIONAL — useful object first</option>
</select>
<label>WHAT SHOULD IT BECOME? — optional</label>
<textarea name='user_intent' rows='3' placeholder='Leave blank and let THE MAKER explore'></textarea>
<p class='warning'>Concept Preview allows unverified scale-to-fit assumptions. It is inspiration, not engineering or safety approval. Exact verification happens only if you choose MAKE IT REAL.</p>
<button type='submit'>GENERATE 4 CONCEPTS</button>
</form>
<p><a href='/lab/{html.escape(session.session_id)}'>BACK TO EVIDENCE LAB</a></p>
"""


def _concepts_page(session: TransformationSession) -> str:
    if session.futures is None or not session.futures.selected_futures:
        return _concept_form(session)
    cards: list[str] = []
    for future in session.futures.selected_futures:
        c = future.candidate
        r = future.review
        added = ", ".join(c.added_materials) if c.added_materials else "none / minimal additions"
        ops = " · ".join(c.key_operations[:5])
        unresolved = " · ".join(c.unresolved_dependencies[:4]) or "ordinary scale-to-fit assumptions only"
        cards.append(f"""
<div class='card'>
<div class='k'>{html.escape(c.category.upper())} / PREVIEW {future.rank_score:.1f}</div>
<h2>{html.escape(c.name)}</h2>
<p>{html.escape(c.one_line)}</p>
<p><strong>Transformation:</strong> {html.escape(c.transformation_logic)}</p>
<div class='scores'>BUILDABILITY {r.buildability_score} / ORIGINALITY {r.originality_score} / ART {r.artistic_impact_score} / USEFULNESS {r.usefulness_score} / VALUE {r.value_potential_score}</div>
<p><strong>Operations:</strong> {html.escape(ops)}</p>
<p><strong>Possible additions:</strong> {html.escape(added)}</p>
<p class='muted'><strong>Still unverified:</strong> {html.escape(unresolved)}</p>
<form method='post' action='/studio/{html.escape(session.session_id)}/render/{html.escape(c.candidate_id)}' data-busy data-busy-title='RENDERING THE SELECTED FUTURE.'>
<button type='submit'>RENDER THIS CONCEPT</button>
</form>
</div>""")
    return f"""
<div class='k'>CONCEPT ARCHITECT / FAST PREVIEW</div><h1>I SEE 4<br>FUTURES.</h1>
<p>No detailed engineering has been generated yet. Pick the idea first. That is the token-efficient path.</p>
<div class='grid'>{''.join(cards)}</div>
<div class='rule'></div><p><a href='/studio/{html.escape(session.session_id)}'>GENERATE A DIFFERENT SET</a></p>
"""


def _render_page(session: TransformationSession) -> str:
    result = session.render_result
    if result is None:
        return _concepts_page(session)
    image = str(result.accepted_image_url) if result.accepted_image_url else None
    future = None
    if session.futures and session.selected_candidate_id:
        future = next((x for x in session.futures.selected_futures if x.candidate.candidate_id == session.selected_candidate_id), None)
    title = future.candidate.name if future else "Selected future"
    if result.status != "pass" or not image:
        return f"""<div class='k'>VISUAL DIRECTOR / RESULT</div><h1>RENDER<br>NEEDS WORK.</h1><p>{html.escape(result.failure_reason or 'The render did not pass the visual trust gate.')}</p><p><a href='/studio/{html.escape(session.session_id)}/concepts'>BACK TO CONCEPTS</a></p>"""
    return f"""
<div class='k'>VISUAL DIRECTOR / APPROVED IMAGE</div><h1>THIS IS WHAT<br>IT COULD BECOME.</h1>
<h2>{html.escape(title)}</h2><img class='hero' src='{html.escape(image, quote=True)}' alt='RUINFORM generated future'/>
<p class='warning'>This is still a concept visualization. Physical feasibility has not yet been deeply verified.</p>
<form method='post' action='/studio/{html.escape(session.session_id)}/build' data-busy data-busy-title='TURNING THE VISUAL INTO A BUILD PLAN.'><button type='submit'>MAKE IT REAL</button></form>
<form method='get' action='/studio/{html.escape(session.session_id)}/concepts'><button class='secondary' type='submit'>CHOOSE ANOTHER CONCEPT</button></form>
"""


def _build_page(session: TransformationSession) -> str:
    plan = session.build_plan
    if plan is None:
        return _render_page(session)
    additions = "".join(f"<li>{html.escape(x)}</li>" for x in plan.added_materials) or "<li>none declared</li>"
    tools = "".join(f"<li>{html.escape(x)}</li>" for x in plan.tools) or "<li>none declared</li>"
    steps = []
    for step in plan.steps:
        stop = " · ".join(step.stop_if) if step.stop_if else "none"
        steps.append(f"""<div class='step'><div class='k'>STEP {step.step_number}</div><h2>{html.escape(step.title)}</h2><p>{html.escape(step.action)}</p><p><strong>Verify:</strong> {html.escape(step.verify)}</p><p class='muted'><strong>Stop if:</strong> {html.escape(stop)}</p></div>""")
    gates = "".join(f"<li>{html.escape(x)}</li>" for x in plan.safety_gates) or "<li>no additional gate declared</li>"
    unresolved = "".join(f"<li>{html.escape(x)}</li>" for x in plan.unresolved_before_use) or "<li>none declared</li>"
    return f"""
<div class='k'>BUILD MASTER / POST-PRODUCTION</div><h1>MAKE IT<br>REAL.</h1>
<h2>{html.escape(plan.title)}</h2><p>{html.escape(plan.result_description)}</p>
<div class='grid'><div class='panel'><div class='k'>ADDED MATERIALS</div><ul>{additions}</ul></div><div class='panel'><div class='k'>TOOLS</div><ul>{tools}</ul></div></div>
<div class='rule'></div>{''.join(steps)}
<div class='grid'><div class='panel'><div class='k'>SAFETY GATES</div><ul>{gates}</ul></div><div class='panel'><div class='k'>VERIFY BEFORE REAL USE</div><ul>{unresolved}</ul></div></div>
<p class='warning'>{html.escape(plan.maker_note)}</p>
<p><a href='/studio/{html.escape(session.session_id)}/concepts'>BACK TO FUTURES</a></p>
"""


@router.get('/studio/{session_id}', response_class=HTMLResponse, dependencies=[Depends(_require_access)])
async def studio_home(session_id: str) -> str:
    return _page(_concept_form(_session(session_id)))


@router.post('/studio/{session_id}/concepts', response_class=HTMLResponse, dependencies=[Depends(_require_access)])
async def studio_concepts(
    session_id: str,
    mode: str = Form('hybrid'),
    user_intent: str = Form(''),
) -> str:
    session = _session(session_id)
    if mode not in {'art', 'buildable', 'functional', 'hybrid'}:
        mode = 'hybrid'
    try:
        futures = await generate_concept_preview(
            state=session.project_state,
            mode=mode,
            user_intent=user_intent.strip() or None,
        )
    except ConceptPreviewError as exc:
        return _page(f"<div class='k'>CONCEPT ARCHITECT / ERROR</div><h1>STOP.</h1><p>{html.escape(str(exc))}</p><p><a href='/studio/{html.escape(session_id)}'>TRY AGAIN</a></p>")

    session = _studio_store().save(
        session.model_copy(
            update={
                'stage': 'futures_ready',
                'reasoning_mode': 'concept',
                'concept_mode_acknowledged': True,
                'futures': futures,
                'selected_candidate_id': None,
                'render_result': None,
                'build_plan': None,
            }
        )
    )
    return _page(_concepts_page(session), title='RUINFORM / FUTURES')


@router.get('/studio/{session_id}/concepts', response_class=HTMLResponse, dependencies=[Depends(_require_access)])
async def studio_concepts_get(session_id: str) -> str:
    return _page(_concepts_page(_session(session_id)), title='RUINFORM / FUTURES')


@router.post('/studio/{session_id}/render/{candidate_id}', response_class=HTMLResponse, dependencies=[Depends(_require_access)])
async def studio_render(session_id: str, candidate_id: str) -> str:
    session = _session(session_id)
    try:
        provider = create_higgsfield_provider()
        session = await render_session_candidate(
            session=session,
            candidate_id=candidate_id,
            provider=provider,
            store=_studio_store(),
            max_attempts=2,
        )
    except (ValueError, RenderGatewayError, RenderProviderError) as exc:
        return _page(f"<div class='k'>VISUAL DIRECTOR / ERROR</div><h1>STOP.</h1><p>{html.escape(str(exc))}</p><p><a href='/studio/{html.escape(session_id)}/concepts'>BACK TO CONCEPTS</a></p>")
    return _page(_render_page(session), title='RUINFORM / RENDER')


@router.get('/studio/{session_id}/render', response_class=HTMLResponse, dependencies=[Depends(_require_access)])
async def studio_render_get(session_id: str) -> str:
    return _page(_render_page(_session(session_id)), title='RUINFORM / RENDER')


@router.post('/studio/{session_id}/build', response_class=HTMLResponse, dependencies=[Depends(_require_access)])
async def studio_build(session_id: str) -> str:
    session = _session(session_id)
    if session.futures is None or not session.selected_candidate_id:
        raise HTTPException(status_code=400, detail='Select and render a concept before build planning')
    future = next((x for x in session.futures.selected_futures if x.candidate.candidate_id == session.selected_candidate_id), None)
    if future is None:
        raise HTTPException(status_code=400, detail='Selected future is unavailable')
    try:
        plan = await generate_build_plan(
            state=session.project_state,
            future=future,
            concept_mode=True,
        )
    except BuildMasterError as exc:
        return _page(f"<div class='k'>BUILD MASTER / ERROR</div><h1>STOP.</h1><p>{html.escape(str(exc))}</p><p><a href='/studio/{html.escape(session_id)}/render'>BACK TO RENDER</a></p>")
    session = _studio_store().save(session.model_copy(update={'stage': 'build_plan_ready', 'build_plan': plan}))
    return _page(_build_page(session), title='RUINFORM / MAKE IT REAL')


@router.get('/studio/{session_id}/build', response_class=HTMLResponse, dependencies=[Depends(_require_access)])
async def studio_build_get(session_id: str) -> str:
    return _page(_build_page(_session(session_id)), title='RUINFORM / MAKE IT REAL')

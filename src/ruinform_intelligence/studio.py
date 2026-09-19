from __future__ import annotations

import hashlib
import hmac
import html
import os
import secrets
import time
from urllib.parse import quote

from fastapi import APIRouter, Depends, Form, HTTPException, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials

from .build_master import BuildMasterError, generate_build_plan
from .concept_preview import ConceptPreviewError, generate_concept_preview
from .provider_factory import create_higgsfield_provider
from .render_gateway import RenderGatewayError
from .render_provider import RenderProviderError
from .run_store import SessionNotFound, SqliteRunStore, TransformationSession
from .live_render import render_session_candidate


router = APIRouter(tags=["studio"])
security = HTTPBasic(auto_error=False)
_store: SqliteRunStore | None = None
_STUDIO_COOKIE = "ruinform_studio_session"
_STUDIO_COOKIE_TTL = 7 * 24 * 60 * 60
_BACKGROUND_MODES = {"clean_studio", "ruinform_world"}


def _auth_config() -> tuple[str, str]:
    expected_user = os.getenv("RUINFORM_LAB_USER", "maker")
    expected_password = os.getenv("RUINFORM_LAB_PASSWORD")
    if not expected_password:
        raise HTTPException(status_code=503, detail="RUINFORM_LAB_PASSWORD is not configured")
    return expected_user, expected_password


def _cookie_token(username: str, expires: int, password: str) -> str:
    payload = f"{username}:{expires}"
    signature = hmac.new(password.encode("utf-8"), payload.encode("utf-8"), hashlib.sha256).hexdigest()
    return f"{payload}:{signature}"


def _cookie_is_valid(token: str | None, *, username: str, password: str) -> bool:
    if not token:
        return False
    try:
        token_user, expires_raw, signature = token.split(":", 2)
        expires = int(expires_raw)
    except (TypeError, ValueError):
        return False
    if token_user != username or expires < int(time.time()):
        return False
    expected = _cookie_token(token_user, expires, password).rsplit(":", 1)[1]
    return secrets.compare_digest(signature, expected)


def _safe_next(value: str | None) -> str:
    if value and value.startswith("/studio/") and not value.startswith("//"):
        return value
    return "/lab"


def _require_access(
    request: Request,
    credentials: HTTPBasicCredentials | None = Depends(security),
) -> None:
    expected_user, expected_password = _auth_config()
    if _cookie_is_valid(
        request.cookies.get(_STUDIO_COOKIE),
        username=expected_user,
        password=expected_password,
    ):
        return
    if credentials and (
        secrets.compare_digest(credentials.username, expected_user)
        and secrets.compare_digest(credentials.password, expected_password)
    ):
        return
    next_path = quote(request.url.path, safe="/")
    raise HTTPException(
        status_code=status.HTTP_303_SEE_OTHER,
        detail="Studio sign-in required",
        headers={"Location": f"/studio-login?next={next_path}"},
    )


def _login_page(next_path: str, *, error: str | None = None) -> str:
    error_html = f"<p style='color:#d5ad74'>{html.escape(error)}</p>" if error else ""
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"/><meta name="viewport" content="width=device-width,initial-scale=1"/>
<title>RUINFORM STUDIO / SIGN IN</title>
<style>
:root{{color-scheme:dark}}*{{box-sizing:border-box}}body{{margin:0;background:#080807;color:#eee8dd;font-family:ui-monospace,SFMono-Regular,Menlo,monospace}}main{{max-width:620px;margin:0 auto;padding:72px 22px}}h1{{font-size:clamp(42px,9vw,86px);line-height:.9;letter-spacing:-.06em;margin:0 0 24px}}p{{line-height:1.55;color:#a69e92}}.k{{font-size:12px;letter-spacing:.2em;color:#8f887b;margin-bottom:16px}}label{{display:block;margin:18px 0 8px;color:#b9b1a4}}input,button{{width:100%;background:#12110f;color:#eee8dd;border:1px solid #3d3932;padding:14px;font:inherit}}button{{cursor:pointer;background:#e8e0d1;color:#111;border:0;font-weight:700;margin-top:20px}}
</style></head><body><main>
<div class='k'>RUINFORM / PRIVATE STUDIO</div><h1>SIGN IN.</h1>
<p>One sign-in keeps this browser connected to the private Studio for seven days. Your OpenAI, Higgsfield and database secrets remain server-side.</p>
{error_html}
<form method='post' action='/studio-login'>
<input type='hidden' name='next' value='{html.escape(_safe_next(next_path), quote=True)}'/>
<label>LOGIN</label><input name='username' autocomplete='username' required/>
<label>PASSWORD</label><input type='password' name='password' autocomplete='current-password' required/>
<button type='submit'>ENTER RUINFORM STUDIO</button>
</form></main></body></html>"""


@router.get('/studio-login', response_class=HTMLResponse)
async def studio_login(next: str = '/lab') -> str:
    return _login_page(_safe_next(next))


@router.post('/studio-login', response_class=HTMLResponse)
async def studio_login_submit(
    username: str = Form(...),
    password: str = Form(...),
    next: str = Form('/lab'),
):
    expected_user, expected_password = _auth_config()
    if not (
        secrets.compare_digest(username, expected_user)
        and secrets.compare_digest(password, expected_password)
    ):
        return HTMLResponse(_login_page(_safe_next(next), error="Invalid Studio login or password."), status_code=401)
    destination = _safe_next(next)
    expires = int(time.time()) + _STUDIO_COOKIE_TTL
    response = RedirectResponse(url=destination, status_code=status.HTTP_303_SEE_OTHER)
    response.set_cookie(
        _STUDIO_COOKIE,
        _cookie_token(expected_user, expires, expected_password),
        max_age=_STUDIO_COOKIE_TTL,
        httponly=True,
        secure=True,
        samesite='lax',
        path='/',
    )
    return response


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
:root{{color-scheme:dark}}*{{box-sizing:border-box}}body{{margin:0;background:#080807;color:#eee8dd;font-family:ui-monospace,SFMono-Regular,Menlo,monospace}}main{{max-width:1180px;margin:0 auto;padding:46px 22px 100px}}h1{{font-size:clamp(42px,8vw,104px);line-height:.88;letter-spacing:-.065em;margin:0 0 24px}}h2{{font-size:24px}}p{{line-height:1.55}}a{{color:#eee8dd}}.k{{font-size:12px;letter-spacing:.2em;color:#8f887b;margin-bottom:15px}}.muted{{color:#8f887b}}.rule{{border-top:1px solid #302d28;margin:32px 0}}.panel{{border:1px solid #343029;background:#0f0f0d;padding:20px;margin:18px 0}}.grid{{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:16px}}.card{{border:1px solid #3b3730;background:#11110f;padding:18px}}.badge{{display:inline-block;border:1px solid #6f5940;padding:5px 8px;margin:0 8px 8px 0;font-size:11px;letter-spacing:.08em}}.scores{{font-size:12px;color:#aaa296;line-height:1.7}}label{{display:block;margin:16px 0 8px;color:#b9b1a4}}input,textarea,select,button{{width:100%;background:#12110f;color:#eee8dd;border:1px solid #3d3932;padding:13px;font:inherit}}input[type=checkbox]{{width:auto;margin-right:8px}}button{{cursor:pointer;background:#e8e0d1;color:#111;border:0;font-weight:700;margin-top:15px}}button.secondary{{background:#171613;color:#eee8dd;border:1px solid #4a443c}}button:disabled{{opacity:.45;cursor:not-allowed}}img.hero{{width:100%;display:block;border:1px solid #3d3932;margin:20px 0}}.warning{{color:#d5ad74}}.step{{border-left:2px solid #675540;padding-left:16px;margin:20px 0}}.critic-pass{{border-color:#485d48}}.critic-revise{{border-color:#8a6b3e}}.critic-reject{{border-color:#7b4141}}#busy{{display:none;position:fixed;inset:0;background:rgba(5,5,4,.92);z-index:20;align-items:center;justify-content:center;text-align:center;padding:20px}}#busy.on{{display:flex}}#busy h2{{font-size:clamp(28px,5vw,64px);margin:8px 0}}@media(max-width:760px){{.grid{{grid-template-columns:1fr}}}}
</style></head><body><div id="busy"><div><div class="k">RUINFORM / WORKING</div><h2 id="busy-title">FINDING POSSIBLE FUTURES.</h2><p class="muted">This stage is intentionally lightweight. Detailed engineering waits until you approve a visual.</p></div></div><main>{body}</main>
<script>
document.querySelectorAll('form[data-busy]').forEach(function(form){{form.addEventListener('submit',function(){{var b=document.getElementById('busy');var t=document.getElementById('busy-title');if(form.dataset.busyTitle)t.textContent=form.dataset.busyTitle;b.classList.add('on');Array.from(form.querySelectorAll('button')).forEach(function(x){{x.disabled=true}});}});}});
</script></body></html>"""


def _materials_summary(session: TransformationSession) -> str:
    rows = []
    for item in session.project_state.materials:
        rows.append(f"<span class='badge'>{html.escape(item.display_name)}</span>")
    return "".join(rows) or "<span class='muted'>No material labels available</span>"


def _project_controls(session: TransformationSession) -> str:
    intent = session.project_state.creative_intent
    direction = html.escape(intent.direction or "RUINFORM decides")
    return (
        "<div class='panel'><div class='k'>PROJECT CONTROLS</div>"
        f"<span class='badge'>DIFFICULTY: {html.escape(intent.difficulty_mode.upper())}</span>"
        f"<span class='badge'>BACKGROUND: {html.escape(intent.background_mode.upper())}</span>"
        f"<p class='muted'><strong>Creative Direction:</strong> {direction}</p></div>"
    )


def _concept_form(session: TransformationSession) -> str:
    return f"""
<div class='k'>RUINFORM / STAGED INTELLIGENCE</div>
<h1>IDEA FIRST.<br>BUILD LATER.</h1>
<p>We now spend intelligence in the order a human actually needs it: first decide whether the idea is worth pursuing, then render it, and only after you approve the visual do we spend tokens on detailed build logic.</p>
<div class='panel'><div class='k'>SOURCE MATTER</div>{_materials_summary(session)}</div>
{_project_controls(session)}
<form method='post' action='/studio/{html.escape(session.session_id)}/concepts' data-busy data-busy-title='FINDING 4 POSSIBLE FUTURES.'>
<label>CREATIVE MODE</label>
<select name='mode'>
<option value='hybrid'>HYBRID — art + real object</option>
<option value='art'>ART — strongest visual idea</option>
<option value='buildable'>BUILDABLE — simplest physical transformation</option>
<option value='functional'>FUNCTIONAL — useful object first</option>
</select>
<label>SESSION ADJUSTMENT — optional</label>
<textarea name='user_intent' rows='3' placeholder='Leave blank to keep the project Creative Direction. Or add a one-batch adjustment, e.g. keep the cup intact.'></textarea>
<p class='warning'>Concept Preview allows unverified scale-to-fit assumptions. It is inspiration, not engineering or safety approval. Exact verification happens only if you choose MAKE IT REAL.</p>
<button type='submit'>GENERATE 4 CONCEPTS</button>
</form>
<p><a href='/lab/{html.escape(session.session_id)}'>BACK TO EVIDENCE LAB</a></p>
"""


def _background_select(current: str) -> str:
    clean = " selected" if current == "clean_studio" else ""
    world = " selected" if current == "ruinform_world" else ""
    return (
        "<label>BACKGROUND FOR THIS RENDER</label>"
        "<select name='background_mode'>"
        f"<option value='clean_studio'{clean}>CLEAN STUDIO — object first</option>"
        f"<option value='ruinform_world'{world}>RUINFORM WORLD — post-apocalyptic hero setting</option>"
        "</select>"
        "<p class='muted'>You can render the SAME concept in both modes for a true A/B comparison.</p>"
    )


def _critic_tags(required_changes: list[str]) -> list[str]:
    tags: list[str] = []
    for change in required_changes:
        if not change.startswith("[") or "]" not in change:
            continue
        tag = change[1 : change.index("]")].strip()
        if tag and tag not in tags:
            tags.append(tag)
    return tags


def _critic_panel(review) -> str:
    status_label = review.status.upper()
    tags = _critic_tags(list(review.required_changes))
    tag_html = "".join(f"<span class='badge'>{html.escape(tag)}</span>" for tag in tags)
    reason = review.reasons[0] if review.reasons else "No critic summary supplied."
    changes = "".join(f"<li>{html.escape(change)}</li>" for change in review.required_changes)
    changes_html = f"<ul>{changes}</ul>" if changes else "<p class='muted'>No required changes.</p>"
    return (
        f"<div class='panel critic-{html.escape(review.status)}'>"
        f"<div class='k'>PRE-RENDER CRITIC / {html.escape(status_label)}</div>"
        f"{tag_html}"
        f"<p>{html.escape(reason)}</p>"
        f"{changes_html}"
        "</div>"
    )


def _render_form(session: TransformationSession, future, current_background: str) -> str:
    review = future.review
    candidate_id = html.escape(future.candidate.candidate_id)
    session_id = html.escape(session.session_id)
    if review.status == "reject":
        return (
            "<p class='warning'><strong>RENDER BLOCKED.</strong> The pre-render critic rejected this direction. "
            "Change the Creative Direction or generate a different set before spending image tokens.</p>"
        )

    override = ""
    label = "RENDER THIS CONCEPT"
    button_class = ""
    if review.status == "revise":
        label = "RENDER ANYWAY — REVISE FLAGGED"
        button_class = " class='secondary'"
        override = (
            "<label><input type='checkbox' name='critic_override' value='yes' required/>"
            "I understand the critic recommends revision and still want to spend a render on this experiment.</label>"
        )

    return f"""
<form method='post' action='/studio/{session_id}/render/{candidate_id}' data-busy data-busy-title='RENDERING THE SELECTED FUTURE.'>
{_background_select(current_background)}
{override}
<button{button_class} type='submit'>{label}</button>
</form>"""


def _concepts_page(session: TransformationSession) -> str:
    if session.futures is None or not session.futures.selected_futures:
        return _concept_form(session)
    cards: list[str] = []
    current_background = session.project_state.creative_intent.background_mode
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
<div class='scores'>FEASIBILITY {r.feasibility_score} / MATERIAL FIT {r.material_fit_score} / BUILDABILITY {r.buildability_score} / ORIGINALITY {r.originality_score} / ART {r.artistic_impact_score} / USEFULNESS {r.usefulness_score} / VALUE {r.value_potential_score}</div>
{_critic_panel(r)}
<p><strong>Operations:</strong> {html.escape(ops)}</p>
<p><strong>Possible additions:</strong> {html.escape(added)}</p>
<p class='muted'><strong>Still unverified:</strong> {html.escape(unresolved)}</p>
{_render_form(session, future, current_background)}
</div>""")
    return f"""
<div class='k'>CONCEPT ARCHITECT / FAST PREVIEW</div><h1>I SEE 4<br>FUTURES.</h1>
<p>No detailed engineering has been generated yet. Pick the idea first. That is the token-efficient path.</p>
{_project_controls(session)}
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
    background_label = session.project_state.creative_intent.background_mode.replace('_', ' ').upper()
    return f"""
<div class='k'>VISUAL DIRECTOR / APPROVED IMAGE / {html.escape(background_label)}</div><h1>THIS IS WHAT<br>IT COULD BECOME.</h1>
<h2>{html.escape(title)}</h2><img class='hero' src='{html.escape(image, quote=True)}' alt='RUINFORM generated future'/>
<p class='warning'>This is still a concept visualization. Physical feasibility has not yet been deeply verified.</p>
<form method='post' action='/studio/{html.escape(session.session_id)}/build' data-busy data-busy-title='TURNING THE VISUAL INTO A BUILD PLAN.'><button type='submit'>MAKE IT REAL</button></form>
<form method='get' action='/studio/{html.escape(session.session_id)}/concepts'><button class='secondary' type='submit'>BACK TO CONCEPTS / TRY OTHER BACKGROUND</button></form>
"""


def _build_page(session: TransformationSession) -> str:
    plan = session.build_plan
    if plan is None:
        return _render_page(session)
    image = None
    if session.render_result and session.render_result.accepted_image_url:
        image = str(session.render_result.accepted_image_url)
    visual = (
        f"<div class='panel'><div class='k'>APPROVED VISUAL / BUILD TARGET</div>"
        f"<img class='hero' src='{html.escape(image, quote=True)}' alt='Approved RUINFORM build target'/></div>"
        if image
        else ""
    )
    additions = "".join(f"<li>{html.escape(x)}</li>" for x in plan.added_materials) or "<li>none declared</li>"
    tools = "".join(f"<li>{html.escape(x)}</li>" for x in plan.tools) or "<li>none declared</li>"
    preparation = "".join(f"<li>{html.escape(x)}</li>" for x in plan.preparation_checks) or "<li>none declared</li>"
    final_checks = "".join(f"<li>{html.escape(x)}</li>" for x in plan.final_verification) or "<li>none declared</li>"
    steps = []
    for step in plan.steps:
        stop = " · ".join(step.stop_if) if step.stop_if else "none"
        steps.append(f"""<div class='step'><div class='k'>STEP {step.step_number}</div><h2>{html.escape(step.title)}</h2><p>{html.escape(step.action)}</p><p><strong>Verify:</strong> {html.escape(step.verify)}</p><p class='muted'><strong>Stop if:</strong> {html.escape(stop)}</p></div>""")
    gates = "".join(f"<li>{html.escape(x)}</li>" for x in plan.safety_gates) or "<li>no additional gate declared</li>"
    unresolved = "".join(f"<li>{html.escape(x)}</li>" for x in plan.unresolved_before_use) or "<li>none declared</li>"
    return f"""
<div class='k'>BUILD MASTER / POST-PRODUCTION</div><h1>MAKE IT<br>REAL.</h1>
<h2>{html.escape(plan.title)}</h2><p>{html.escape(plan.result_description)}</p>
{visual}
<div class='grid'><div class='panel'><div class='k'>SHOPPING / ADDED MATERIALS</div><ul>{additions}</ul></div><div class='panel'><div class='k'>TOOLS</div><ul>{tools}</ul></div></div>
<div class='panel'><div class='k'>PREFLIGHT / PREPARATION CHECKS</div><ul>{preparation}</ul></div>
<div class='rule'></div>{''.join(steps)}
<div class='grid'><div class='panel'><div class='k'>SAFETY GATES</div><ul>{gates}</ul></div><div class='panel'><div class='k'>VERIFY BEFORE REAL USE</div><ul>{unresolved}</ul></div></div>
<div class='panel'><div class='k'>FINAL VERIFICATION / MATCH THE APPROVED VISUAL</div><ul>{final_checks}</ul></div>
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
async def studio_render(
    session_id: str,
    candidate_id: str,
    background_mode: str = Form(''),
    critic_override: str = Form(''),
) -> str:
    session = _session(session_id)
    future = None
    if session.futures:
        future = next((x for x in session.futures.selected_futures if x.candidate.candidate_id == candidate_id), None)
    if future is None:
        raise HTTPException(status_code=404, detail='Concept is unavailable')
    if future.review.status == 'reject':
        return _page(
            f"<div class='k'>PRE-RENDER CRITIC / REJECT</div><h1>RENDER BLOCKED.</h1>"
            f"<p>This direction failed the pre-render gate, so RUINFORM did not spend image tokens.</p>"
            f"<p><a href='/studio/{html.escape(session_id)}/concepts'>BACK TO CONCEPTS</a></p>",
            title='RUINFORM / RENDER BLOCKED',
        )
    if future.review.status == 'revise' and critic_override != 'yes':
        raise HTTPException(status_code=409, detail='Critic revision acknowledgement required before render')

    if background_mode in _BACKGROUND_MODES and background_mode != session.project_state.creative_intent.background_mode:
        creative_intent = session.project_state.creative_intent.model_copy(
            update={'background_mode': background_mode}
        )
        project_state = session.project_state.model_copy(
            update={'creative_intent': creative_intent}
        )
        session = _studio_store().save(
            session.model_copy(update={'project_state': project_state, 'render_result': None})
        )
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
    if (
        session.render_result is None
        or session.render_result.status != 'pass'
        or session.render_result.accepted_image_url is None
    ):
        raise HTTPException(status_code=400, detail='MAKE IT REAL requires an approved render image')
    if session.render_result.candidate_id != session.selected_candidate_id:
        raise HTTPException(status_code=409, detail='Approved render does not match the selected future')
    future = next((x for x in session.futures.selected_futures if x.candidate.candidate_id == session.selected_candidate_id), None)
    if future is None:
        raise HTTPException(status_code=400, detail='Selected future is unavailable')
    try:
        plan = await generate_build_plan(
            state=session.project_state,
            future=future,
            accepted_image_url=str(session.render_result.accepted_image_url),
            concept_mode=True,
        )
    except BuildMasterError as exc:
        return _page(f"<div class='k'>BUILD MASTER / ERROR</div><h1>STOP.</h1><p>{html.escape(str(exc))}</p><p><a href='/studio/{html.escape(session_id)}/render'>BACK TO RENDER</a></p>")
    session = _studio_store().save(session.model_copy(update={'stage': 'build_plan_ready', 'build_plan': plan}))
    return _page(_build_page(session), title='RUINFORM / MAKE IT REAL')


@router.get('/studio/{session_id}/build', response_class=HTMLResponse, dependencies=[Depends(_require_access)])
async def studio_build_get(session_id: str) -> str:
    return _page(_build_page(_session(session_id)), title='RUINFORM / MAKE IT REAL')

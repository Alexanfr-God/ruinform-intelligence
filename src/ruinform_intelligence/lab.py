from __future__ import annotations

import base64
import html
import os
import secrets

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile, status
from fastapi.responses import HTMLResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials

from .evidence_gate import can_advance_to_ideation
from .evidence_loop import continue_evidence_loop
from .future_models import FuturePreferences
from .lab_dialogue import compose_answer_statement, parse_measurements, suggested_choices
from .live_futures import discover_session_futures
from .live_render import render_session_candidate
from .material_eye import MaterialEyeError, analyze_evidence
from .models import EvidenceItem, ProjectConstraints, Unknown
from .provider_factory import create_higgsfield_provider
from .render_gateway import RenderGatewayError
from .render_provider import RenderProviderError
from .run_store import SessionNotFound, SqliteRunStore, TransformationSession

router = APIRouter(tags=["lab"])
security = HTTPBasic()

_ALLOWED_TYPES = {"image/jpeg", "image/png", "image/webp"}
_MAX_FILES = 8
_MAX_FOLLOWUP_FILES = 4
_MAX_FILE_BYTES = 8 * 1024 * 1024
_MAX_PRIMARY_QUESTIONS = 5
_CONCEPT_NOTICE_VERSION = "2026-09-15-v1"
_store: SqliteRunStore | None = None


def _require_lab_access(credentials: HTTPBasicCredentials = Depends(security)) -> None:
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
            detail="Invalid lab credentials",
            headers={"WWW-Authenticate": "Basic"},
        )


def _lab_store() -> SqliteRunStore:
    global _store
    if _store is None:
        _store = SqliteRunStore()
    return _store


def _get_session(session_id: str) -> TransformationSession:
    try:
        return _lab_store().get(session_id)
    except SessionNotFound as exc:
        raise HTTPException(status_code=404, detail="Lab session not found") from exc


def _page(body: str) -> str:
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width,initial-scale=1" />
<title>RUINFORM LAB</title>
<style>
:root{{color-scheme:dark}}*{{box-sizing:border-box}}body{{margin:0;background:#0a0a09;color:#e9e3d8;font-family:ui-monospace,SFMono-Regular,Menlo,monospace}}main{{max-width:1040px;margin:0 auto;padding:48px 22px 90px}}h1{{font-size:clamp(38px,8vw,92px);line-height:.9;letter-spacing:-.06em;margin:0 0 18px}}h2{{font-size:22px;margin:0 0 12px}}p{{line-height:1.55}}.kicker{{letter-spacing:.18em;font-size:12px;color:#9d9689;margin-bottom:18px}}.rule{{border-top:1px solid #38342e;margin:28px 0}}label{{display:block;margin:16px 0 8px;color:#b9b1a4}}input,textarea,select,button{{width:100%;background:#11110f;color:#eee7db;border:1px solid #3b3730;padding:13px;font:inherit}}button{{cursor:pointer;margin-top:18px;background:#e8e0d1;color:#111;border:0;font-weight:700}}button.secondary{{background:#1a1916;color:#e8e0d1;border:1px solid #514b42}}pre{{white-space:pre-wrap;overflow-wrap:anywhere;background:#11110f;border:1px solid #302d28;padding:18px;line-height:1.5}}.material,.candidate{{padding:18px 0;border-top:1px solid #302d28}}.fact{{color:#d9d2c4;margin:5px 0}}.unknown{{color:#c9a26b;margin:5px 0}}.muted{{color:#817b70}}.question{{border:1px solid #302d28;background:#0f0f0d;padding:16px;margin:12px 0}}.q{{color:#e3c28f;margin-bottom:8px}}.grid2{{display:grid;grid-template-columns:1fr 1fr;gap:12px}}.scores{{display:flex;gap:14px;flex-wrap:wrap;color:#a7a093;font-size:13px}}img.result{{max-width:100%;display:block;margin:22px 0;border:1px solid #38342e}}a{{color:#d9d2c4}}code{{color:#e3c28f}}.concept{{border:1px solid #8f6d3f;background:#16120d;padding:20px;margin:24px 0}}.warning{{color:#e1bd85}}.badge{{display:inline-block;border:1px solid #6f5940;padding:5px 8px;margin:0 8px 8px 0;font-size:12px;letter-spacing:.08em}}details.more{{border:1px solid #302d28;padding:14px;margin:16px 0}}.ledger{{border-left:2px solid #3c3933;padding-left:14px;margin:12px 0}}@media(max-width:700px){{.grid2{{grid-template-columns:1fr}}}}
</style>
</head><body><main>{body}</main>
<script>
(function(){{
  function restore(form){{
    var key=form.dataset.persistKey;if(!key)return;
    var raw=localStorage.getItem('ruinform:'+key);if(!raw)return;
    try{{var data=JSON.parse(raw);Array.from(form.elements).forEach(function(el){{
      if(!el.name||el.type==='file'||el.type==='password'||!(el.name in data))return;
      if(el.type==='checkbox'||el.type==='radio')el.checked=Boolean(data[el.name]);else el.value=data[el.name];
    }});}}catch(e){{}}
  }}
  function save(form){{
    var key=form.dataset.persistKey;if(!key)return;
    var data={{}};Array.from(form.elements).forEach(function(el){{
      if(!el.name||el.type==='file'||el.type==='password')return;
      data[el.name]=(el.type==='checkbox'||el.type==='radio')?el.checked:el.value;
    }});localStorage.setItem('ruinform:'+key,JSON.stringify(data));
  }}
  document.querySelectorAll('form[data-persist-key]').forEach(function(form){{
    restore(form);form.addEventListener('input',function(){{save(form)}});form.addEventListener('change',function(){{save(form)}});
  }});
}})();
</script>
</body></html>"""


def _error_page(title: str, exc: Exception, back_href: str = "/lab") -> HTMLResponse:
    return HTMLResponse(
        _page(
            f"<div class='kicker'>{html.escape(title)} / ERROR</div>"
            f"<h1>STOP.</h1><pre>{html.escape(str(exc))}</pre>"
            f"<p><a href='{html.escape(back_href, quote=True)}'>GO BACK</a></p>"
        ),
        status_code=502,
    )


async def _upload_to_data_url(upload: UploadFile, *, index: int) -> str:
    media_type = upload.content_type or ""
    if media_type not in _ALLOWED_TYPES:
        raise ValueError(f"Unsupported image type: {media_type or 'unknown'}")
    raw = await upload.read(_MAX_FILE_BYTES + 1)
    if len(raw) > _MAX_FILE_BYTES:
        raise ValueError(f"Image {index} exceeds 8 MB")
    return f"data:{media_type};base64,{base64.b64encode(raw).decode('ascii')}"


def _materials_html(session: TransformationSession) -> str:
    sections: list[str] = []
    for material in session.project_state.materials:
        observations = "".join(
            f"<div class='fact'>{html.escape(obs.claim_kind.value.upper())} / {html.escape(obs.property_key or 'property')} / "
            f"{html.escape(obs.label)} / confidence={obs.confidence if obs.confidence is not None else 'n/a'}</div>"
            for obs in material.observations
        )
        unknowns = "".join(
            f"<div class='unknown'>UNKNOWN / {html.escape(item.property_key or 'property')} — {html.escape(item.question)}</div>"
            for item in material.unknowns
        )
        sections.append(
            f"<section class='material'><strong>{html.escape(material.display_name)}</strong>{observations}{unknowns}</section>"
        )
    return "".join(sections)


def _recent_evidence_html(session: TransformationSession) -> str:
    visible = [item for item in session.project_state.evidence if item.source_type != "image"][-10:]
    if not visible:
        return ""
    lines: list[str] = []
    for item in visible:
        if item.source_type == "measurement":
            value = f"{item.value} {item.unit or ''}".strip()
            label = f"{item.property_key or 'measurement'} = {value}"
        else:
            label = item.text or str(item.value or "")
        lines.append(f"<div class='ledger'><span class='badge'>{html.escape(item.source_type.upper())}</span>{html.escape(label)}</div>")
    return (
        "<div class='rule'></div><div class='kicker'>SAVED EVIDENCE</div>"
        "<p class='muted'>Submitted answers are already stored in the project ledger. You do not need to type them again.</p>"
        + "".join(lines)
    )


def _question_html(material_name: str, unknown: Unknown, field_index: str) -> str:
    options = ["<option value=''>choose or type your own answer</option>"]
    for choice in suggested_choices(unknown.property_key or ""):
        safe = html.escape(choice, quote=True)
        options.append(f"<option value='{safe}'>{html.escape(choice)}</option>")
    preferred = ", ".join(unknown.preferred_evidence) if unknown.preferred_evidence else "any direct evidence"
    return f"""
<div class="question">
<div class="kicker">{html.escape(material_name)} / {html.escape(unknown.property_key or 'property')} / {html.escape(unknown.consequence_if_unresolved.upper())}</div>
<div class="q">{html.escape(unknown.question)}</div>
<div class="muted">Why it matters: {html.escape(unknown.reason)}<br>Preferred evidence: {html.escape(preferred)}</div>
<div class="grid2">
<div><label>QUICK ANSWER</label><select name="choice_{field_index}">{''.join(options)}</select></div>
<div><label>YOUR EXACT ANSWER</label><input name="answer_{field_index}" placeholder="Write only what you actually know" /></div>
</div></div>
"""


def _concept_mode_block(session: TransformationSession) -> str:
    return f"""
<div class="concept">
<div class="kicker">FAST PATH / CONCEPT MODE</div>
<h2>NO EXACT DIMENSIONS? LET THE AI EXPLORE.</h2>
<p>You can skip the remaining evidence questions and let THE MAKER create exploratory future forms from the photographs, the facts already collected, and clearly marked assumptions.</p>
<p class="warning"><strong>Important:</strong> Concept Mode is for ideation and visualization only. It does not verify exact dimensions, material composition, structural integrity, load capacity, electrical compatibility, heat/flame behavior, pressure resistance, food-contact suitability, regulatory compliance, or manufacturability. Outputs are not engineering, safety, certification, legal, or compliance advice. Before fabrication, sale, installation, powering, wearing, heating, loading, or other real-world use, independently verify the relevant dimensions, materials, safety requirements, and applicable rules. This notice clarifies the limits of the output; it is not a guarantee that all legal liability is waived.</p>
<form method="post" action="/lab/{html.escape(session.session_id)}/concept-mode" data-persist-key="concept-{html.escape(session.session_id)}-{len(session.project_state.evidence)}">
<label><input style="width:auto" type="checkbox" name="concept_ack" required /> I UNDERSTAND THAT THE RESULT WILL CONTAIN UNVERIFIED AI ASSUMPTIONS.</label>
<label>WHAT DO YOU WANT THIS MATTER TO BECOME? — optional</label>
<textarea name="user_intent" rows="3" placeholder="Leave blank for open exploration"></textarea>
<label>PRIORITY</label>
<select name="priority"><option value="balanced">balanced</option><option value="originality">most original</option><option value="value">highest value potential</option><option value="usefulness">most useful</option><option value="ease">easiest to build concept</option><option value="artistic_impact">strongest artistic impact</option></select>
<label><input style="width:auto" type="checkbox" name="only_owned" /> ONLY USE MATERIALS I ALREADY OWN</label>
<button type="submit">CONTINUE IN CONCEPT MODE → FIND FUTURES</button>
</form>
</div>
"""


def _evidence_form(session: TransformationSession) -> str:
    ranked: list[tuple[int, str, Unknown]] = []
    order = {"high": 0, "medium": 1, "low": 2}
    for material in session.project_state.materials:
        for unknown in material.unknowns:
            ranked.append((order.get(unknown.consequence_if_unresolved, 2), material.display_name, unknown))
    ranked.sort(key=lambda item: item[0])

    primary = ranked[:_MAX_PRIMARY_QUESTIONS]
    optional = ranked[_MAX_PRIMARY_QUESTIONS:]
    primary_html = "".join(
        _question_html(material_name, unknown, f"p_{idx}")
        for idx, (_, material_name, unknown) in enumerate(primary)
    )
    optional_html = "".join(
        _question_html(material_name, unknown, f"o_{idx}")
        for idx, (_, material_name, unknown) in enumerate(optional)
    )
    optional_block = (
        f"<details class='more'><summary>SHOW {len(optional)} MORE QUESTIONS — optional for now</summary>{optional_html}</details>"
        if optional
        else ""
    )
    draft_key = f"evidence-{session.session_id}-{len(session.project_state.evidence)}-{len(ranked)}"

    return f"""
<div class="rule"></div>
<div class="kicker">THE MAKER / EVIDENCE DIALOGUE</div>
<h2>ANSWER ONLY WHAT IS EASY TO KNOW.</h2>
<p>We show at most {_MAX_PRIMARY_QUESTIONS} questions first. Your previously submitted answers are already saved. If you do not know the exact dimensions or technical specifications, use Concept Mode below instead of guessing.</p>
<form method="post" action="/lab/{html.escape(session.session_id)}/evidence" enctype="multipart/form-data" data-persist-key="{html.escape(draft_key)}">
{primary_html}
{optional_block}
<label>MEASUREMENTS — one per line</label>
<textarea name="measurements" rows="5" placeholder="bottle_height = 31 cm&#10;bottle_neck_diameter = 28 mm&#10;led_voltage = 12 V"></textarea>
<div class="muted">Format: property = number unit. These become structured measurement evidence.</div>
<label>ADDITIONAL DESCRIPTION / CORRECTIONS</label>
<textarea name="notes" rows="4" placeholder="The bottle is definitely glass. The LED strip came from a 12 V supply. Jacket zipper works normally."></textarea>
<label>ADDITIONAL PHOTOGRAPHS — optional, up to {_MAX_FOLLOWUP_FILES}</label>
<input type="file" name="images" accept="image/jpeg,image/png,image/webp" multiple />
<button type="submit">SUBMIT EVIDENCE → RE-READ MATTER</button>
</form>
{_concept_mode_block(session)}
"""


def _future_form(session: TransformationSession) -> str:
    concept = session.reasoning_mode == "concept" and session.concept_mode_acknowledged
    if concept:
        intro = (
            "<div class='concept'><div class='kicker'>CONCEPT MODE / ACTIVE</div>"
            "<h2>UNVERIFIED ASSUMPTIONS ARE ALLOWED FOR IDEATION.</h2>"
            "<p class='warning'>Future forms and scores below remain exploratory until missing physical facts are independently verified.</p></div>"
        )
    else:
        intro = (
            "<div class='kicker'>EVIDENCE GATE / OPEN</div><h2>I HAVE ENOUGH EVIDENCE.</h2>"
            "<p>The physical state is sufficiently grounded to let Form Architect create possibilities and Feasibility Critic reject impossible ones.</p>"
        )
    return f"""
<div class="rule"></div>{intro}
<form method="post" action="/lab/{html.escape(session.session_id)}/futures" data-persist-key="futures-{html.escape(session.session_id)}-{session.reasoning_mode}">
<label>WHAT DO YOU WANT THIS MATTER TO BECOME? — optional</label>
<textarea name="user_intent" rows="4" placeholder="Open exploration, or: something useful for a desk, not furniture."></textarea>
<label>PRIORITY</label>
<select name="priority"><option value="balanced">balanced</option><option value="originality">most original</option><option value="value">highest value potential</option><option value="usefulness">most useful</option><option value="ease">easiest to build</option><option value="artistic_impact">strongest artistic impact</option></select>
<label><input style="width:auto" type="checkbox" name="only_owned" /> ONLY USE MATERIALS I ALREADY OWN</label>
<label>AVOID CATEGORIES — optional, comma separated</label>
<input name="avoid_categories" placeholder="furniture, wearable" />
<button type="submit">FIND FUTURE FORMS</button>
</form>
"""


def _state_page(session: TransformationSession, summary: str) -> str:
    verified_ready = can_advance_to_ideation(session.project_state)
    concept_ready = session.reasoning_mode == "concept" and session.concept_mode_acknowledged
    ready = verified_ready or concept_ready
    if verified_ready:
        gate = "OPEN — READY FOR FUTURES"
    elif concept_ready:
        gate = "CONCEPT MODE — READY FOR FUTURES"
    else:
        gate = "BLOCKED — MORE EVIDENCE REQUIRED"
    next_request = html.escape(session.project_state.next_user_request or "No additional evidence requested.")
    next_action = _future_form(session) if ready else _evidence_form(session)
    return _page(
        f"""
<div class="kicker">RUINFORM INTELLIGENCE / LIVE LAB / RFM-INT-0002.5</div>
<h1>{html.escape(gate)}</h1>
<p>{html.escape(summary)}</p>
<div class="rule"></div>{_materials_html(session)}
{_recent_evidence_html(session)}
<div class="rule"></div><div class="kicker">NEXT REQUEST</div><p>{next_request}</p>
{next_action}
<div class="rule"></div>
<details><summary>PROJECT STATE / JSON</summary><pre>{html.escape(session.project_state.model_dump_json(indent=2))}</pre></details>
<p><a href="/lab">START A NEW OBJECT SET</a></p>
"""
    )


def _preferences_from_form(form: object, *, concept_mode: bool = False) -> FuturePreferences:
    get = getattr(form, "get")
    priority = str(get("priority") or "balanced")
    weights = {"originality": 1.0, "artistic_impact": 1.0, "usefulness": 1.0, "ease": 1.0, "value": 1.0}
    if priority in weights:
        weights[priority] = 2.5
    avoid = [part.strip() for part in str(get("avoid_categories") or "").split(",") if part.strip()]
    return FuturePreferences(
        **weights,
        only_use_owned_materials=bool(get("only_owned")),
        avoid_categories=avoid,
        concept_mode=concept_mode,
    )


def _concept_unknowns_html(session: TransformationSession) -> str:
    items: list[str] = []
    for material in session.project_state.materials:
        for unknown in material.unknowns:
            items.append(f"<li>{html.escape(material.display_name)} / {html.escape(unknown.property_key or 'property')}</li>")
    if not items:
        return ""
    return "<details class='more'><summary>UNVERIFIED PROPERTIES USED AS CONCEPT CONSTRAINTS</summary><ul>" + "".join(items) + "</ul></details>"


def _futures_page(session: TransformationSession) -> str:
    if session.futures is None:
        return _page("<h1>NO FUTURES.</h1><p>The session contains no future-form result.</p>")
    concept = session.reasoning_mode == "concept" and session.concept_mode_acknowledged
    cards: list[str] = []
    for future in session.futures.selected_futures:
        candidate = future.candidate
        review = future.review
        unresolved = " · ".join(candidate.unresolved_dependencies) or "none declared"
        cards.append(
            f"""
<section class="candidate">
<div class="kicker">{html.escape(candidate.category.upper())} / RANK {future.rank_score:.1f}</div>
<h2>{html.escape(candidate.name)}</h2><p>{html.escape(candidate.one_line)}</p><p>{html.escape(candidate.artistic_thesis)}</p>
<div class="scores"><span>{'CONCEPT FEASIBILITY' if concept else 'FEASIBILITY'} {review.feasibility_score}</span><span>MATERIAL FIT {review.material_fit_score}</span><span>BUILDABILITY {review.buildability_score}</span><span>ORIGINALITY {review.originality_score}</span><span>VALUE {review.value_potential_score}</span></div>
<p class="muted">Added materials: {html.escape(', '.join(candidate.added_materials) or 'none')}<br>Tools: {html.escape(', '.join(candidate.required_tools) or 'none declared')}<br>Operations: {html.escape(' · '.join(candidate.key_operations) or 'none declared')}<br>Unresolved before real build: {html.escape(unresolved)}</p>
<form method="post" action="/lab/{html.escape(session.session_id)}/render/{html.escape(candidate.candidate_id)}"><button type="submit">RENDER THIS FUTURE</button></form>
</section>
"""
        )
    if not cards:
        cards.append(f"<p>{html.escape(session.futures.regeneration_reason or 'No candidate passed the trust gate.')}</p>")
    mode_notice = ""
    if concept:
        mode_notice = (
            "<div class='concept'><div class='kicker'>CONCEPT MODE / UNVERIFIED</div>"
            "<p class='warning'><strong>These are exploratory AI concepts.</strong> A critic PASS means suitable for concept visualization, not approved for fabrication or use. Verify the unresolved properties before building.</p>"
            + _concept_unknowns_html(session)
            + "</div>"
        )
    return _page(
        f"""
<div class="kicker">FORM ARCHITECT + FEASIBILITY CRITIC / LIVE RESULT</div>
<h1>I SEE<br>{len(session.futures.selected_futures)} FUTURES.</h1>
{mode_notice}
<p class="muted">Generated internally: {session.futures.internal_candidate_count} / Reviewed: {session.futures.reviewed_candidate_count} / Revisions: {session.futures.revision_attempt_count}</p>
{''.join(cards)}<div class="rule"></div><p><a href="/lab/{html.escape(session.session_id)}">BACK TO PROJECT STATE</a></p>
"""
    )


def _render_result_page(session: TransformationSession) -> str:
    result = session.render_result
    if result is None:
        return _page("<h1>NO RENDER.</h1><p>The session contains no render result.</p>")
    concept = session.reasoning_mode == "concept" and session.concept_mode_acknowledged
    image = ""
    if result.accepted_image_url:
        image = f"<img class='result' src='{html.escape(str(result.accepted_image_url), quote=True)}' alt='RUINFORM generated future form' />"
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
    heading = "FORM FOUND." if result.status == "pass" else "RENDER REJECTED."
    concept_notice = (
        "<div class='concept'><div class='kicker'>CONCEPT IMAGE / NOT BUILD PROOF</div>"
        "<p class='warning'>This visualization contains unverified assumptions. Do not treat visible proportions, joints, electrical routing, material behavior, or structural details as verified fabrication instructions.</p></div>"
        if concept
        else ""
    )
    return _page(
        f"""
<div class="kicker">RENDER GATE / {html.escape(result.status.upper())}</div><h1>{heading}</h1>
{concept_notice}{image}{review_html}{failure}
<p class="muted">Attempts: {len(result.attempts)}. A beautiful image is accepted only after the Render Critic checks it against source matter and the approved visual brief.</p>
<div class="rule"></div><p><a href="/lab/{html.escape(session.session_id)}/futures">BACK TO FUTURES</a></p><p><a href="/lab">START A NEW OBJECT SET</a></p>
"""
    )


@router.get("/lab", response_class=HTMLResponse, response_model=None, dependencies=[Depends(_require_lab_access)])
async def lab_home() -> str:
    body = f"""
<div class="kicker">RUINFORM INTELLIGENCE / LIVE LAB / RFM-INT-0002.5</div><h1>READ<br>MATTER.</h1>
<p>Upload 1–8 real photographs. Material Eye will separate facts, hypotheses and unknowns. You can either continue gathering evidence or switch to Concept Mode when exact measurements are unavailable.</p>
<div class="rule"></div><p class="muted">OPENAI: {'CONFIGURED' if os.getenv('OPENAI_API_KEY') else 'MISSING'} &nbsp; / &nbsp; HIGGSFIELD: {'CONFIGURED' if os.getenv('HIGGSFIELD_AUTHORIZATION') else 'MISSING'}</p>
<form method="post" action="/lab/analyze" enctype="multipart/form-data"><label>PHOTOGRAPHS</label><input type="file" name="images" accept="image/jpeg,image/png,image/webp" multiple required /><label>CONTEXT — optional</label><textarea name="user_context" rows="4" placeholder="What are these objects? Where did they come from? What tools do you have?"></textarea><button type="submit">READ MATTER</button></form>
"""
    return _page(body)


@router.post("/lab/analyze", response_class=HTMLResponse, response_model=None, dependencies=[Depends(_require_lab_access)])
async def lab_analyze(images: list[UploadFile] = File(...), user_context: str = Form(default="")) -> str:
    if not 1 <= len(images) <= _MAX_FILES:
        raise HTTPException(status_code=400, detail=f"Upload between 1 and {_MAX_FILES} images")
    evidence: list[EvidenceItem] = []
    try:
        for index, image in enumerate(images, start=1):
            evidence.append(
                EvidenceItem(
                    evidence_id=f"image_{index:03d}",
                    source_type="image",
                    uri=await _upload_to_data_url(image, index=index),
                )
            )
        state, summary = await analyze_evidence(
            evidence=evidence,
            user_context=user_context.strip() or None,
            constraints=ProjectConstraints(),
        )
    except (MaterialEyeError, ValueError) as exc:
        return _error_page("MATERIAL EYE", exc)

    stage = "ready_for_futures" if can_advance_to_ideation(state) else "evidence_required"
    session = _lab_store().save(TransformationSession(project_id=state.project_id, stage=stage, project_state=state))
    return _state_page(session, summary)


@router.get("/lab/{session_id}", response_class=HTMLResponse, response_model=None, dependencies=[Depends(_require_lab_access)])
async def lab_session(session_id: str) -> str:
    return _state_page(_get_session(session_id), "Saved project state. Submitted evidence is retained in the ledger; continue only with what remains unresolved.")


@router.post("/lab/{session_id}/evidence", response_class=HTMLResponse, response_model=None, dependencies=[Depends(_require_lab_access)])
async def lab_continue_evidence(session_id: str, request: Request) -> str:
    session = _get_session(session_id)
    form = await request.form()
    statements: list[str] = []

    ranked: list[tuple[int, str, Unknown]] = []
    order = {"high": 0, "medium": 1, "low": 2}
    for material in session.project_state.materials:
        for unknown in material.unknowns:
            ranked.append((order.get(unknown.consequence_if_unresolved, 2), material.display_name, unknown))
    ranked.sort(key=lambda item: item[0])
    primary = ranked[:_MAX_PRIMARY_QUESTIONS]
    optional = ranked[_MAX_PRIMARY_QUESTIONS:]

    for idx, (_, material_name, unknown) in enumerate(primary):
        statement = compose_answer_statement(
            material_name=material_name,
            property_key=unknown.property_key or "property",
            choice=str(form.get(f"choice_p_{idx}") or ""),
            custom_answer=str(form.get(f"answer_p_{idx}") or ""),
        )
        if statement:
            statements.append(statement)
    for idx, (_, material_name, unknown) in enumerate(optional):
        statement = compose_answer_statement(
            material_name=material_name,
            property_key=unknown.property_key or "property",
            choice=str(form.get(f"choice_o_{idx}") or ""),
            custom_answer=str(form.get(f"answer_o_{idx}") or ""),
        )
        if statement:
            statements.append(statement)

    notes = str(form.get("notes") or "").strip()
    if notes:
        statements.append(notes)

    measurements, rejected = parse_measurements(str(form.get("measurements") or ""))
    if rejected:
        return HTMLResponse(
            _page(
                "<div class='kicker'>MEASUREMENT INPUT / NEEDS CORRECTION</div><h1>CHECK FORMAT.</h1>"
                "<p>Your draft is saved in this browser. Use one measurement per line, for example: <code>bottle_height = 31 cm</code>.</p>"
                f"<pre>{html.escape(chr(10).join(rejected))}</pre><p><a href='/lab/{html.escape(session_id)}'>BACK TO QUESTIONS</a></p>"
            ),
            status_code=400,
        )

    uploads = [item for item in form.getlist("images") if getattr(item, "filename", "")]
    if len(uploads) > _MAX_FOLLOWUP_FILES:
        raise HTTPException(status_code=400, detail=f"Upload at most {_MAX_FOLLOWUP_FILES} follow-up images")

    try:
        image_urls = [await _upload_to_data_url(item, index=index) for index, item in enumerate(uploads, start=1)]
        user_statement = "\n".join(statements) or None
        if not image_urls and not measurements and not user_statement:
            raise ValueError("Answer at least one question, enter a measurement, add a note, upload a new photo, or choose Concept Mode")
        result = await continue_evidence_loop(
            current_state=session.project_state,
            new_image_urls=image_urls,
            user_statement=user_statement,
            measurements=measurements,
        )
    except (MaterialEyeError, ValueError) as exc:
        return _error_page("EVIDENCE LOOP", exc, f"/lab/{session_id}")

    verified_ready = can_advance_to_ideation(result.project_state)
    stage = "ready_for_futures" if verified_ready else "evidence_required"
    session = _lab_store().save(
        session.model_copy(
            update={
                "stage": stage,
                "project_state": result.project_state,
                "reasoning_mode": "verified" if verified_ready else session.reasoning_mode,
                "concept_mode_acknowledged": False if verified_ready else session.concept_mode_acknowledged,
                "concept_notice_version": None if verified_ready else session.concept_notice_version,
                "futures": None,
                "selected_candidate_id": None,
                "render_result": None,
            }
        )
    )
    summary = result.analysis_summary
    if result.resolved_unknown_keys:
        summary += " Resolved: " + ", ".join(result.resolved_unknown_keys) + "."
    return _state_page(session, summary)


@router.post("/lab/{session_id}/concept-mode", response_class=HTMLResponse, response_model=None, dependencies=[Depends(_require_lab_access)])
async def lab_concept_mode(session_id: str, request: Request) -> str:
    session = _get_session(session_id)
    form = await request.form()
    if not form.get("concept_ack"):
        return HTMLResponse(
            _page(
                "<div class='kicker'>CONCEPT MODE / ACKNOWLEDGEMENT REQUIRED</div><h1>NOT YET.</h1>"
                "<p>Please acknowledge that Concept Mode uses unverified AI assumptions before continuing.</p>"
                f"<p><a href='/lab/{html.escape(session_id)}'>BACK TO PROJECT</a></p>"
            ),
            status_code=400,
        )

    session = _lab_store().save(
        session.model_copy(
            update={
                "reasoning_mode": "concept",
                "concept_mode_acknowledged": True,
                "concept_notice_version": _CONCEPT_NOTICE_VERSION,
                "stage": "ready_for_futures",
                "futures": None,
                "selected_candidate_id": None,
                "render_result": None,
            }
        )
    )
    try:
        session = await discover_session_futures(
            session=session,
            preferences=_preferences_from_form(form, concept_mode=True),
            user_intent=str(form.get("user_intent") or "").strip() or None,
            max_revision_rounds=2,
            store=_lab_store(),
        )
    except (RuntimeError, ValueError) as exc:
        return _error_page("CONCEPT FUTURE DISCOVERY", exc, f"/lab/{session_id}")
    return _futures_page(session)


@router.get("/lab/{session_id}/futures", response_class=HTMLResponse, response_model=None, dependencies=[Depends(_require_lab_access)])
async def lab_futures_get(session_id: str) -> str:
    return _futures_page(_get_session(session_id))


@router.post("/lab/{session_id}/futures", response_class=HTMLResponse, response_model=None, dependencies=[Depends(_require_lab_access)])
async def lab_futures_post(session_id: str, request: Request) -> str:
    session = _get_session(session_id)
    form = await request.form()
    concept = session.reasoning_mode == "concept" and session.concept_mode_acknowledged
    try:
        session = await discover_session_futures(
            session=session,
            preferences=_preferences_from_form(form, concept_mode=concept),
            user_intent=str(form.get("user_intent") or "").strip() or None,
            max_revision_rounds=2,
            store=_lab_store(),
        )
    except (RuntimeError, ValueError) as exc:
        return _error_page("FUTURE DISCOVERY", exc, f"/lab/{session_id}")
    return _futures_page(session)


@router.post("/lab/{session_id}/render/{candidate_id}", response_class=HTMLResponse, response_model=None, dependencies=[Depends(_require_lab_access)])
async def lab_render(session_id: str, candidate_id: str) -> str:
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
        return _error_page("RENDER", exc, f"/lab/{session_id}/futures")
    return _render_result_page(session)

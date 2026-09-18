from __future__ import annotations

import html

from fastapi import APIRouter, Depends, Form, HTTPException, Query
from fastapi.responses import HTMLResponse, RedirectResponse

from .eval_models import EvalOutcome, EvalRecord
from .eval_store import create_eval_store
from . import studio as studio_module


router = APIRouter(tags=["studio-evals"])
_eval_store = None

_FAILURE_TAGS = [
    ("too_diy", "TOO DIY"),
    ("too_complex", "TOO COMPLEX"),
    ("weak_idea", "WEAK IDEA"),
    ("too_many_added_parts", "TOO MANY ADDED PARTS"),
    ("bad_render", "BAD RENDER"),
    ("lost_source", "LOST SOURCE OBJECT"),
    ("weak_signature_gesture", "WEAK SIGNATURE GESTURE"),
    ("low_physical_credibility", "LOW PHYSICAL CREDIBILITY"),
    ("world_rescues_object", "BACKGROUND RESCUES WEAK OBJECT"),
    ("other", "OTHER"),
]


def _store():
    global _eval_store
    if _eval_store is None:
        _eval_store = create_eval_store()
    return _eval_store


def _selected_future(session):
    if session.futures is None or not session.selected_candidate_id:
        return None
    return next(
        (
            item
            for item in session.futures.selected_futures
            if item.candidate.candidate_id == session.selected_candidate_id
        ),
        None,
    )


def _score_options(default: int = 3) -> str:
    rows = []
    for score in range(1, 6):
        selected = " selected" if score == default else ""
        rows.append(f"<option value='{score}'{selected}>{score}</option>")
    return "".join(rows)


def _eval_form(session) -> str:
    result = session.render_result
    future = _selected_future(session)
    if (
        result is None
        or result.status != "pass"
        or result.accepted_image_url is None
        or future is None
    ):
        return ""

    tag_rows = "".join(
        (
            "<label class='eval-check'>"
            f"<input type='checkbox' name='failure_tags' value='{html.escape(value, quote=True)}'/> "
            f"{html.escape(label)}</label>"
        )
        for value, label in _FAILURE_TAGS
    )
    candidate_name = html.escape(future.candidate.name)
    return f"""
<style>
.eval-grid{{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:14px}}
.eval-check{{display:block;margin:7px 0;color:#c9c0b3}}.eval-check input{{width:auto;margin-right:8px}}
@media(max-width:760px){{.eval-grid{{grid-template-columns:1fr}}}}
</style>
<div class='rule'></div>
<div class='panel'>
<div class='k'>WAVE 2 / TEACH RUINFORM</div>
<h2>RATE THIS RESULT.</h2>
<p class='muted'>This saves a permanent snapshot of <strong>{candidate_name}</strong>. Later edits or re-renders will not rewrite this evaluation.</p>
<form method='post' action='/studio/{html.escape(session.session_id)}/evaluate'>
<div class='eval-grid'>
<div><label>OUTCOME</label><select name='outcome' required>
<option value='success'>SUCCESS — keep as a positive example</option>
<option value='mixed' selected>MIXED — useful lesson, not fully there</option>
<option value='fail'>FAIL — learn what not to repeat</option>
</select></div>
<div><label>WOULD YOU KEEP / BUILD IT?</label><select name='would_keep_or_build' required>
<option value='yes'>YES</option><option value='maybe' selected>MAYBE</option><option value='no'>NO</option>
</select></div>
<div><label>IDEA / 5</label><select name='idea_score'>{_score_options(3)}</select></div>
<div><label>WOW / 5</label><select name='wow_score'>{_score_options(3)}</select></div>
<div><label>PHYSICAL CREDIBILITY / 5</label><select name='physical_credibility_score'>{_score_options(3)}</select></div>
<div><label>SOURCE PARTICIPATION / 5</label><select name='source_participation_score'>{_score_options(3)}</select></div>
<div><label>COLLECTIBLE QUALITY / 5</label><select name='collectible_quality_score'>{_score_options(3)}</select></div>
</div>
<label>WHAT FAILED? — optional</label>
<div>{tag_rows}</div>
<label>GOOD — optional</label><textarea name='good_notes' rows='2' maxlength='1200' placeholder='Strong silhouette, source still recognizable, one clear gesture...'></textarea>
<label>BAD — optional</label><textarea name='bad_notes' rows='2' maxlength='1200' placeholder='Too DIY, impossible physics, generic support geometry...'></textarea>
<button type='submit'>SAVE TO EVAL LIBRARY</button>
</form>
<p><a href='/studio/evals'>OPEN EVAL LIBRARY</a></p>
</div>
"""


def _record_from_session(
    session,
    *,
    outcome: EvalOutcome,
    idea_score: int,
    wow_score: int,
    physical_credibility_score: int,
    source_participation_score: int,
    collectible_quality_score: int,
    would_keep_or_build: str,
    failure_tags: list[str],
    good_notes: str,
    bad_notes: str,
) -> EvalRecord:
    result = session.render_result
    future = _selected_future(session)
    if (
        result is None
        or result.status != "pass"
        or result.accepted_image_url is None
        or future is None
    ):
        raise HTTPException(status_code=400, detail="An approved selected render is required before evaluation")

    valid_tags = {value for value, _ in _FAILURE_TAGS}
    cleaned_tags = [tag for tag in failure_tags if tag in valid_tags]
    intent = session.project_state.creative_intent

    return EvalRecord(
        session_id=session.session_id,
        project_id=session.project_id,
        candidate_id=future.candidate.candidate_id,
        candidate_name=future.candidate.name,
        background_mode=intent.background_mode,
        difficulty_mode=intent.difficulty_mode,
        creative_direction=intent.direction,
        render_url=str(result.accepted_image_url),
        outcome=outcome,
        idea_score=idea_score,
        wow_score=wow_score,
        physical_credibility_score=physical_credibility_score,
        source_participation_score=source_participation_score,
        collectible_quality_score=collectible_quality_score,
        would_keep_or_build=would_keep_or_build,
        failure_tags=cleaned_tags,
        good_notes=good_notes.strip() or None,
        bad_notes=bad_notes.strip() or None,
        source_items=[item.display_name for item in session.project_state.materials],
        source_material_ids=[item.item_id for item in session.project_state.materials],
        concept_snapshot=future.candidate.model_dump(mode="json"),
        review_snapshot=future.review.model_dump(mode="json"),
        render_snapshot=result.model_dump(mode="json"),
    )


def _eval_card(record: EvalRecord) -> str:
    tags = " ".join(f"<span class='badge'>{html.escape(tag.upper())}</span>" for tag in record.failure_tags)
    source = " · ".join(html.escape(x) for x in record.source_items)
    good = f"<p><strong>GOOD:</strong> {html.escape(record.good_notes)}</p>" if record.good_notes else ""
    bad = f"<p><strong>BAD:</strong> {html.escape(record.bad_notes)}</p>" if record.bad_notes else ""
    return f"""
<div class='card'>
<div class='k'>{html.escape(record.outcome.upper())} / {html.escape(record.difficulty_mode.upper())} / {html.escape(record.background_mode.upper())}</div>
<h2>{html.escape(record.candidate_name)}</h2>
<p class='muted'>{source}</p>
<div class='scores'>IDEA {record.idea_score}/5 · WOW {record.wow_score}/5 · PHYSICAL {record.physical_credibility_score}/5 · SOURCE {record.source_participation_score}/5 · COLLECTIBLE {record.collectible_quality_score}/5</div>
<p><strong>KEEP / BUILD:</strong> {html.escape(record.would_keep_or_build.upper())}</p>
<div>{tags}</div>
{good}{bad}
<p><a href='{html.escape(record.render_url, quote=True)}'>OPEN RENDER</a> · <a href='/studio/{html.escape(record.session_id)}'>OPEN PROJECT</a></p>
</div>
"""


@router.get('/studio/evals', response_class=HTMLResponse, dependencies=[Depends(studio_module._require_access)])
async def studio_eval_library(outcome: str | None = Query(default=None)) -> str:
    selected: EvalOutcome | None = outcome if outcome in {"success", "mixed", "fail"} else None
    records = _store().list_recent(outcome=selected, limit=80)
    cards = "".join(_eval_card(record) for record in records) or "<p class='muted'>No evaluations saved yet.</p>"
    active = selected.upper() if selected else "ALL"
    body = f"""
<div class='k'>RUINFORM / EVAL LIBRARY</div>
<h1>MEMORY,<br>NOT VIBES.</h1>
<p>Every card is a frozen learning example. SUCCESS, MIXED and FAIL stay in one dataset so Wave 3 can retrieve both inspiration and warnings.</p>
<p><span class='badge'>VIEW: {html.escape(active)}</span></p>
<p><a href='/studio/evals'>ALL</a> · <a href='/studio/evals?outcome=success'>SUCCESS</a> · <a href='/studio/evals?outcome=mixed'>MIXED</a> · <a href='/studio/evals?outcome=fail'>FAIL</a></p>
<div class='grid'>{cards}</div>
"""
    return studio_module._page(body, title="RUINFORM / EVAL LIBRARY")


@router.post('/studio/{session_id}/evaluate', response_class=HTMLResponse, dependencies=[Depends(studio_module._require_access)])
async def studio_evaluate(
    session_id: str,
    outcome: EvalOutcome = Form(...),
    idea_score: int = Form(...),
    wow_score: int = Form(...),
    physical_credibility_score: int = Form(...),
    source_participation_score: int = Form(...),
    collectible_quality_score: int = Form(...),
    would_keep_or_build: str = Form(...),
    failure_tags: list[str] = Form(default=[]),
    good_notes: str = Form(default=''),
    bad_notes: str = Form(default=''),
):
    if would_keep_or_build not in {"yes", "maybe", "no"}:
        raise HTTPException(status_code=422, detail="Invalid keep/build value")
    session = studio_module._session(session_id)
    record = _record_from_session(
        session,
        outcome=outcome,
        idea_score=idea_score,
        wow_score=wow_score,
        physical_credibility_score=physical_credibility_score,
        source_participation_score=source_participation_score,
        collectible_quality_score=collectible_quality_score,
        would_keep_or_build=would_keep_or_build,
        failure_tags=failure_tags,
        good_notes=good_notes,
        bad_notes=bad_notes,
    )
    _store().save(record)
    return RedirectResponse(url=f"/studio/evals?outcome={record.outcome}", status_code=303)


# Append the Wave 2 evaluation form to every approved Studio render without
# changing the stable render pipeline itself.
_original_render_page = studio_module._render_page


def _render_page_with_eval(session):
    return _original_render_page(session) + _eval_form(session)


studio_module._render_page = _render_page_with_eval

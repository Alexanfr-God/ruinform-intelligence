from __future__ import annotations

import html

from fastapi import APIRouter, Depends, Form, HTTPException, Query
from fastapi.responses import HTMLResponse, RedirectResponse

from .eval_models import EvalOutcome, EvalRecord
from .eval_store import create_eval_store
from .review_store import ReviewItemNotFound, create_review_store
from . import studio as studio_module


router = APIRouter(tags=["studio-reviews"])
_review_store = None
_eval_store = None

_FAILURE_TAGS = [
    ("too_diy", "TOO DIY"),
    ("too_complex", "TOO COMPLEX"),
    ("requires_too_much_craft_skill", "REQUIRES TOO MUCH CRAFT SKILL"),
    ("overdesigned", "OVERDESIGNED"),
    ("weak_idea", "WEAK IDEA"),
    ("too_many_added_parts", "TOO MANY ADDED PARTS"),
    ("bad_render", "BAD RENDER"),
    ("lost_source", "LOST SOURCE OBJECT"),
    ("weak_signature_gesture", "WEAK SIGNATURE GESTURE"),
    ("mechanism_not_visually_readable", "MECHANISM NOT VISUALLY READABLE"),
    ("low_physical_credibility", "LOW PHYSICAL CREDIBILITY"),
    ("world_rescues_object", "BACKGROUND RESCUES WEAK OBJECT"),
    ("other", "OTHER"),
]


def _reviews():
    global _review_store
    if _review_store is None:
        _review_store = create_review_store()
    return _review_store


def _evals():
    global _eval_store
    if _eval_store is None:
        _eval_store = create_eval_store()
    return _eval_store


def _score_options(default: int = 3) -> str:
    return "".join(
        f"<option value='{score}'{' selected' if score == default else ''}>{score}</option>"
        for score in range(1, 6)
    )


def _review_card(item) -> str:
    source = " · ".join(html.escape(x) for x in item.source_items)
    return f"""
<div class='card'>
<div class='k'>PENDING / {html.escape(item.difficulty_mode.upper())} / {html.escape(item.background_mode.upper())}</div>
<h2>{html.escape(item.candidate_name)}</h2>
<img class='hero' src='{html.escape(item.render_url, quote=True)}' alt='Pending RUINFORM render'/>
<p class='muted'>{source}</p>
<p><a href='/studio/reviews/{html.escape(item.review_id)}'>RATE NOW</a> · <a href='/studio/{html.escape(item.session_id)}'>OPEN PROJECT</a></p>
</div>
"""


def _review_form(item) -> str:
    tag_rows = "".join(
        (
            "<label class='eval-check'>"
            f"<input type='checkbox' name='failure_tags' value='{html.escape(value, quote=True)}'/> "
            f"{html.escape(label)}</label>"
        )
        for value, label in _FAILURE_TAGS
    )
    source = " · ".join(html.escape(x) for x in item.source_items)
    return f"""
<style>
.eval-grid{{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:14px}}
.eval-check{{display:block;margin:7px 0;color:#c9c0b3}}.eval-check input{{width:auto;margin-right:8px}}
@media(max-width:760px){{.eval-grid{{grid-template-columns:1fr}}}}
</style>
<div class='k'>RUINFORM / REVIEW INBOX</div>
<h1>TEACH IT<br>LATER.</h1>
<p>This render is frozen. You can judge it now even if the original Studio project has moved on to another concept or background.</p>
<div class='panel'><div class='k'>SOURCE MATTER</div><p class='muted'>{source}</p></div>
<h2>{html.escape(item.candidate_name)}</h2>
<img class='hero' src='{html.escape(item.render_url, quote=True)}' alt='RUINFORM render awaiting evaluation'/>
<div class='panel'>
<form method='post' action='/studio/reviews/{html.escape(item.review_id)}/evaluate'>
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
<label>WHAT FAILED? — optional</label><div>{tag_rows}</div>
<label>GOOD — optional</label><textarea name='good_notes' rows='3' maxlength='1200' placeholder='Strong silhouette, source still recognizable, one clear gesture...'></textarea>
<label>BAD — optional</label><textarea name='bad_notes' rows='3' maxlength='1200' placeholder='Mechanism unclear, too DIY, weak gesture, requires too much craft skill...'></textarea>
<button type='submit'>SAVE EVALUATION + CLEAR FROM INBOX</button>
</form>
</div>
<p><a href='/studio/reviews'>BACK TO REVIEW INBOX</a></p>
"""


def _eval_from_review_item(
    item,
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
    valid_tags = {value for value, _ in _FAILURE_TAGS}
    return EvalRecord(
        session_id=item.session_id,
        project_id=item.project_id,
        candidate_id=item.candidate_id,
        candidate_name=item.candidate_name,
        background_mode=item.background_mode,
        difficulty_mode=item.difficulty_mode,
        creative_direction=item.creative_direction,
        render_url=item.render_url,
        outcome=outcome,
        idea_score=idea_score,
        wow_score=wow_score,
        physical_credibility_score=physical_credibility_score,
        source_participation_score=source_participation_score,
        collectible_quality_score=collectible_quality_score,
        would_keep_or_build=would_keep_or_build,
        failure_tags=[tag for tag in failure_tags if tag in valid_tags],
        good_notes=good_notes.strip() or None,
        bad_notes=bad_notes.strip() or None,
        source_items=item.source_items,
        source_material_ids=item.source_material_ids,
        concept_snapshot=item.concept_snapshot,
        review_snapshot=item.review_snapshot,
        render_snapshot=item.render_snapshot,
    )


@router.get('/studio/reviews', response_class=HTMLResponse, dependencies=[Depends(studio_module._require_access)])
async def studio_review_inbox(status: str = Query(default='pending')) -> str:
    selected = status if status in {'pending', 'evaluated'} else 'pending'
    items = _reviews().list_recent(status=selected, limit=120)
    cards = "".join(_review_card(item) for item in items) or "<p class='muted'>Nothing waiting here.</p>"
    body = f"""
<div class='k'>RUINFORM / REVIEW INBOX</div>
<h1>UNRATED,<br>NOT LOST.</h1>
<p>Every approved generation is frozen here until a human turns it into SUCCESS, MIXED or FAIL. Public traffic can generate now; teaching can happen later.</p>
<p><span class='badge'>VIEW: {html.escape(selected.upper())}</span> <span class='badge'>{len(items)} ITEMS</span></p>
<p><a href='/studio/reviews?status=pending'>PENDING</a> · <a href='/studio/reviews?status=evaluated'>EVALUATED</a> · <a href='/studio/evals'>EVAL LIBRARY</a></p>
<div class='grid'>{cards}</div>
"""
    return studio_module._page(body, title='RUINFORM / REVIEW INBOX')


@router.get('/studio/reviews/{review_id}', response_class=HTMLResponse, dependencies=[Depends(studio_module._require_access)])
async def studio_review_item(review_id: str) -> str:
    try:
        item = _reviews().get(review_id)
    except ReviewItemNotFound as exc:
        raise HTTPException(status_code=404, detail='Review item not found') from exc
    if item.status == 'evaluated':
        body = f"""
<div class='k'>RUINFORM / REVIEW INBOX</div><h1>ALREADY<br>LEARNED.</h1>
<p>This render has already been moved into the Eval Library.</p>
<img class='hero' src='{html.escape(item.render_url, quote=True)}' alt='Evaluated RUINFORM render'/>
<p><a href='/studio/evals'>OPEN EVAL LIBRARY</a> · <a href='/studio/reviews'>BACK TO REVIEW INBOX</a></p>
"""
        return studio_module._page(body, title='RUINFORM / REVIEWED')
    return studio_module._page(_review_form(item), title='RUINFORM / RATE RENDER')


@router.post('/studio/reviews/{review_id}/evaluate', response_class=HTMLResponse, dependencies=[Depends(studio_module._require_access)])
async def studio_review_evaluate(
    review_id: str,
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
    if would_keep_or_build not in {'yes', 'maybe', 'no'}:
        raise HTTPException(status_code=422, detail='Invalid keep/build value')
    try:
        item = _reviews().get(review_id)
    except ReviewItemNotFound as exc:
        raise HTTPException(status_code=404, detail='Review item not found') from exc
    if item.status == 'evaluated':
        return RedirectResponse(url='/studio/evals', status_code=303)

    record = _eval_from_review_item(
        item,
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
    _evals().save(record)
    _reviews().mark_evaluated(review_id, record.eval_id)
    return RedirectResponse(url=f'/studio/evals?outcome={record.outcome}', status_code=303)

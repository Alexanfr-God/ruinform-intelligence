from __future__ import annotations

import html

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import HTMLResponse, RedirectResponse

from .idea_store import IdeaBatch, IdeaBatchNotFound, create_idea_store
from . import studio as studio_module


router = APIRouter(tags=["studio-ideas"])
_store = None


def _ideas():
    global _store
    if _store is None:
        _store = create_idea_store()
    return _store


def _candidate_rows(item: IdeaBatch) -> list[dict]:
    rows = item.futures_snapshot.get("selected_futures", [])
    return [row for row in rows if isinstance(row, dict)]


def _retrieval_trace(item: IdeaBatch) -> dict:
    trace = item.futures_snapshot.get("retrieval_trace", {})
    return trace if isinstance(trace, dict) else {}


def _memory_badges(item: IdeaBatch) -> str:
    trace = _retrieval_trace(item)
    if not trace:
        return ""
    taste = len(trace.get("taste_cards") or [])
    evals = len(trace.get("evals") or [])
    lessons = len(trace.get("lessons") or [])
    shortlists = len(trace.get("shortlisted_ideas") or [])
    return (
        f"<span class='badge'>MEMORY: {taste} TASTE</span>"
        f"<span class='badge'>{evals} EVAL</span>"
        f"<span class='badge'>{lessons} LESSON</span>"
        f"<span class='badge'>{shortlists} SHORTLIST</span>"
    )


def _memory_panel(item: IdeaBatch) -> str:
    trace = _retrieval_trace(item)
    if not trace:
        return "<div class='panel'><div class='k'>WAVE 3 / MEMORY ROUTER</div><p class='muted'>This batch predates retrieval tracing.</p></div>"

    taste_rows = trace.get("taste_cards") or []
    eval_rows = trace.get("evals") or []
    lesson_rows = trace.get("lessons") or []
    shortlist_rows = trace.get("shortlisted_ideas") or []

    taste = "".join(
        f"<li><strong>{html.escape(str(row.get('id', '')))}</strong> — {html.escape(str(row.get('title', '')))} <span class='muted'>/{html.escape(str(row.get('operator', '')))}</span></li>"
        for row in taste_rows if isinstance(row, dict)
    ) or "<li class='muted'>none</li>"
    evals = "".join(
        f"<li><strong>{html.escape(str(row.get('outcome', '')).upper())}</strong> — {html.escape(str(row.get('candidate_name', '')))} <span class='muted'>relevance {html.escape(str(row.get('score', '')))}</span></li>"
        for row in eval_rows if isinstance(row, dict)
    ) or "<li class='muted'>none relevant</li>"
    lessons = "".join(
        f"<li><strong>{html.escape(str(row.get('id', '')))}</strong> — {html.escape(str(row.get('title', '')))}</li>"
        for row in lesson_rows if isinstance(row, dict)
    ) or "<li class='muted'>none triggered</li>"
    shortlists = "".join(
        f"<li>{html.escape(str(row.get('name', 'Unnamed idea')))} <span class='muted'>relevance {html.escape(str(row.get('score', '')))}</span></li>"
        for row in shortlist_rows if isinstance(row, dict)
    ) or "<li class='muted'>none relevant</li>"

    strategy = html.escape(str(trace.get("strategy", "unknown")))
    return f"""
<div class='panel'>
<div class='k'>WAVE 3 / MEMORY ROUTER</div>
<p><span class='badge'>{html.escape(str(trace.get('version', 'wave3')))}</span><span class='badge'>{strategy}</span></p>
<p class='muted'>Design Brain saw only this retrieved memory pack, not the whole library. Current source photos and Creative Direction still have priority.</p>
<div class='grid'>
<div><h2>TASTE / RETRIEVED</h2><ul>{taste}</ul></div>
<div><h2>HUMAN EVALS</h2><ul>{evals}</ul></div>
<div><h2>CONDITIONAL LESSONS</h2><ul>{lessons}</ul></div>
<div><h2>SHORTLISTED / UNJUDGED</h2><ul>{shortlists}</ul></div>
</div>
</div>
"""


def _candidate_card(item: IdeaBatch, row: dict) -> str:
    candidate = row.get("candidate", {}) if isinstance(row.get("candidate"), dict) else {}
    review = row.get("review", {}) if isinstance(row.get("review"), dict) else {}
    candidate_id = str(candidate.get("candidate_id", "unknown"))
    name = str(candidate.get("name", "Unnamed future"))
    one_line = str(candidate.get("one_line", ""))
    transformation = str(candidate.get("transformation_logic", ""))
    category = str(candidate.get("category", "other")).upper()
    rank = row.get("rank_score")
    rank_label = f" / PREVIEW {float(rank):.1f}" if isinstance(rank, (int, float)) else ""
    shortlisted = candidate_id in item.shortlisted_candidate_ids
    rendered = candidate_id in item.rendered_candidate_ids
    status_bits = []
    if shortlisted:
        status_bits.append("SHORTLISTED")
    if rendered:
        status_bits.append("RENDERED")
    status_html = " ".join(f"<span class='badge'>{html.escape(bit)}</span>" for bit in status_bits)
    score_line = (
        f"BUILDABILITY {review.get('buildability_score', '?')} / "
        f"ORIGINALITY {review.get('originality_score', '?')} / "
        f"ART {review.get('artistic_impact_score', '?')} / "
        f"USEFULNESS {review.get('usefulness_score', '?')} / "
        f"VALUE {review.get('value_potential_score', '?')}"
    )
    shortlist_button = "" if shortlisted else f"""
<form method='post' action='/studio/ideas/{html.escape(item.batch_id)}/shortlist/{html.escape(candidate_id)}'>
<button class='secondary' type='submit'>SHORTLIST THIS IDEA</button>
</form>
"""
    return f"""
<div class='card'>
<div class='k'>{html.escape(category)}{html.escape(rank_label)}</div>
<h2>{html.escape(name)}</h2>
<p>{html.escape(one_line)}</p>
<p><strong>Transformation:</strong> {html.escape(transformation)}</p>
<div class='scores'>{html.escape(score_line)}</div>
<div>{status_html}</div>
{shortlist_button}
</div>
"""


def _batch_card(item: IdeaBatch) -> str:
    source = " · ".join(html.escape(x) for x in item.source_items)
    names = []
    for row in _candidate_rows(item):
        candidate = row.get("candidate", {}) if isinstance(row.get("candidate"), dict) else {}
        if candidate.get("name"):
            names.append(html.escape(str(candidate["name"])))
    names_html = "<br>".join(names)
    return f"""
<div class='card'>
<div class='k'>{html.escape(item.status.upper())} / {html.escape(item.difficulty_mode.upper())} / {html.escape(item.background_mode.upper())}</div>
<h2>4 FUTURES</h2>
<p class='muted'>{source}</p>
<p>{names_html}</p>
<p><span class='badge'>{len(item.shortlisted_candidate_ids)} SHORTLISTED</span><span class='badge'>{len(item.rendered_candidate_ids)} RENDERED</span>{_memory_badges(item)}</p>
<p><a href='/studio/ideas/{html.escape(item.batch_id)}'>OPEN IDEA BATCH</a> · <a href='/studio/{html.escape(item.session_id)}/concepts'>OPEN CURRENT PROJECT</a></p>
</div>
"""


@router.get('/studio/ideas', response_class=HTMLResponse, dependencies=[Depends(studio_module._require_access)])
async def studio_idea_room(status: str = Query(default='all')) -> str:
    selected = status if status in {'pending', 'rendered', 'archived'} else 'all'
    rows = _ideas().list_recent(status=None if selected == 'all' else selected, limit=120)
    cards = "".join(_batch_card(item) for item in rows) or "<p class='muted'>No idea batches captured yet.</p>"
    body = f"""
<div class='k'>RUINFORM / IDEA ROOM</div>
<h1>UNPICKED,<br>NOT WASTED.</h1>
<p>Every four-future concept batch is frozen here before rendering. Generated thinking becomes reusable product memory instead of disappearing when another set is created.</p>
<p><span class='badge'>VIEW: {html.escape(selected.upper())}</span><span class='badge'>{len(rows)} BATCHES</span></p>
<p><a href='/studio/ideas'>ALL</a> · <a href='/studio/ideas?status=pending'>UNRENDERED</a> · <a href='/studio/ideas?status=rendered'>RENDERED</a> · <a href='/studio/ideas?status=archived'>ARCHIVED</a></p>
<div class='grid'>{cards}</div>
"""
    return studio_module._page(body, title='RUINFORM / IDEA ROOM')


@router.get('/studio/ideas/{batch_id}', response_class=HTMLResponse, dependencies=[Depends(studio_module._require_access)])
async def studio_idea_batch(batch_id: str) -> str:
    try:
        item = _ideas().get(batch_id)
    except IdeaBatchNotFound as exc:
        raise HTTPException(status_code=404, detail='Idea batch not found') from exc
    source = " · ".join(html.escape(x) for x in item.source_items)
    direction = html.escape(item.creative_direction or 'RUINFORM decides')
    cards = "".join(_candidate_card(item, row) for row in _candidate_rows(item))
    body = f"""
<div class='k'>RUINFORM / IDEA SNAPSHOT</div>
<h1>FOUR<br>FUTURES.</h1>
<div class='panel'><div class='k'>SOURCE MATTER</div><p>{source}</p></div>
<div class='panel'><span class='badge'>DIFFICULTY: {html.escape(item.difficulty_mode.upper())}</span><span class='badge'>BACKGROUND: {html.escape(item.background_mode.upper())}</span><p class='muted'><strong>Creative Direction:</strong> {direction}</p></div>
{_memory_panel(item)}
<div class='grid'>{cards}</div>
<form method='post' action='/studio/ideas/{html.escape(item.batch_id)}/archive'><button class='secondary' type='submit'>ARCHIVE THIS BATCH</button></form>
<p><a href='/studio/{html.escape(item.session_id)}/concepts'>OPEN CURRENT PROJECT</a> · <a href='/studio/ideas'>BACK TO IDEA ROOM</a></p>
"""
    return studio_module._page(body, title='RUINFORM / IDEA SNAPSHOT')


@router.post('/studio/ideas/{batch_id}/shortlist/{candidate_id}', dependencies=[Depends(studio_module._require_access)])
async def studio_idea_shortlist(batch_id: str, candidate_id: str):
    try:
        _ideas().shortlist(batch_id, candidate_id)
    except IdeaBatchNotFound as exc:
        raise HTTPException(status_code=404, detail='Idea or candidate not found') from exc
    return RedirectResponse(url=f'/studio/ideas/{batch_id}', status_code=303)


@router.post('/studio/ideas/{batch_id}/archive', dependencies=[Depends(studio_module._require_access)])
async def studio_idea_archive(batch_id: str):
    try:
        _ideas().archive(batch_id)
    except IdeaBatchNotFound as exc:
        raise HTTPException(status_code=404, detail='Idea batch not found') from exc
    return RedirectResponse(url='/studio/ideas?status=archived', status_code=303)

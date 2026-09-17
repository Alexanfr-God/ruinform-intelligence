from __future__ import annotations

import html

from fastapi import APIRouter, Depends, Form
from fastapi.responses import HTMLResponse, RedirectResponse

from .studio import _page, _require_access, _session, _studio_store


router = APIRouter(tags=["studio-controls"])
_DIFFICULTY_MODES = {"easy", "medium", "wild"}
_BACKGROUND_MODES = {"clean_studio", "ruinform_world"}


def _selected(value: str, expected: str) -> str:
    return " selected" if value == expected else ""


def _controls_page(session_id: str) -> str:
    session = _session(session_id)
    intent = session.project_state.creative_intent
    direction = html.escape(intent.direction or "", quote=True)
    body = f"""
<div class='k'>RUINFORM / PROJECT CONTROLS</div>
<h1>CHANGE DIRECTION.<br>KEEP THE SOURCE.</h1>
<p>Adjust the creative brief without re-uploading photographs. Saving controls clears the previous concept/render selection so the same source matter can be tested again under a new direction.</p>
<div class='panel'>
<form method='post' action='/studio/{html.escape(session_id)}/controls'>
<label>CREATIVE DIRECTION — optional</label>
<textarea name='creative_direction' rows='4' maxlength='800' placeholder='Leave blank and let RUINFORM decide. Or: useful collectible, keep bottle intact, no electronics, more brutal...'>{direction}</textarea>
<label>DIFFICULTY</label>
<select name='difficulty_mode'>
<option value='easy'{_selected(intent.difficulty_mode, 'easy')}>EASY — simple tools, minimal additions</option>
<option value='medium'{_selected(intent.difficulty_mode, 'medium')}>MEDIUM — workshop-level transformation</option>
<option value='wild'{_selected(intent.difficulty_mode, 'wild')}>WILD — radical form, mechanisms allowed</option>
</select>
<label>DEFAULT BACKGROUND MODE</label>
<select name='background_mode'>
<option value='clean_studio'{_selected(intent.background_mode, 'clean_studio')}>CLEAN STUDIO — object first</option>
<option value='ruinform_world'{_selected(intent.background_mode, 'ruinform_world')}>RUINFORM WORLD — post-apocalyptic hero setting</option>
</select>
<p class='muted'>Background remains a presentation choice. You can still A/B the same selected concept later from its render card.</p>
<button type='submit'>SAVE CONTROLS → GENERATE AGAIN</button>
</form>
</div>
<p><a href='/studio/{html.escape(session_id)}'>BACK TO CURRENT PROJECT</a> · <a href='/studio/new'>START A NEW PROJECT</a></p>
"""
    return _page(body, title="RUINFORM / PROJECT CONTROLS")


@router.get('/studio/{session_id}/controls', response_class=HTMLResponse, dependencies=[Depends(_require_access)])
async def studio_controls(session_id: str) -> str:
    return _controls_page(session_id)


@router.post('/studio/{session_id}/controls', response_class=HTMLResponse, dependencies=[Depends(_require_access)])
async def studio_controls_submit(
    session_id: str,
    creative_direction: str = Form(default=''),
    difficulty_mode: str = Form(default='medium'),
    background_mode: str = Form(default='clean_studio'),
):
    session = _session(session_id)
    if difficulty_mode not in _DIFFICULTY_MODES:
        difficulty_mode = 'medium'
    if background_mode not in _BACKGROUND_MODES:
        background_mode = 'clean_studio'

    creative_intent = session.project_state.creative_intent.model_copy(
        update={
            'direction': creative_direction.strip() or None,
            'difficulty_mode': difficulty_mode,
            'background_mode': background_mode,
        }
    )
    project_state = session.project_state.model_copy(
        update={'creative_intent': creative_intent}
    )
    _studio_store().save(
        session.model_copy(
            update={
                'stage': 'ready_for_futures',
                'project_state': project_state,
                'futures': None,
                'selected_candidate_id': None,
                'render_result': None,
                'build_plan': None,
            }
        )
    )
    return RedirectResponse(url=f'/studio/{session_id}', status_code=303)

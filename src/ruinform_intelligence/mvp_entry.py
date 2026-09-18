from __future__ import annotations

import base64
import html

from fastapi import APIRouter, Depends, File, Form, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse

from .material_eye import MaterialEyeError, analyze_evidence
from .models import CreativeIntent, EvidenceItem, ProjectConstraints
from .run_store import SqliteRunStore, TransformationSession
from .studio import _require_access


router = APIRouter(tags=["mvp-entry"])
_ALLOWED_TYPES = {"image/jpeg", "image/png", "image/webp"}
_MAX_FILES = 8
_MAX_FILE_BYTES = 8 * 1024 * 1024
_MAX_CREATIVE_DIRECTION_CHARS = 3000
_DIFFICULTY_MODES = {"easy", "medium", "wild"}
_BACKGROUND_MODES = {"clean_studio", "ruinform_world"}


async def _to_data_url(upload: UploadFile, *, index: int) -> str:
    media_type = upload.content_type or ""
    if media_type not in _ALLOWED_TYPES:
        raise ValueError(f"Unsupported image type: {media_type or 'unknown'}")
    raw = await upload.read(_MAX_FILE_BYTES + 1)
    if len(raw) > _MAX_FILE_BYTES:
        raise ValueError(f"Image {index} exceeds 8 MB")
    return f"data:{media_type};base64,{base64.b64encode(raw).decode('ascii')}"


def _page(body: str) -> str:
    return f"""<!doctype html>
<html lang='en'><head><meta charset='utf-8'/><meta name='viewport' content='width=device-width,initial-scale=1'/>
<title>RUINFORM / NEW PROJECT</title>
<style>
:root{{color-scheme:dark}}*{{box-sizing:border-box}}body{{margin:0;background:#080807;color:#eee8dd;font-family:ui-monospace,SFMono-Regular,Menlo,monospace}}main{{max-width:860px;margin:0 auto;padding:54px 22px 100px}}h1{{font-size:clamp(46px,9vw,108px);line-height:.86;letter-spacing:-.065em;margin:0 0 24px}}p{{line-height:1.55;color:#aaa296}}.k{{font-size:12px;letter-spacing:.2em;color:#8f887b;margin-bottom:16px}}.panel{{border:1px solid #343029;background:#0f0f0d;padding:22px;margin:22px 0}}label{{display:block;margin:18px 0 8px;color:#b9b1a4}}input,textarea,select,button{{width:100%;background:#12110f;color:#eee8dd;border:1px solid #3d3932;padding:14px;font:inherit}}button{{cursor:pointer;background:#e8e0d1;color:#111;border:0;font-weight:700;margin-top:20px}}.steps{{display:grid;grid-template-columns:repeat(3,1fr);gap:10px;margin:28px 0}}.step{{border:1px solid #302d28;padding:14px;color:#aaa296}}.step strong{{display:block;color:#eee8dd;margin-bottom:6px}}.hint{{font-size:12px;color:#746f66;margin-top:7px;line-height:1.55}}.control-grid{{display:grid;grid-template-columns:1fr 1fr;gap:14px}}#busy{{display:none;position:fixed;inset:0;background:rgba(5,5,4,.94);z-index:20;align-items:center;justify-content:center;text-align:center;padding:24px}}#busy.on{{display:flex}}#busy h2{{font-size:clamp(30px,6vw,70px);margin:8px 0}}@media(max-width:700px){{.steps,.control-grid{{grid-template-columns:1fr}}}}
</style></head><body>
<div id='busy'><div><div class='k'>RUINFORM / MATERIAL EYE</div><h2>READING MATTER.</h2><p>Looking at the actual photographs before any concept is invented.</p></div></div>
<main>{body}</main>
<script>var f=document.getElementById('new-project');if(f)f.addEventListener('submit',function(){{document.getElementById('busy').classList.add('on');}});</script>
</body></html>"""


@router.get('/studio/new', response_class=HTMLResponse, dependencies=[Depends(_require_access)])
async def new_project() -> str:
    return _page("""
<div class='k'>RUINFORM / MVP TEST FLOW</div>
<h1>SHOW ME<br>WHAT SURVIVED.</h1>
<p>Start a fresh project. Upload the real objects exactly as they are. Material Eye reads the photographs first; then the vision-first Design Brain will invent four different RUINFORM futures from the actual images.</p>
<div class='steps'>
<div class='step'><strong>01 / PHOTOS</strong>1–8 real source images.</div>
<div class='step'><strong>02 / DESIGN BRAIN</strong>Four concepts created while seeing the originals.</div>
<div class='step'><strong>03 / GPT IMAGE</strong>Render only the concept worth testing.</div>
</div>
<div class='panel'>
<form id='new-project' method='post' action='/studio/new' enctype='multipart/form-data'>
<label>PHOTOGRAPHS — 1 to 8</label>
<input type='file' name='images' accept='image/jpeg,image/png,image/webp' multiple required />
<label>WHAT DO I KNOW ABOUT THESE THINGS? — optional</label>
<textarea name='user_context' rows='3' placeholder='Facts only: old ceramic cup, broken adapter, used pencil, empty bottle...'></textarea>
<p class='hint'>Material facts help the system understand the source. Do not describe the desired final object here.</p>
<label>CREATIVE DIRECTION — optional</label>
<textarea name='creative_direction' rows='6' maxlength='3000' placeholder='Leave blank and let RUINFORM decide. Or describe the desired gesture, composition, exclusions and purpose. The source objects must still drive the result.'></textarea>
<p class='hint'>Up to 3000 characters. This guides the whole pipeline; it is not a free-form text-to-image prompt. Source reality and RUINFORM design rules still win.</p>
<div class='control-grid'>
<div>
<label>DIFFICULTY</label>
<select name='difficulty_mode'>
<option value='easy'>EASY — simple tools, minimal additions</option>
<option value='medium' selected>MEDIUM — workshop-level transformation</option>
<option value='wild'>WILD — radical form, mechanisms allowed</option>
</select>
</div>
<div>
<label>BACKGROUND MODE</label>
<select name='background_mode'>
<option value='clean_studio' selected>CLEAN STUDIO — object first</option>
<option value='ruinform_world'>RUINFORM WORLD — post-apocalyptic hero setting</option>
</select>
</div>
</div>
<p class='hint'>Background mode changes presentation, not the core object idea. Clean Studio tests the design honestly; RUINFORM World adds the post-apocalyptic salvage-luxury environment later.</p>
<button type='submit'>READ MATTER → START NEW PROJECT</button>
</form>
</div>
<p><a href='/studio-login?next=/studio/new'>SIGN IN AGAIN</a></p>
""")


@router.post('/studio/new', response_class=HTMLResponse, dependencies=[Depends(_require_access)])
async def new_project_submit(
    images: list[UploadFile] = File(...),
    user_context: str = Form(default=''),
    creative_direction: str = Form(default=''),
    difficulty_mode: str = Form(default='medium'),
    background_mode: str = Form(default='clean_studio'),
):
    if not 1 <= len(images) <= _MAX_FILES:
        return HTMLResponse(_page(f"<div class='k'>UPLOAD ERROR</div><h1>STOP.</h1><p>Upload between 1 and {_MAX_FILES} images.</p><p><a href='/studio/new'>TRY AGAIN</a></p>"), status_code=400)

    direction = creative_direction.strip()
    if len(direction) > _MAX_CREATIVE_DIRECTION_CHARS:
        return HTMLResponse(
            _page(
                "<div class='k'>CREATIVE DIRECTION / TOO LONG</div><h1>SHORTEN IT.</h1>"
                f"<p>Creative Direction is {len(direction)} characters. The current limit is {_MAX_CREATIVE_DIRECTION_CHARS}. "
                "Shorten the brief before Material Eye runs, so no analysis tokens are wasted.</p>"
                "<p><a href='/studio/new'>TRY AGAIN</a></p>"
            ),
            status_code=400,
        )

    if difficulty_mode not in _DIFFICULTY_MODES:
        difficulty_mode = 'medium'
    if background_mode not in _BACKGROUND_MODES:
        background_mode = 'clean_studio'

    evidence: list[EvidenceItem] = []
    try:
        for index, image in enumerate(images, start=1):
            evidence.append(
                EvidenceItem(
                    evidence_id=f"image_{index:03d}",
                    source_type="image",
                    uri=await _to_data_url(image, index=index),
                )
            )
        state, _summary = await analyze_evidence(
            evidence=evidence,
            user_context=user_context.strip() or None,
            constraints=ProjectConstraints(),
        )
        state = state.model_copy(
            update={
                'creative_intent': CreativeIntent(
                    direction=direction or None,
                    difficulty_mode=difficulty_mode,
                    background_mode=background_mode,
                )
            }
        )
    except (MaterialEyeError, ValueError) as exc:
        return HTMLResponse(
            _page(
                "<div class='k'>MATERIAL EYE / ERROR</div><h1>STOP.</h1>"
                f"<p>{html.escape(str(exc))}</p><p><a href='/studio/new'>TRY AGAIN</a></p>"
            ),
            status_code=502,
        )

    store = SqliteRunStore()
    session = store.save(
        TransformationSession(
            project_id=state.project_id,
            stage="ready_for_futures",
            project_state=state,
            reasoning_mode="concept",
            concept_mode_acknowledged=True,
            concept_notice_version="mvp-vision-first-2026-09",
        )
    )
    return RedirectResponse(url=f"/studio/{session.session_id}", status_code=303)
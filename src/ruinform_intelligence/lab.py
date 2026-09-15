from __future__ import annotations

import base64
import html
import os
import secrets

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from fastapi.responses import HTMLResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials

from .evidence_gate import can_advance_to_ideation
from .material_eye import MaterialEyeError, analyze_evidence
from .models import EvidenceItem, ProjectConstraints

router = APIRouter(tags=["lab"])
security = HTTPBasic()

_ALLOWED_TYPES = {"image/jpeg", "image/png", "image/webp"}
_MAX_FILES = 8
_MAX_FILE_BYTES = 8 * 1024 * 1024


def _require_lab_access(credentials: HTTPBasicCredentials = Depends(security)) -> None:
    expected_user = os.getenv("RUINFORM_LAB_USER", "maker")
    expected_password = os.getenv("RUINFORM_LAB_PASSWORD")
    if not expected_password:
        raise HTTPException(status_code=503, detail="RUINFORM_LAB_PASSWORD is not configured")
    user_ok = secrets.compare_digest(credentials.username, expected_user)
    password_ok = secrets.compare_digest(credentials.password, expected_password)
    if not (user_ok and password_ok):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid lab credentials",
            headers={"WWW-Authenticate": "Basic"},
        )


def _page(body: str) -> str:
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width,initial-scale=1" />
<title>RUINFORM LAB</title>
<style>
:root {{ color-scheme: dark; }}
* {{ box-sizing: border-box; }}
body {{ margin: 0; background:#0a0a09; color:#e9e3d8; font-family: ui-monospace,SFMono-Regular,Menlo,monospace; }}
main {{ max-width: 980px; margin: 0 auto; padding: 48px 22px 80px; }}
h1 {{ font-size: clamp(38px,8vw,92px); line-height:.9; letter-spacing:-.06em; margin:0 0 18px; }}
.kicker {{ letter-spacing:.18em; font-size:12px; color:#9d9689; margin-bottom:18px; }}
.rule {{ border-top:1px solid #38342e; margin:28px 0; }}
label {{ display:block; margin:18px 0 8px; color:#b9b1a4; }}
input,textarea,button {{ width:100%; background:#11110f; color:#eee7db; border:1px solid #3b3730; padding:14px; font:inherit; }}
button {{ cursor:pointer; margin-top:18px; background:#e8e0d1; color:#111; border:0; font-weight:700; }}
pre {{ white-space:pre-wrap; overflow-wrap:anywhere; background:#11110f; border:1px solid #302d28; padding:18px; line-height:1.5; }}
.material {{ padding:16px 0; border-top:1px solid #302d28; }}
.fact {{ color:#d9d2c4; }} .unknown {{ color:#c9a26b; }} .muted {{ color:#817b70; }}
a {{ color:#d9d2c4; }}
</style>
</head>
<body><main>{body}</main></body></html>"""


@router.get("/lab", response_class=HTMLResponse, dependencies=[Depends(_require_lab_access)])
async def lab_home() -> str:
    configured_openai = bool(os.getenv("OPENAI_API_KEY"))
    configured_higgsfield = bool(os.getenv("HIGGSFIELD_AUTHORIZATION"))
    body = f"""
<div class="kicker">RUINFORM INTELLIGENCE / LIVE LAB / RFM-INT-0002.3.1</div>
<h1>READ<br>MATTER.</h1>
<p>Upload 1–8 real photographs. Material Eye will inspect evidence, separate facts from hypotheses and unknowns, and decide whether there is enough evidence to move toward future forms.</p>
<div class="rule"></div>
<p class="muted">OPENAI: {'CONFIGURED' if configured_openai else 'MISSING'} &nbsp; / &nbsp; HIGGSFIELD: {'CONFIGURED' if configured_higgsfield else 'MISSING'}</p>
<form method="post" action="/lab/analyze" enctype="multipart/form-data">
<label>PHOTOGRAPHS</label>
<input type="file" name="images" accept="image/jpeg,image/png,image/webp" multiple required />
<label>CONTEXT — optional</label>
<textarea name="user_context" rows="4" placeholder="What are these objects? Where did they come from? What tools do you have?"></textarea>
<button type="submit">READ MATTER</button>
</form>
"""
    return _page(body)


@router.post("/lab/analyze", response_class=HTMLResponse, dependencies=[Depends(_require_lab_access)])
async def lab_analyze(
    images: list[UploadFile] = File(...),
    user_context: str = Form(default=""),
) -> str:
    if not 1 <= len(images) <= _MAX_FILES:
        raise HTTPException(status_code=400, detail=f"Upload between 1 and {_MAX_FILES} images")

    evidence: list[EvidenceItem] = []
    for index, image in enumerate(images, start=1):
        media_type = image.content_type or ""
        if media_type not in _ALLOWED_TYPES:
            raise HTTPException(status_code=400, detail=f"Unsupported image type: {media_type or 'unknown'}")
        raw = await image.read(_MAX_FILE_BYTES + 1)
        if len(raw) > _MAX_FILE_BYTES:
            raise HTTPException(status_code=413, detail=f"Image {index} exceeds 8 MB")
        data_url = f"data:{media_type};base64,{base64.b64encode(raw).decode('ascii')}"
        evidence.append(EvidenceItem(evidence_id=f"image_{index:03d}", source_type="image", uri=data_url))

    try:
        state, summary = await analyze_evidence(
            evidence=evidence,
            user_context=user_context.strip() or None,
            constraints=ProjectConstraints(),
        )
    except (MaterialEyeError, ValueError) as exc:
        safe = html.escape(str(exc))
        return HTMLResponse(_page(f"<div class='kicker'>MATERIAL EYE / ERROR</div><h1>STOP.</h1><pre>{safe}</pre><p><a href='/lab'>TRY AGAIN</a></p>"), status_code=502)

    materials_html: list[str] = []
    for material in state.materials:
        observations = "".join(
            f"<div class='fact'>{html.escape(obs.claim_kind.value.upper())} / {html.escape(obs.property_key)} / {html.escape(obs.label)} / confidence={obs.confidence if obs.confidence is not None else 'n/a'}</div>"
            for obs in material.observations
        )
        unknowns = "".join(
            f"<div class='unknown'>UNKNOWN / {html.escape(item.property_key)} — {html.escape(item.question)}</div>"
            for item in material.unknowns
        )
        materials_html.append(f"<section class='material'><strong>{html.escape(material.display_name)}</strong>{observations}{unknowns}</section>")

    gate = "OPEN — READY FOR FUTURES" if can_advance_to_ideation(state) else "BLOCKED — MORE EVIDENCE REQUIRED"
    next_request = html.escape(state.next_user_request or "No additional evidence requested.")
    body = f"""
<div class="kicker">MATERIAL EYE / LIVE RESULT</div>
<h1>{html.escape(gate)}</h1>
<p>{html.escape(summary)}</p>
<div class="rule"></div>
{''.join(materials_html)}
<div class="rule"></div>
<div class="kicker">NEXT REQUEST</div>
<p>{next_request}</p>
<details><summary>PROJECT STATE / JSON</summary><pre>{html.escape(state.model_dump_json(indent=2))}</pre></details>
<p><a href="/lab">ANALYZE ANOTHER OBJECT</a></p>
"""
    return _page(body)

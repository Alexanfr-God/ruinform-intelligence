from __future__ import annotations

from .api import app
from .evidence_api import router as evidence_loop_router
from .evidence_media import router as evidence_media_router
from .future_api import router as future_forms_router
from .lab import router as lab_router
from .lab_postproduction import router as lab_postproduction_router
from .live_api import router as live_transformations_router
from .mvp_entry import router as mvp_entry_router
from .render_api import router as render_router
from . import studio as studio_module
from .studio_controls import router as studio_controls_router
from .studio_evals import router as studio_evals_router


studio_router = studio_module.router

# Keep the two most-used Studio destinations visible on every Studio page.
# This wrapper is intentionally UI-only: it does not touch session state or the
# render/concept pipelines, so a user can always start fresh without hunting
# for /studio/new in chat history.
_original_studio_page = studio_module._page


def _studio_page_with_global_nav(body: str, *, title: str = "RUINFORM STUDIO") -> str:
    nav = """
<style>
.ruinform-global-nav{position:sticky;top:0;z-index:15;display:flex;justify-content:flex-end;gap:10px;padding:10px 0 16px;background:linear-gradient(#080807 72%,rgba(8,8,7,0));}
.ruinform-global-nav a{display:inline-block;text-decoration:none;border:1px solid #5c5448;background:#12110f;color:#eee8dd;padding:10px 13px;font-size:12px;font-weight:700;letter-spacing:.08em;}
.ruinform-global-nav a.primary{background:#e8e0d1;color:#111;border-color:#e8e0d1;}
@media(max-width:760px){.ruinform-global-nav{justify-content:stretch}.ruinform-global-nav a{flex:1;text-align:center}}
</style>
<nav class='ruinform-global-nav' aria-label='Studio navigation'>
<a href='/studio/evals'>EVAL LIBRARY</a>
<a class='primary' href='/studio/new'>+ NEW PROJECT</a>
</nav>
"""
    return _original_studio_page(nav + body, title=title)


_studio_page_with_global_nav._ruinform_nav_wrapped = True
studio_module._page = _studio_page_with_global_nav


app.include_router(evidence_loop_router)
app.include_router(evidence_media_router)
app.include_router(future_forms_router)
app.include_router(render_router)
app.include_router(live_transformations_router)
# Static Studio entry routes must be registered before the dynamic
# /studio/{session_id} routes, otherwise FastAPI treats "new" as a session ID.
app.include_router(mvp_entry_router)
# In-session controls are registered before the main Studio router so control
# edits remain first-class Studio navigation and never fall through to legacy Lab.
app.include_router(studio_controls_router)
# Wave 2 Eval Library includes a static /studio/evals route and patches the
# approved render page with a small human-rating form. Register it before the
# dynamic Studio session router.
app.include_router(studio_evals_router)
app.include_router(studio_router)
# Register post-production before the legacy lab router so the enhanced
# render endpoint owns POST /lab/{session_id}/render/{candidate_id}.
app.include_router(lab_postproduction_router)
app.include_router(lab_router)

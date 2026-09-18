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
from .studio import router as studio_router
from .studio_controls import router as studio_controls_router
from .studio_evals import router as studio_evals_router


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

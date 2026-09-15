from __future__ import annotations

from .api import app
from .evidence_api import router as evidence_loop_router
from .future_api import router as future_forms_router
from .lab import router as lab_router
from .live_api import router as live_transformations_router
from .render_api import router as render_router


app.include_router(evidence_loop_router)
app.include_router(future_forms_router)
app.include_router(render_router)
app.include_router(live_transformations_router)
app.include_router(lab_router)

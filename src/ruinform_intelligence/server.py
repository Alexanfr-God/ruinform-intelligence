from __future__ import annotations

from .api import app
from .evidence_api import router as evidence_loop_router
from .future_api import router as future_forms_router


app.include_router(evidence_loop_router)
app.include_router(future_forms_router)

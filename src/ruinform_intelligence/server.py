from __future__ import annotations

from .api import app
from .evidence_api import router as evidence_loop_router


app.include_router(evidence_loop_router)

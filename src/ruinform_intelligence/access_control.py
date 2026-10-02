from __future__ import annotations

import os
import secrets

from fastapi import HTTPException, Request


async def require_api_access(request: Request) -> None:
    path = request.url.path
    public_object_read = request.method == "GET" and (
        path.startswith("/object/") or path.startswith("/v1/objects/")
    )
    if (
        path == "/health"
        or path.startswith("/lab")
        or path.startswith("/public/evidence/")
        or path == "/studio-login"
        or path.startswith("/studio/")
        or path == "/studio"
        or public_object_read
    ):
        return

    expected = os.getenv("RUINFORM_API_TOKEN")
    if not expected:
        raise HTTPException(status_code=503, detail="RUINFORM_API_TOKEN is not configured")
    supplied = request.headers.get("x-ruinform-key", "")
    if not secrets.compare_digest(supplied, expected):
        raise HTTPException(status_code=401, detail="Unauthorized")

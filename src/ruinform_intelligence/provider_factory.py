from __future__ import annotations

import os

import httpx

from .higgsfield_api import HiggsfieldApi
from .higgsfield_provider import HiggsfieldProvider
from .render_provider import RenderProviderError


def create_higgsfield_provider() -> tuple[HiggsfieldProvider, httpx.AsyncClient]:
    auth_value = os.getenv("HIGGSFIELD_AUTHORIZATION")
    if not auth_value:
        raise RenderProviderError("HIGGSFIELD_AUTHORIZATION must be configured")

    try:
        timeout_seconds = float(os.getenv("RUINFORM_HIGGSFIELD_TIMEOUT_SECONDS", "60"))
    except ValueError as exc:
        raise RenderProviderError("RUINFORM_HIGGSFIELD_TIMEOUT_SECONDS must be numeric") from exc

    if timeout_seconds < 10 or timeout_seconds > 180:
        raise RenderProviderError("RUINFORM_HIGGSFIELD_TIMEOUT_SECONDS must be between 10 and 180")

    client = httpx.AsyncClient(timeout=30.0, headers={"Authorization": auth_value})
    provider = HiggsfieldProvider(
        HiggsfieldApi(client, timeout_seconds=timeout_seconds),
        endpoint=os.getenv("RUINFORM_HIGGSFIELD_IMAGE_ENDPOINT", "/higgsfield-ai/popcorn/auto"),
        resolution=os.getenv("RUINFORM_HIGGSFIELD_RESOLUTION", "1600p"),
    )
    return provider, client

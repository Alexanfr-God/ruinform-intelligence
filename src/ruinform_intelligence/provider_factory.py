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
    client = httpx.AsyncClient(timeout=30.0, headers={"Authorization": auth_value})
    provider = HiggsfieldProvider(
        HiggsfieldApi(client),
        endpoint=os.getenv("RUINFORM_HIGGSFIELD_IMAGE_ENDPOINT", "/higgsfield-ai/popcorn/auto"),
        resolution=os.getenv("RUINFORM_HIGGSFIELD_RESOLUTION", "1600p"),
    )
    return provider, client

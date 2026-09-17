from __future__ import annotations

import os

import httpx
from openai import AsyncOpenAI

from .higgsfield_api import HiggsfieldApi
from .higgsfield_provider import HiggsfieldProvider
from .openai_image_provider import OpenAIImageProvider
from .render_provider import RenderProviderError


def _create_higgsfield_provider() -> tuple[HiggsfieldProvider, httpx.AsyncClient]:
    auth_value = os.getenv("HIGGSFIELD_AUTHORIZATION")
    if not auth_value:
        raise RenderProviderError("HIGGSFIELD_AUTHORIZATION must be configured")

    try:
        timeout_seconds = float(os.getenv("RUINFORM_HIGGSFIELD_TIMEOUT_SECONDS", "120"))
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


def create_render_provider():
    """Create the active image renderer.

    GPT Image is primary for the RUINFORM MVP. Higgsfield remains available as an
    opt-in fallback/benchmark via RUINFORM_RENDER_PROVIDER=higgsfield.
    """
    provider_name = os.getenv("RUINFORM_RENDER_PROVIDER", "openai").strip().lower()

    if provider_name in {"openai", "gpt", "gpt-image", "sunburst"}:
        try:
            timeout_seconds = float(os.getenv("RUINFORM_OPENAI_IMAGE_TIMEOUT_SECONDS", "180"))
        except ValueError as exc:
            raise RenderProviderError("RUINFORM_OPENAI_IMAGE_TIMEOUT_SECONDS must be numeric") from exc
        if timeout_seconds < 30 or timeout_seconds > 300:
            raise RenderProviderError("RUINFORM_OPENAI_IMAGE_TIMEOUT_SECONDS must be between 30 and 300")

        return OpenAIImageProvider(
            AsyncOpenAI(),
            model=os.getenv("RUINFORM_OPENAI_IMAGE_MODEL", "gpt-image-2.5-sunburst"),
            quality=os.getenv("RUINFORM_OPENAI_IMAGE_QUALITY", "high"),
            timeout_seconds=timeout_seconds,
        )

    if provider_name == "higgsfield":
        return _create_higgsfield_provider()

    raise RenderProviderError(
        "RUINFORM_RENDER_PROVIDER must be one of: openai, higgsfield"
    )


def create_higgsfield_provider():
    """Legacy factory name kept so current Studio routes do not need a risky rewrite."""
    return create_render_provider()
